"""The effect gate. Spec: `docs/0011` §3, `docs/0012` §3.2.

The correctness core, and deliberately small. One rule dominates:

    guard() MUST NEVER RAISE.

Any internal failure becomes BLOCK — fail closed (`docs/0008` §6.5). A gate
that crashes open is worse than no gate, because it creates false confidence.
"""
from __future__ import annotations

import json
import logging

from .classify import Classifier
from .reconcile.base import (
    DID_NOT_LAND, INCONCLUSIVE, LANDED, SAFE_TO_RETRY, ProbeRegistry,
)
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
        probes: ProbeRegistry | None = None,
        fence: int = 0,
    ):
        self.store = store
        self.classifier = classifier or Classifier()
        self.probes = probes if probes is not None else ProbeRegistry()
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

        if rec is None and not cls.replay_safe:
            # The id is model-minted, so a different model answering the same
            # question produces a different one for the identical call
            # (`docs/0023` §4). Before calling this a first sighting, ask
            # whether this exact effect is already on record under another id.
            twin = self.store.find_by_intent(call.conversation_id,
                                             call.intent_hash())
            if twin is not None:
                log.info("matched %s to prior effect %s by intent hash",
                         call.tool_call_id, twin.tool_call_id)
                return self._decide_on(call, twin, cls, aliased=True)

        # First sighting — the common case.
        if rec is None:
            self.store.write_intent(call, cls, self.fence, self._capture(call, cls))
            return GateDecision(Verdict.EXECUTE, cls)

        # Same id, different arguments. Substituting here would return the
        # wrong observation, so refuse outright.
        if rec.intent_hash != call.intent_hash():
            return GateDecision(
                Verdict.BLOCK, cls,
                reason="tool_call_id reused with different arguments",
            )
        return self._decide_on(call, rec, cls)

    def _decide_on(self, call: ToolCall, rec, cls: EffectClass,
                   aliased: bool = False) -> GateDecision:
        """Decide against a record, which may be under a different id."""
        note = (f" (matched to {rec.tool_call_id} by intent hash)"
                if aliased else "")

        if rec.state in (EffectState.COMMITTED, EffectState.OBSERVED):
            return GateDecision(Verdict.SUBSTITUTE, cls,
                                observation=rec.observation,
                                reason=f"already recorded{note}" if note else None)

        if rec.state is EffectState.FAILED:
            # Re-capture: the world may have moved since the failed attempt.
            self.store.write_intent(call, cls, self.fence, self._capture(call, cls))
            return GateDecision(Verdict.EXECUTE, cls)

        if rec.state is EffectState.BLOCKED:
            return GateDecision(
                Verdict.BLOCK, cls,
                reason=(rec.error or "previously blocked; awaiting human decision")
                + note,
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
        probe = self.probes.for_call(call, self.classifier.probe_for(call))
        verdict = INCONCLUSIVE
        if probe is not None:
            try:
                verdict = probe.probe(call, rec)
            except Exception:                           # noqa: BLE001
                log.exception("probe %s raised", getattr(probe, "name", "?"))
                verdict = INCONCLUSIVE

            if verdict == LANDED:
                self.store.reconcile(call.tool_call_id, verdict, landed=True)
                return GateDecision(
                    Verdict.SUBSTITUTE, cls, observation=rec.observation,
                    reason=f"{probe.name} probe: the effect already landed",
                )
            if verdict == DID_NOT_LAND:
                self.store.reconcile(call.tool_call_id, verdict, landed=False)
                self.store.write_intent(call, cls, self.fence,
                                        self._capture(call, cls))
                return GateDecision(
                    Verdict.EXECUTE, cls,
                    reason=f"{probe.name} probe: the effect did not land",
                )
            if verdict == SAFE_TO_RETRY:
                # We cannot tell whether it landed, and we do not need to: the
                # call carries an idempotency key, so the remote collapses a
                # retry into the original effect (`docs/0020`).
                self.store.reconcile(call.tool_call_id, verdict, landed=False)
                self.store.write_intent(call, cls, self.fence,
                                        self._capture(call, cls))
                return GateDecision(
                    Verdict.EXECUTE, cls,
                    reason=(f"{probe.name} probe: outcome unknown, but the call "
                            f"is idempotency-keyed so a retry is safe"),
                )

        # No probe, or inconclusive. Fail closed.
        detail = ("no probe available" if probe is None
                  else f"{probe.name} probe inconclusive")
        reason = (f"cannot determine whether {call.tool_name} already "
                  f"executed ({detail})")
        self.store.block(call.tool_call_id, reason)
        return GateDecision(Verdict.BLOCK, cls, reason=reason)

    def _capture(self, call: ToolCall, cls: EffectClass) -> str | None:
        """Fingerprint the world before acting, so a probe can compare later.

        Only for classes that can reach the ambiguous branch -- there is no
        point paying for it on a read.
        """
        if cls.replay_safe:
            return None
        probe = self.probes.for_call(call, self.classifier.probe_for(call))
        if probe is None:
            return None
        try:
            state = probe.capture(call)
        except Exception:                               # noqa: BLE001
            log.exception("probe %s capture raised", getattr(probe, "name", "?"))
            return None
        return json.dumps(state) if state else None

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
