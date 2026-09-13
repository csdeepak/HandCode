r"""A tool that RAN and FAILED is a third outcome. `docs/0031` §10.

Found in a real user's ledger: five shell commands exited 1 and every one was
recorded `COMMITTED`. Seam B decided success from the SDK *event type*, and a
failed tool still arrives as an ordinary `ObservationEvent`.

The consequence runs the opposite way to this project's usual worry. It does
not duplicate an effect -- it makes a resume treat work that never happened as
done, and skip it. Under-execution, silently.

The fix must not over-correct. `FAILED` means *provably did not land*, and a
non-zero exit is not proof: `echo x > a.txt && bad` writes the file and exits
1. So the split is on whether repeating is safe.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from agentctl.adapters.openhands.seam_b import _tool_error
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import EffectClass, EffectState, ToolCall
from agentctl.kernel.ledger.store import LedgerStore


class Obs:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class Ev:
    def __init__(self, observation):
        self.observation = observation


# ── detecting it ───────────────────────────────────────────────────────
def test_a_successful_observation_is_not_an_error():
    assert _tool_error(Ev(Obs(is_error=False, output="fine"))) is None


def test_a_failed_shell_command_is_detected_with_its_message():
    """The exact case: cmd.exe rejecting a bash heredoc."""
    why = _tool_error(Ev(Obs(is_error=True, exit_code=1,
                             output="<< was unexpected at this time.")))
    assert why and "<< was unexpected" in why


def test_a_failed_write_is_detected():
    why = _tool_error(Ev(Obs(is_error=True, status="error: Permission denied")))
    assert why and "Permission denied" in why


@pytest.mark.parametrize("event", [Ev(None), Ev(Obs(output="x"))])
def test_cannot_tell_is_not_the_same_as_failed(event):
    """An unreadable event must not block work for no reason."""
    assert _tool_error(event) is None


# ── recording it ───────────────────────────────────────────────────────
def _gate_with(cls: EffectClass):
    ws = Path(tempfile.mkdtemp())
    store = LedgerStore(ws / "l.db", holder="t")
    cid = str(uuid.uuid4())
    fence = store.acquire(cid)
    gate = EffectGate(store=store, fence=fence)
    call = ToolCall(tool_call_id="tc-1", conversation_id=cid, turn_id="t1",
                    tool_name="execute_bash", args={"command": "x"})
    store.write_intent(call, cls, fence, None)
    return store, gate, call


def test_a_retry_safe_effect_is_marked_FAILED_so_it_can_be_retried():
    """Nothing is lost by running an idempotent write again."""
    store, gate, call = _gate_with(EffectClass.IDEMPOTENT_WRITE)
    gate.record_tool_error("tc-1", "exit=1 << was unexpected")
    rec = store.lookup("tc-1")
    assert rec.state is EffectState.FAILED
    assert "unexpected" in (rec.error or "")
    store.close()


def test_an_unrepeatable_effect_is_BLOCKED_not_failed():
    """`FAILED` claims it provably did not land. Nobody knows that here.

    `echo x > a.txt && bad` writes the file and exits 1, so asserting it did
    not land would permit a duplicate -- the direction `docs/0008` §6.5 says
    must fail closed.
    """
    store, gate, call = _gate_with(EffectClass.NON_IDEMPOTENT_WRITE)
    gate.record_tool_error("tc-1", "exit=1")
    rec = store.lookup("tc-1")
    assert rec.state is EffectState.BLOCKED
    assert "whether it landed is unknown" in (rec.error or "")
    store.close()


def test_an_external_effect_is_blocked_too():
    store, gate, call = _gate_with(EffectClass.EXTERNAL)
    gate.record_tool_error("tc-1", "exit=1")
    assert store.lookup("tc-1").state is EffectState.BLOCKED
    store.close()


def test_a_failed_effect_is_never_COMMITTED():
    """The bug itself, stated as an invariant."""
    for cls in (EffectClass.PURE_READ, EffectClass.IDEMPOTENT_WRITE,
                EffectClass.NON_IDEMPOTENT_WRITE, EffectClass.EXTERNAL,
                EffectClass.DESTRUCTIVE):
        store, gate, call = _gate_with(cls)
        gate.record_tool_error("tc-1", "exit=1")
        assert store.lookup("tc-1").state is not EffectState.COMMITTED, cls
        store.close()


def test_recording_an_error_never_raises():
    """The gate must not take down the agent loop (`docs/0012` §3.2)."""
    store, gate, _ = _gate_with(EffectClass.PURE_READ)
    gate.record_tool_error("no-such-id", "exit=1")     # must not raise
    store.close()


# ── the wiring, which is where the bug actually lived ──────────────────
def test_seam_b_does_not_commit_a_failed_observation():
    """This is the regression test for the real defect.

    Against the old code this fails: `_close` looked only at the event TYPE,
    an `ObservationEvent` meant success, and a command that exited 1 was
    committed.
    """
    from agentctl.adapters.openhands.seam_b import OpenHandsContext, SeamB

    store, gate, call = _gate_with(EffectClass.IDEMPOTENT_WRITE)
    seam = SeamB(gate, ctx=OpenHandsContext(call.conversation_id))
    seam._pending["act-1"] = "tc-1"

    class FailedObservation:
        is_error = True
        exit_code = 1
        output = "<< was unexpected at this time."

        def model_dump_json(self):
            return '{"exit_code": 1}'

    class ObservationEvent:                 # the class NAME is what seam B saw
        action_id = "act-1"
        observation = FailedObservation()

    seam._close(ObservationEvent())

    rec = store.lookup("tc-1")
    assert rec.state is not EffectState.COMMITTED, \
        "a command that exited 1 was recorded as COMMITTED"
    assert rec.state is EffectState.FAILED
    store.close()


def test_seam_b_still_commits_a_successful_observation():
    """The other half: this must not start blocking ordinary work."""
    from agentctl.adapters.openhands.seam_b import OpenHandsContext, SeamB

    store, gate, call = _gate_with(EffectClass.IDEMPOTENT_WRITE)
    seam = SeamB(gate, ctx=OpenHandsContext(call.conversation_id))
    seam._pending["act-1"] = "tc-1"

    class GoodObservation:
        is_error = False
        exit_code = 0
        output = "written"

        def model_dump_json(self):
            return '{"exit_code": 0}'

    class ObservationEvent:
        action_id = "act-1"
        observation = GoodObservation()

    seam._close(ObservationEvent())
    assert store.lookup("tc-1").state is EffectState.COMMITTED
    store.close()
