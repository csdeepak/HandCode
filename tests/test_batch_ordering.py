r"""A batch shares one pre-state, and the probe cannot tell its members apart.

The SDK emits every `ActionEvent` in one assistant message -- and therefore
runs every gate decision and every `capture()` -- **before** executing any of
them (`openhands/sdk/agent/agent.py::_ActionBatch.prepare` partitions blocked
from executable, then executes the batch). Two HEAD-moving calls in one message
consequently fingerprint the *same* HEAD.

`GitProbe.probe` states the assumption that breaks here, in its own words:

    HEAD moved during the crash window. With a single writer in
    the workspace, that was our commit.

A sibling call in the same batch is a second writer. So when the first commit
lands and the process dies before the second runs, the second call's probe sees
a moved HEAD, returns LANDED, and the gate SUBSTITUTEs -- silently dropping a
commit the agent intended and recording it as though it had happened.

One agent. One conversation. `tool_concurrency_limit=1`. The nine-point suite
cannot see this because its worker issues one effect per run (`docs/0038` §3).

## The fix has two halves, and they cover different ground

**Seam C re-captures** (`EffectGate.recapture`) so each call is fingerprinted
at its own execution moment rather than once for the whole batch. That makes
the probe's answer correct in the ordinary case.

**The gate checks the assumption** (`EffectGate._sole_writer`) before trusting
any world-state verdict, so a LANDED reached while a sibling was also writing
is downgraded rather than believed.

The first buys clean resume. The second is what happens when the crash lands
before the first can help — and it fails closed, which is the whole design.
"""
import json
import shutil
import subprocess

import pytest

from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import EffectState, ToolCall, Verdict
from agentctl.kernel.ledger.store import LedgerStore
from agentctl.kernel.reconcile import default_registry
from agentctl.kernel.reconcile.base import LANDED

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("one\n", encoding="utf-8")
    (r / "b.txt").write_text("one\n", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "initial")
    return r


@pytest.fixture
def gate(tmp_path, repo):
    store = LedgerStore(tmp_path / "l.db", holder="test")
    yield EffectGate(store, Classifier(), default_registry(repo),
                     fence=store.acquire("conv_1"))
    store.close()


def commit_call(message, path, repo, cid):
    """One `git commit` the agent asked for, as the harness would present it."""
    return ToolCall(cid, "conv_1", "turn_1", "execute_bash",
                    {"command": f"git commit -m {message} -- {path}",
                     "cwd": str(repo)})


def pre_head(gate, tool_call_id):
    raw = gate.store.lookup(tool_call_id).pre_state
    return json.loads(raw)["head"] if raw else None


def head(repo):
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def dirty(repo):
    """Both tracked files modified, so each call has something to commit."""
    (repo / "a.txt").write_text("edited for the first commit\n", encoding="utf-8")
    (repo / "b.txt").write_text("edited for the second commit\n", encoding="utf-8")


# ══ the shape of the hazard ══════════════════════════════════════════
@needs_git
def test_batch_members_capture_the_same_head(repo, gate):
    """The precondition: one batch, one decision pass, one shared pre-state.

    Not itself the bug -- the ground the bug stands on. Asserted separately so
    a change in batch semantics shows up here first.
    """
    dirty(repo)
    first = commit_call("first", "a.txt", repo, "tc_first")
    second = commit_call("second", "b.txt", repo, "tc_second")

    assert gate.guard(first).verdict is Verdict.EXECUTE
    assert gate.guard(second).verdict is Verdict.EXECUTE

    assert pre_head(gate, "tc_first") == pre_head(gate, "tc_second") == head(repo)


@needs_git
def test_probe_alone_cannot_tell_a_siblings_commit_from_its_own(repo, gate):
    """Characterisation, not a defect: this is why the gate checks.

    The probe is handed one record and asked about the world. It cannot see
    siblings, so a moved HEAD reads as LANDED even when another call moved it.
    Pinned here so the gate's `_sole_writer` guard is never mistaken for
    belt-and-braces and removed.
    """
    dirty(repo)
    second = commit_call("second", "b.txt", repo, "tc_second")
    gate.guard(second)
    rec = gate.store.lookup("tc_second")

    git(repo, "commit", "-qm", "first", "--", "a.txt")   # a sibling commits

    probe = gate.probes.for_call(second, "git")
    assert probe.probe(second, rec) == LANDED, (
        "the probe's contract is world-state only; if it learns about "
        "siblings, the gate's guard can be reconsidered"
    )


