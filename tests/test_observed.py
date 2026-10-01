r"""Tell a replay from a repeat. `docs/0042` I-01, `docs/0045`.

Intent-hash aliasing (`docs/0023` §4) exists for one case: a crash before a
call's result was persisted, after which a different model re-mints the same
call under a new id. It fired on EVERY identical call in a conversation, which
captures the most common loop there is -- edit, run the tests, run them again.

Phase 0 (`docs/0044` N15) hit it in the first two tasks a new user ran:

* the agent ran `python -c "divide(1, 0)"` to show the new error, and that
  deliberate failure became a BLOCKED effect "awaiting your decision";
* `git commit` failed, the agent fixed the cause and re-issued it, and the
  gate refused the identical command twice.

The rule now: once the result is in the history the model reads (OBSERVED),
an identical call is the model's decision. Every crash case is unchanged, and
most of this file is about proving that.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import EffectClass, EffectState, ToolCall, Verdict
from agentctl.kernel.ledger.store import LedgerStore

PYTEST = {"command": "python -m pytest -q"}       # classifies EXTERNAL
COMMIT = {"command": "git commit -m 'add multiply'"}


@pytest.fixture
def gate():
    store = LedgerStore(Path(tempfile.mkdtemp()) / "l.db", holder="t")
    cid = str(uuid.uuid4())
    g = EffectGate(store, Classifier(), fence=store.acquire(cid))
    g.cid = cid
    yield g
    store.close()


def call(g, tcid, args, turn="t"):
    return ToolCall(tcid, g.cid, turn, "execute_bash", dict(args))


# ══ the defect, as P1 reproduced it ═══════════════════════════════════
def test_a_test_rerun_after_seeing_the_result_executes(gate):
    """P1, first half: it used to SUBSTITUTE the old `1 failed`."""
    a = call(gate, "call_A", PYTEST)
    assert gate.guard(a).verdict is Verdict.EXECUTE
    gate.record_observation("call_A", b'{"output":"1 failed"}')

    d = gate.guard(call(gate, "call_B", PYTEST, turn="t5"))
    assert d.verdict is Verdict.EXECUTE, d
    assert d.observation is None, "handed back the stale result"


def test_a_rerun_after_a_seen_failure_executes(gate):
    """P1, second half: it used to BLOCK, and leave a 'needs you' behind."""
    gate.guard(call(gate, "call_C", PYTEST))
    gate.record_observation("call_C", b'{"output":"1 failed"}',
                            error="exit=1 1 failed")

    assert gate.guard(call(gate, "call_D", PYTEST)).verdict is Verdict.EXECUTE
    assert gate.store.blocked(gate.cid) == [], \
        "a failure the model saw is not a decision for a human"


def test_the_phase_0_commit_retry_executes(gate):
    """The exact `docs/0044` N15 sequence: commit fails, the agent fixes the
    identity, and issues the identical command again."""
    gate.guard(call(gate, "c1", COMMIT))
    gate.record_observation("c1", b'{"exit_code":128}',
                            error="Author identity unknown")
    gate.guard(call(gate, "cfg", {"command": "git config user.name me"}))
    gate.record_observation("cfg", b'{"exit_code":0}')

    assert gate.guard(call(gate, "c2", COMMIT)).verdict is Verdict.EXECUTE


def test_a_seen_failure_keeps_its_error_on_record(gate):
    """It is not recorded as a success. Whether it touched the world is
    unknown, and `agentctl show` must still say the tool reported failure."""
    gate.guard(call(gate, "e1", PYTEST))
    gate.record_observation("e1", b"{}", error="exit=1 boom")
    rec = gate.store.lookup("e1")
    assert rec.state is EffectState.OBSERVED
    assert "boom" in rec.error


def test_a_replay_safe_failure_is_still_FAILED(gate):
    """Nothing changes where repeating was always harmless."""
    c = ToolCall("r1", gate.cid, "t", "write_file", {"path": "a", "content": "x"})
    gate.guard(c)
    gate.record_observation("r1", b"{}", error="Permission denied")
    assert gate.store.lookup("r1").state is EffectState.FAILED


# ══ the crash cases must not move ═════════════════════════════════════
def test_an_unobserved_twin_still_substitutes(gate):
    """Crash after the result was recorded but before it was delivered: a
    re-minted identical call must get the recorded result, not run again."""
    gate.guard(call(gate, "x1", PYTEST))
    gate.record_success(call(gate, "x1", PYTEST), b'{"output":"ok"}')  # COMMITTED

    d = gate.guard(call(gate, "x2_reminted", PYTEST))
    assert d.verdict is Verdict.SUBSTITUTE
    assert d.observation == b'{"output":"ok"}'
    assert d.record_id == "x1", "Seam B needs the twin's id to mark it seen"


def test_an_intent_twin_is_still_ambiguous(gate):
    """Crash mid-tool: nobody knows whether it ran. No probe -> fail closed."""
    gate.guard(call(gate, "i1", PYTEST))                             # INTENT
    d = gate.guard(call(gate, "i2_reminted", PYTEST))
    assert d.verdict is Verdict.BLOCK
    assert gate.store.lookup("i1").state is EffectState.BLOCKED


def test_a_blocked_twin_still_blocks(gate):
    """`record_tool_error` (no delivery known) keeps the old, closed shape."""
    gate.guard(call(gate, "b1", PYTEST))
    gate.record_tool_error("b1", "exit=1")
    assert gate.guard(call(gate, "b2", PYTEST)).verdict is Verdict.BLOCK


def test_the_same_id_redriven_still_substitutes(gate):
    """The SDK re-driving the very action it already persisted a result for
    is a replay by definition, whatever the state says."""
    gate.guard(call(gate, "s1", PYTEST))
    gate.record_observation("s1", b'{"output":"ok"}')
    d = gate.guard(call(gate, "s1", PYTEST))
    assert d.verdict is Verdict.SUBSTITUTE and d.observation == b'{"output":"ok"}'


def test_only_the_most_recent_identical_call_counts(gate):
    """An older unresolved twin must not capture a call issued after a newer
    identical one was seen: the model has the newer result in view."""
    gate.guard(call(gate, "o1", PYTEST))
    gate.record_success(call(gate, "o1", PYTEST), b"{}")        # COMMITTED, unseen
    gate.store._db.execute(
        "UPDATE effect_record SET started_at=started_at-100 WHERE tool_call_id='o1'")
    gate.store.write_intent(call(gate, "o2", PYTEST), EffectClass.EXTERNAL,
                            gate.fence)
    gate.record_observation("o2", b"{}")                        # newer, seen
    assert gate.guard(call(gate, "o3", PYTEST)).verdict is Verdict.EXECUTE


# ══ the sole-writer check must still see delivered siblings ═══════════
def test_an_observed_sibling_counts_as_a_writer(gate):
    """`committed_since` read only COMMITTED. Delivered effects now end
    OBSERVED, so without this every ordinary sibling would vanish from the
    check that stops a probe crediting someone else's commit (`docs/0038` §3).
    """
    gate.guard(call(gate, "w1", COMMIT))                 # INTENT, the subject
    rec = gate.store.lookup("w1")
    gate.guard(call(gate, "w2", {"command": "git commit -m other"}))
    gate.record_observation("w2", b"{}")                 # a sibling landed after
    siblings = gate.store.committed_since(gate.cid, rec.started_at, "w1")
    assert [s.tool_call_id for s in siblings] == ["w2"]
    assert gate._sole_writer(rec) is False


# ══ Seam B: the wiring ════════════════════════════════════════════════
class _Obs:
    def __init__(self, error=False, output="ok"):
        self.is_error, self.output, self.exit_code = error, output, int(error)

    def model_dump_json(self):
        return '{"output": "%s"}' % self.output


def _event(action_id, obs):
    ev = type("ObservationEvent", (), {})()
    ev.action_id, ev.observation = action_id, obs
    return ev


def test_seam_b_delivers_a_failure_instead_of_blocking_it(gate):
    from agentctl.adapters.openhands.seam_b import OpenHandsContext, SeamB

    gate.guard(call(gate, "tc", PYTEST))
    seam = SeamB(gate, ctx=OpenHandsContext(gate.cid))
    seam._pending["act-1"] = "tc"
    seam._close(_event("act-1", _Obs(error=True, output="1 failed")))

    rec = gate.store.lookup("tc")
    assert rec.state is EffectState.OBSERVED and "1 failed" in rec.error
    assert gate.store.blocked(gate.cid) == []


def test_seam_b_marks_a_substituted_result_observed(gate):
    """After a crash, Seam C hands back the recorded result. Once that reaches
    the model, a later deliberate repeat must run, not get the old output."""
    from agentctl.adapters.openhands.seam_b import OpenHandsContext, SeamB

    gate.guard(call(gate, "orig", PYTEST))
    gate.record_success(call(gate, "orig", PYTEST), b"{}")      # COMMITTED

    class Handoff:
        def offer(self, *a):
            pass

    seam = SeamB(gate, ctx=OpenHandsContext(gate.cid), handoff=Handoff())
    seam._state = object()
    action = type("ActionEvent", (), {})()
    action.id, action.tool_call_id, action.tool_name = "act-9", "remint", "execute_bash"
    action.action = type("A", (), {"model_dump": lambda self: dict(PYTEST)})()
    seam._decide(action)
    assert gate.store.lookup("orig").state is EffectState.COMMITTED

    seam._close(_event("act-9", _Obs()))
    assert gate.store.lookup("orig").state is EffectState.OBSERVED
    assert gate.guard(call(gate, "later", PYTEST)).verdict is Verdict.EXECUTE
