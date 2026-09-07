"""Gate decisions. docs/0011 §3.

The rule under test above all others: guard() never raises.
"""
import pytest

from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import EffectClass, EffectState, ToolCall, Verdict
from agentctl.kernel.ledger.store import LedgerStore


@pytest.fixture
def gate(tmp_path):
    store = LedgerStore(tmp_path / "l.db", holder="test")
    yield EffectGate(store, Classifier(), fence=store.acquire("conv_1"))
    store.close()


def call(cid="tc_1", tool="write_file", **args):
    return ToolCall(cid, "conv_1", "turn_1", tool, args or {"path": "a.txt"})


def bash(cmd, cid="tc_b"):
    return ToolCall(cid, "conv_1", "turn_1", "execute_bash", {"command": cmd})


def test_first_sighting_executes_and_writes_intent(gate):
    c = call()
    d = gate.guard(c)
    assert d.verdict is Verdict.EXECUTE
    assert gate.store.lookup(c.tool_call_id).state is EffectState.INTENT


def test_committed_effect_is_substituted_not_repeated(gate):
    c = call()
    gate.guard(c)
    gate.record_success(c, b'{"ok":1}')
    d = gate.guard(c)
    assert d.verdict is Verdict.SUBSTITUTE
    assert d.observation == b'{"ok":1}'


def test_reused_id_with_different_args_is_blocked(gate):
    gate.guard(call("tc_x", path="a.txt"))
    d = gate.guard(call("tc_x", path="DIFFERENT.txt"))
    assert d.verdict is Verdict.BLOCK
    assert "different arguments" in d.reason


def test_ambiguous_read_re_executes(gate):
    """PURE_READ escapes the ambiguous branch cheaply."""
    c = bash("ls -la")
    gate.guard(c)                                   # leaves INTENT
    assert gate.guard(c).verdict is Verdict.EXECUTE


def test_ambiguous_idempotent_write_re_executes(gate):
    c = call("tc_w", tool="write_file")
    gate.guard(c)
    assert gate.guard(c).verdict is Verdict.EXECUTE


def test_ambiguous_non_idempotent_blocks_without_a_probe(gate):
    """THE CORE CASE: a git commit whose outcome is unknown must not repeat."""
    c = bash("git commit -m 'work'", cid="tc_commit")
    assert gate.guard(c).verdict is Verdict.EXECUTE      # first time
    d = gate.guard(c)                                   # crash, then resume
    assert d.verdict is Verdict.BLOCK
    assert gate.store.lookup(c.tool_call_id).state is EffectState.BLOCKED


def test_ambiguous_destructive_escalates(gate):
    c = bash("rm -rf /tmp/x", cid="tc_rm")
    gate.guard(c)
    d = gate.guard(c)
    assert d.verdict is Verdict.ESCALATE
    assert d.effect_class is EffectClass.DESTRUCTIVE


def _stub(verdict):
    from agentctl.kernel.reconcile.base import ProbeRegistry

    class Stub:
        name = "git"
        def handles(self, call): return True
        def capture(self, call): return {"probe": "git"}
        def probe(self, call, rec): return verdict
    return ProbeRegistry(Stub())


def test_probe_landed_substitutes(gate):
    gate.probes = _stub("LANDED")
    c = bash("git commit -m x", cid="tc_p1")
    gate.guard(c)
    assert gate.guard(c).verdict is Verdict.SUBSTITUTE


def test_probe_did_not_land_re_executes(gate):
    gate.probes = _stub("DID_NOT_LAND")
    c = bash("git commit -m x", cid="tc_p2")
    gate.guard(c)
    assert gate.guard(c).verdict is Verdict.EXECUTE


def test_inconclusive_probe_fails_closed(gate):
    gate.probes = _stub("INCONCLUSIVE")
    c = bash("git commit -m x", cid="tc_p3")
    gate.guard(c)
    assert gate.guard(c).verdict is Verdict.BLOCK


def test_guard_never_raises_and_fails_closed(tmp_path):
    """A gate that crashes open is worse than no gate."""
    store = LedgerStore(tmp_path / "l.db")

    class Exploding(Classifier):
        def classify(self, call): raise RuntimeError("classifier is broken")

    g = EffectGate(store, Exploding())
    d = g.guard(call())
    assert d.verdict is Verdict.BLOCK
    assert "failing closed" in d.reason
    store.close()


def test_blocked_stays_blocked(gate):
    c = bash("git commit -m x", cid="tc_bb")
    gate.guard(c); gate.guard(c)                    # -> BLOCKED
    assert gate.guard(c).verdict is Verdict.BLOCK


def test_a_probe_that_raises_fails_closed(gate):
    """A broken probe must not become an unguarded effect."""
    from agentctl.kernel.reconcile.base import ProbeRegistry

    class Exploding:
        name = "git"
        def handles(self, call): return True
        def capture(self, call): raise RuntimeError("capture is broken")
        def probe(self, call, rec): raise RuntimeError("probe is broken")

    gate.probes = ProbeRegistry(Exploding())
    c = bash("git commit -m x", cid="tc_boom")
    assert gate.guard(c).verdict is Verdict.EXECUTE     # capture failure is survivable
    assert gate.guard(c).verdict is Verdict.BLOCK       # probe failure fails closed


def test_pre_state_is_captured_for_dangerous_classes_only(gate):
    from agentctl.kernel.reconcile.base import ProbeRegistry

    class Stub:
        name = "git"
        def handles(self, call): return True
        def capture(self, call): return {"probe": "git", "head": "abc"}
        def probe(self, call, rec): return "INCONCLUSIVE"

    gate.probes = ProbeRegistry(Stub())
    dangerous = bash("git commit -m x", cid="tc_pre1")
    gate.guard(dangerous)
    assert gate.store.lookup("tc_pre1").pre_state is not None

    safe = bash("ls -la", cid="tc_pre2")
    gate.guard(safe)
    assert gate.store.lookup("tc_pre2").pre_state is None,         "no point fingerprinting the world for a read"