# ══ the fix ══════════════════════════════════════════════════════════
@needs_git
def test_recapture_at_execution_time_re_drives_the_dropped_commit(repo, gate):
    """The ordinary path: Seam C re-fingerprints, so the probe is right.

    Sequence, all within one agent and one conversation:

        1. The model emits two commits in one assistant message.
        2. Seam B gates both.
        3. Seam C re-captures for the first; it executes and lands.
        4. Seam C re-captures for the second.
        5. The process dies before the second executes.
        6. On resume the second is re-driven through the gate.
    """
    dirty(repo)
    first = commit_call("first", "a.txt", repo, "tc_first")
    second = commit_call("second", "b.txt", repo, "tc_second")

    assert gate.guard(first).verdict is Verdict.EXECUTE
    assert gate.guard(second).verdict is Verdict.EXECUTE

    gate.recapture(first)                               # Seam C, first call
    git(repo, "commit", "-qm", "first", "--", "a.txt")
    gate.record_success(first, b"[committed]")
    landed_head = head(repo)

    gate.recapture(second)                              # Seam C, second call
    # ── the process dies here; `tc_second` never ran ──
    assert gate.store.lookup("tc_second").state is EffectState.INTENT
    assert pre_head(gate, "tc_second") == landed_head, \
        "the re-capture must see the world the first commit left behind"

    decision = gate.guard(second)

    assert decision.verdict is Verdict.EXECUTE, (
        f"the second commit never ran and must be re-driven, got "
        f"{decision.verdict} -- {decision.reason!r}"
    )
    assert head(repo) == landed_head, "sanity: nothing else moved HEAD"


def test_seam_c_actually_triggers_the_recapture():
    """The route, not just the result (`docs/0024`).

    `recapture` being correct is worth nothing if nothing calls it. This
    asserts the Seam B -> Seam C wiring fires, with no harness present.
    """
    from agentctl.adapters.openhands.handoff import SubstitutionHandoff

    fired = []
    handoff = SubstitutionHandoff()
    action = object()
    call = ToolCall("tc_1", "conv_1", "turn_1", "execute_bash", {"command": "x"})

    handoff.arm(action, call, lambda: fired.append(call.tool_call_id))

    assert handoff.before_execute(action, "execute_bash", {"command": "x"}) is True
    assert fired == ["tc_1"], "Seam C did not trigger the re-capture"

    assert handoff.before_execute(action, "execute_bash", {"command": "x"}) is False, \
        "an armed call is consumed once, like a substitution"
    assert fired == ["tc_1"]


@needs_git
def test_crash_before_recapture_fails_closed(repo, gate):
    """The gap re-capture cannot cover: fail closed, never substitute.

    If the crash lands between the batch decision and Seam C, the second call
    still carries the stale batch fingerprint. The probe will say LANDED. The
    gate must not believe it -- a sibling committed inside the window.
    """
    dirty(repo)
    first = commit_call("first", "a.txt", repo, "tc_first")
    second = commit_call("second", "b.txt", repo, "tc_second")

    gate.guard(first)
    gate.guard(second)

    # The first lands. The second never reaches Seam C, so it is never
    # re-captured and its fingerprint still describes the pre-batch world.
    git(repo, "commit", "-qm", "first", "--", "a.txt")
    gate.record_success(first, b"[committed]")

    decision = gate.guard(second)

    assert decision.verdict is not Verdict.SUBSTITUTE, (
        "a commit that never ran was reported as already landed -- it would "
        "be dropped and the ledger would say it happened"
    )
    assert decision.verdict is Verdict.BLOCK, (
        f"the outcome is genuinely unknown, so a human must decide; got "
        f"{decision.verdict}"
    )
    assert gate.store.lookup("tc_second").state is EffectState.BLOCKED
