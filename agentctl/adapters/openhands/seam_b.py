"""Seam B binding for OpenHands. Spec: `docs/0008` §3.5, `docs/0012` §3.2.1.

Binds BLOCK and ESCALATE via `ConversationState.block_action`, which fires from
the event callback when an `ActionEvent` is emitted — before the tool runs
(`docs/0015` §2).

This is the whole of M2a. No executor wrapping, no fork, and it already gives
correct fail-closed behaviour: a dangerous effect whose outcome is unknown is
refused rather than repeated. What it cannot do is SUBSTITUTE a stored
observation — that needs Seam C (M2b).

Usage — note the two-step, forced by a chicken-and-egg: callbacks are passed at
construction, but the callback needs the conversation it is attached to.

    seam = SeamB(gate)
    conv = Conversation(agent=..., callbacks=[seam])
    seam.attach(conv)
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import GateDecision, ToolCall, Verdict

log = logging.getLogger("agentctl.seam_b")


class OpenHandsContext:
    """Everything harness-specific lives here.

    Keeping the translation in one small class is what makes porting to another
    harness cheap (`docs/0008` §12).
    """

    def __init__(self, conversation_id: str):
        self.conversation_id = conversation_id

    def to_tool_call(self, event: Any) -> ToolCall | None:
        """Normalise an ActionEvent into a harness-neutral ToolCall."""
        tool_call_id = getattr(event, "tool_call_id", None)
        if not tool_call_id:
            tc = getattr(event, "tool_call", None)
            tool_call_id = getattr(tc, "id", None) if tc else None
        if not tool_call_id:
            return None

        action = getattr(event, "action", None)
        args: dict = {}
        if action is not None:
            try:
                args = action.model_dump()
            except Exception:                           # noqa: BLE001
                args = {k: v for k, v in vars(action).items()
                        if not k.startswith("_")}
        args.pop("kind", None)

        return ToolCall(
            tool_call_id=str(tool_call_id),
            conversation_id=self.conversation_id,
            turn_id=str(getattr(event, "id", "") or ""),
            tool_name=str(getattr(event, "tool_name", "") or ""),
            args=args,
        )

    @staticmethod
    def serialize(event_or_observation: Any) -> bytes:
        """Serialize the Observation, not the wrapping ObservationEvent.

        Seam C revives this with `observation_type.model_validate_json`, so it
        must be the observation's own shape.
        """
        obj = getattr(event_or_observation, "observation", None) or event_or_observation
        try:
            return obj.model_dump_json().encode()
        except Exception:                               # noqa: BLE001
            return json.dumps(str(obj)).encode()


def is_action_event(event: Any) -> bool:
    """Duck-typed so nothing here needs the SDK imported."""
    return (
        type(event).__name__ == "ActionEvent"
        and getattr(event, "action", None) is not None
    )


def is_observation_event(event: Any) -> bool:
    return type(event).__name__ in ("ObservationEvent", "AgentErrorEvent")


class SeamB:
    """Event callback that enforces the gate's BLOCK/ESCALATE verdicts.

    Relies on the ordering contract in `docs/0006:V1`: the ActionEvent is
    persisted, and callbacks fire, *before* the tool executes. Blocking here
    prevents execution rather than merely recording disapproval.
    """

    def __init__(
        self,
        gate: EffectGate,
        ctx: OpenHandsContext | None = None,
        on_decision: Callable[[ToolCall, GateDecision], None] | None = None,
        handoff: Any = None,
    ):
        self.gate = gate
        self.ctx = ctx
        self.on_decision = on_decision
        # When Seam C is installed, SUBSTITUTE is handed to it instead of being
        # downgraded to a block. Without it, behaviour degrades to M2a:
        # still correct, just a rejection where a result was possible.
        self.handoff = handoff
        self._state: Any = None
        self._pending: dict[str, str] = {}    # action_event_id -> tool_call_id

    def attach(self, conversation: Any) -> "SeamB":
        """Bind to a live conversation. Call immediately after construction."""
        self._state = conversation.state
        if self.ctx is None:
            self.ctx = OpenHandsContext(str(conversation.state.id))
        return self

    # ── the callback ───────────────────────────────────────────────────
    def __call__(self, event: Any) -> None:
        try:
            if is_observation_event(event):
                self._close(event)
                return
            if not is_action_event(event):
                return
            if self._state is None:
                log.error("SeamB not attached; the gate is INERT. "
                          "Call seam.attach(conversation) after construction.")
                return
            self._decide(event)
        except Exception:                               # noqa: BLE001
            # A callback bug must not take down the agent loop, but it must
            # never silently disable the guard either. Log loudly.
            log.exception("seam B callback failed for %r", event)

    # ── internals ──────────────────────────────────────────────────────
    def _decide(self, event: Any) -> None:
        assert self.ctx is not None
        call = self.ctx.to_tool_call(event)
        if call is None:
            return

        decision = self.gate.guard(call)

        if decision.verdict is Verdict.EXECUTE:
            self._pending[str(event.id)] = call.tool_call_id

        elif decision.verdict in (Verdict.BLOCK, Verdict.ESCALATE):
            reason = decision.reason or "blocked by agentctl"
            self._state.block_action(event.id, reason)
            log.warning("BLOCKED %s (%s): %s",
                        call.tool_name, call.tool_call_id, reason)

        elif decision.verdict is Verdict.SUBSTITUTE:
            if self.handoff is not None:
                # Seam C will return the recorded observation. Let the harness
                # proceed to the executor -- it never reaches the real tool.
                self.handoff.offer(event.action, call, decision.observation)
                log.info("handing %s to Seam C for substitution", call.tool_call_id)
            else:
                # No Seam C: block instead. Correctness preserved, resume
                # quality is not. docs/0008 §3.5 -- degrade, never fail open.
                reason = (
                    f"{call.tool_name} already ran and its result was recorded; "
                    f"agentctl blocked a repeat. Install the Seam C executor "
                    f"wrap to resume cleanly instead of blocking."
                )
                self._state.block_action(event.id, reason)
                log.warning("SUBSTITUTE needed, Seam B can only block: %s",
                            call.tool_call_id)

        if self.on_decision:
            self.on_decision(call, decision)

    def _close(self, event: Any) -> None:
        """Close the ledger record. Pure observation, so Seam B can do it."""
        tcid = self._pending.pop(getattr(event, "action_id", None), None)
        if tcid is None:
            return
        assert self.ctx is not None
        if type(event).__name__ == "AgentErrorEvent":
            self.gate.record_failure_by_id(
                tcid, str(getattr(event, "error", "tool error"))[:500])
        else:
            self.gate.record_success_by_id(tcid, self.ctx.serialize(event))


def make_seam_b_callback(
    conversation: Any,
    gate: EffectGate,
    ctx: OpenHandsContext | None = None,
    on_decision: Callable[[ToolCall, GateDecision], None] | None = None,
) -> SeamB:
    """Convenience for when the conversation already exists."""
    return SeamB(gate, ctx, on_decision).attach(conversation)
