"""The effect gate. Spec: `docs/0011` §3, `docs/0012` §3.2.

The correctness core, and deliberately small. One rule dominates:

    guard() MUST NEVER RAISE.

Any internal failure becomes BLOCK — fail closed (`docs/0008` §6.5). A gate
that crashes open is worse than no gate, because it creates false confidence.
"""
from __future__ import annotations

import logging

from .classify import Classifier
from .ledger.models import (
    EffectClass,
    EffectState,
    GateDecision,
    ToolCall,
    Verdict,
)
from .ledger.store import LedgerStore

log = logging.getLogger("agentctl.gate")


class EffectGate:
    """Decides whether a tool call may execute.

    Seam-agnostic by design (`docs/0012` §3.2.1): it returns a decision, and
    the binding acts on it. Seam B can honour BLOCK/ESCALATE; only Seam C can
    honour SUBSTITUTE.
    """

    def __init__(
        self,
        store: LedgerStore,
        classifier: Classifier | None = None,
        probes: dict | None = None,
        fence: int = 0,
    ):
        self.store = store
        self.classifier = classifier or Classifier()
        self.probes = probes or {}
        self.fence = fence

    # ── the decision ───────────────────────────────────────────────────
    def guard(self, call: ToolCall) -> GateDecision:
        try:
            return self._guard(call)
        except Exception as exc:                       # noqa: BLE001
            # Fail closed. Never let a gate bug become an unguarded effect.
            log.exception("gate failure for %s", call.tool_call_id)
            self._try_block(call.tool_call_id, f"gate error: {exc!r}")
            return GateDecision(
                Verdict.BLOCK, reason=f"gate error, failing closed: {exc!r}"
            )

    def _guard(self, call: ToolCall) -> GateDecision:
        cls = self.classifier.classify(call)
        rec = self.store.lookup(call.tool_call_id)

        # First sighting — the common case.
        if rec is None:
            self.store.write_intent(call, cls, self.fence)
            return GateDecision(Verdict.EXECUTE, cls)

        # Same id, different arguments. Substituting here would return the
        # wrong observation, so refuse outright.
        if rec.intent_hash != call.intent_hash():
            return GateDecision(
                Verdict.BLOCK, cls,
                reason="tool_call_id reused with different arguments",
            )

        if rec.state in (EffectState.COMMITTED, EffectState.OBSERVED):
            return GateDecision(Verdict.SUBSTITUTE, cls, observation=rec.observation)

        if rec.state is EffectState.FAILED:
            self.store.write_intent(call, cls, self.fence)   # bumps attempt
            return GateDecision(Verdict.EXECUTE, cls)

        if rec.state is EffectState.BLOCKED:
            return GateDecision(
                Verdict.BLOCK, cls,
                reason=rec.error or "previously blocked; awaiting human decision",
            )

        # rec.state is INTENT — the irreducible ambiguity (docs/0008 §6.5).
        return self._resolve_ambiguous(call, rec, cls)

    def _resolve_ambiguous(self, call, rec, cls: EffectClass) -> GateDecision:
        """We cannot tell whether the effect landed. Decide by class."""
        if cls.replay_safe:
            # Repeating is harmless, so the window does not matter.
            return GateDecision(Verdict.EXECUTE, cls)

        if cls is EffectClass.DESTRUCTIVE:
            self.store.block(call.tool_call_id, "destructive effect, outcome unknown")
            return GateDecision(
                Verdict.ESCALATE, cls,
                reason="destructive effect with unknown outcome; a human must decide",
            )

        # NON_IDEMPOTENT_WRITE / EXTERNAL: ask the world if it can answer.
        probe_name = self.classifier.probe_for(call)
        probe = self.probes.get(probe_name) if probe_name else None
        if probe is not None:
            verdict = probe.probe(call, rec)
            if verdict == "LANDED":
                self.store.reconcile(call.tool_call_id, verdict, landed=True)
                return GateDecision(
                    Verdict.SUBSTITUTE, cls, observation=rec.observation,
                    reason="probe found the effect already landed",
                )
            if verdict == "DID_NOT_LAND":
                self.store.reconcile(call.tool_call_id, verdict, landed=False)
                self.store.write_intent(call, cls, self.fence)
                return GateDecision(Verdict.EXECUTE, cls)

        # No probe, or inconclusive. Fail closed.
        reason = (
            f"cannot determine whether {call.tool_name} already executed"
            f"{' (no probe available)' if probe is None else ' (probe inconclusive)'}"
        )
        self.store.block(call.tool_call_id, reason)
        return GateDecision(Verdict.BLOCK, cls, reason=reason)

    # ── post-execution bookkeeping ─────────────────────────────────────
    def record_success(self, call: ToolCall, observation: bytes | None = None) -> None:
        try:
            self.store.commit(call.tool_call_id, observation)
        except Exception:                               # noqa: BLE001
            log.exception("could not commit %s", call.tool_call_id)

    def record_failure(self, call: ToolCall, error: str) -> None:
        try:
            self.store.fail(call.tool_call_id, error)
        except Exception:                               # noqa: BLE001
            log.exception("could not record failure for %s", call.tool_call_id)

    def record_success_by_id(self, tool_call_id: str, observation: bytes | None = None) -> None:
        try:
            self.store.commit(tool_call_id, observation)
        except Exception:                               # noqa: BLE001
            log.exception("could not commit %s", tool_call_id)

    def record_failure_by_id(self, tool_call_id: str, error: str) -> None:
        try:
            self.store.fail(tool_call_id, error)
        except Exception:                               # noqa: BLE001
            log.exception("could not record failure for %s", tool_call_id)

    def _try_block(self, tool_call_id: str, reason: str) -> None:
        try:
            if self.store.lookup(tool_call_id):
                self.store.block(tool_call_id, reason)
        except Exception:                               # noqa: BLE001
            log.exception("could not block %s", tool_call_id)
