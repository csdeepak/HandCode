"""Core types for the effect ledger.

Spec: `docs/0012` §2. No I/O here, no dependencies beyond the stdlib — this
module is imported by everything in the kernel.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum


class EffectClass(str, Enum):
    """How a tool's side effect behaves under repetition.

    Ordering matters: `DESTRUCTIVE` is the safe default direction, so an
    unknown tool must never classify below `EXTERNAL`.
    """

    PURE_READ = "PURE_READ"
    IDEMPOTENT_WRITE = "IDEMPOTENT_WRITE"
    NON_IDEMPOTENT_WRITE = "NON_IDEMPOTENT_WRITE"
    EXTERNAL = "EXTERNAL"
    DESTRUCTIVE = "DESTRUCTIVE"

    @property
    def severity(self) -> int:
        """Rank by danger. Used to resolve competing classification rules.

        A command can match several rules (`ls && rm -rf x` matches both a
        benign prefix and a destructive one). The classifier must take the
        most dangerous match, never the first.
        """
        return _SEVERITY[self]

    @property
    def replay_safe(self) -> bool:
        """Safe to run again when we cannot tell whether it already ran."""
        return self in (EffectClass.PURE_READ, EffectClass.IDEMPOTENT_WRITE)

    @property
    def speculation_safe(self) -> bool:
        """Safe to run *before* we know we want to, then discard.

        Strictly stricter than `replay_safe` (`docs/0010` §6.4): an idempotent
        write is safe to repeat but a discarded speculative write has still
        mutated the world.
        """
        return self is EffectClass.PURE_READ


_SEVERITY: dict[EffectClass, int] = {
    EffectClass.PURE_READ: 0,
    EffectClass.IDEMPOTENT_WRITE: 1,
    EffectClass.NON_IDEMPOTENT_WRITE: 2,
    EffectClass.EXTERNAL: 3,
    EffectClass.DESTRUCTIVE: 4,
}


class EffectState(str, Enum):
    INTENT = "INTENT"        # written before execution; the ambiguous state
    COMMITTED = "COMMITTED"  # tool returned; observation stored
    OBSERVED = "OBSERVED"    # observation handed back to the harness
    FAILED = "FAILED"        # provably did not land
    BLOCKED = "BLOCKED"      # fail-closed; awaiting a human


#: Legal transitions. Anything else is a bug and raises.
TRANSITIONS: dict[EffectState | None, set[EffectState]] = {
    None: {EffectState.INTENT},
    EffectState.INTENT: {
        EffectState.COMMITTED, EffectState.FAILED,
        EffectState.BLOCKED, EffectState.INTENT,   # retry after FAILED bumps attempt
    },
    EffectState.COMMITTED: {EffectState.OBSERVED},
    EffectState.FAILED: {EffectState.INTENT},
    EffectState.BLOCKED: {
        EffectState.COMMITTED, EffectState.FAILED, EffectState.INTENT,
    },  # human resolution only
    EffectState.OBSERVED: set(),
}


class IllegalTransition(RuntimeError):
    """Raised inside the store, never past `EffectGate.guard`."""


class Verdict(str, Enum):
    EXECUTE = "EXECUTE"          # run the tool
    SUBSTITUTE = "SUBSTITUTE"    # return the stored observation (Seam C only)
    BLOCK = "BLOCK"              # refuse; fail closed
    ESCALATE = "ESCALATE"        # refuse; a human must decide


@dataclass(frozen=True)
class ToolCall:
    """One tool invocation, normalised away from any harness."""

    tool_call_id: str
    conversation_id: str
    turn_id: str
    tool_name: str
    args: dict = field(default_factory=dict)

    def intent_hash(self) -> str:
        """Stable fingerprint of *what this call would do*.

        Guards against a `tool_call_id` being reused with different arguments,
        which would otherwise let the ledger substitute the wrong observation.
        """
        canonical = json.dumps(
            {"t": self.tool_name, "a": self.args},
            sort_keys=True, separators=(",", ":"), default=str,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class EffectRecord:
    tool_call_id: str
    conversation_id: str
    turn_id: str
    tool_name: str
    intent_hash: str
    effect_class: EffectClass
    state: EffectState
    fence_token: int
    attempt: int
    started_at: float
    committed_at: float | None = None
    observation: bytes | None = None
    probe_verdict: str | None = None
    pre_state: str | None = None
    error: str | None = None
    action_event_id: str | None = None


@dataclass(frozen=True)
class GateDecision:
    verdict: Verdict
    effect_class: EffectClass | None = None
    observation: bytes | None = None
    reason: str | None = None

    @property
    def allows_execution(self) -> bool:
        return self.verdict is Verdict.EXECUTE
