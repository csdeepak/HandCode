"""Seam C binding for OpenHands — the substitution channel.

Spec: `docs/0008` §3.5, `docs/0012` §4, corrected by `docs/0014` C1.

Binds by replacing the `executor` field on a resolved `ToolDefinition`. No
subclassing of `ToolExecutor` to re-register, no fork:

    gated = tool.model_copy(update={"executor": GatedExecutor(...)})

What it adds over Seam B alone:

1. **Substitution** — when an effect already landed, the agent receives the
   recorded observation instead of a rejection, so the loop continues as though
   the crash never happened.
2. **Idempotency-key injection** — Seam C is the only place that can modify a
   call before it executes, and injecting a stable key is the only general way
   to make a remote effect replay-safe (`docs/0020`).

The second is a deliberate widening of Seam C's role, and it stays narrow: the
key is *computed by the kernel* and merely written onto the call here. Seam C
still decides nothing.

It remains thin — a lookup, a branch, an optional field write, and the inner
call. All policy lives in the gate; all decisions are made at Seam B
(`handoff.py`). Keeping this small is the whole portability argument in
`docs/0008` §12.
"""
from __future__ import annotations

import logging
from typing import Any

from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool

from .handoff import SubstitutionHandoff

log = logging.getLogger("agentctl.seam_c")


class GatedExecutor(ToolExecutor):
    """Wraps a real executor. Substitutes when Seam B says the effect landed."""

    def __init__(self, inner: ToolExecutor, handoff: SubstitutionHandoff,
                 observation_type: type | None = None, tool_name: str = "",
                 idempotency: Any = None):
        self._inner = inner
        self._handoff = handoff
        self._observation_type = observation_type
        self._tool_name = tool_name
        #: An `IdempotencyProbe`, when this tool declares a key field.
        self._idempotency = idempotency

    def __call__(self, action, conversation=None):
        claim = self._handoff.claim(action, self._tool_name, _args(action))
        if claim is not None:
            _call, raw = claim
            if (obs := self._revive(raw)) is not None:
                log.info("substituted recorded observation for %s", self._tool_name)
                return obs
            if (obs := self._synthesize()) is not None:
                log.info("synthesized a recovery observation for %s", self._tool_name)
                return obs
            # It landed, we cannot describe it, and re-running would duplicate
            # the effect. Raising is the safe end: the harness surfaces an
            # error, and the ledger already says COMMITTED.
            raise RuntimeError(
                f"{self._tool_name} already executed, but its result could not "
                f"be recovered or described. It was NOT re-run."
            )

        # No claim means Seam B said EXECUTE. Seam C never decides.
        #
        # It does, however, re-fingerprint: Seam B decided for the whole batch,
        # and this is the only point at which a call is seen at its own
        # execution moment (`docs/0038` §3). Still no decision -- the kernel
        # captures, this only says when.
        self._handoff.before_execute(action, self._tool_name, _args(action))
        return self._inner(self._stamp_idempotency_key(action), conversation)

    def _stamp_idempotency_key(self, action):
        """Write the kernel's stable key onto the call before it goes out.

        Without this the IdempotencyProbe declines and the effect fails closed,
        so the injection is not an optimisation -- it IS the mechanism
        (`docs/0020`).
        """
        if self._idempotency is None:
            return action
        try:
            from agentctl.kernel.ledger.models import ToolCall
            call = ToolCall("stamp", "", "", self._tool_name, _args(action))
            field = self._idempotency.key_field(call)
            if field is None:
                return action
            existing = getattr(action, field, None)
            if existing:
                # The caller already supplied a key. It is stable across a
                # resume for the same reason ours is, so leave it alone.
                return action
            return action.model_copy(
                update={field: self._idempotency.key_for(call)})
        except Exception:                               # noqa: BLE001
            # A failed stamp means the probe declines and the effect fails
            # closed. Safe, but say so loudly: it silently costs protection.
            log.exception("could not stamp an idempotency key on %s",
                          self._tool_name)
            return action

    def _revive(self, raw: bytes | None):
        """Rebuild the observation actually recorded at commit time."""
        if not raw or self._observation_type is None:
            return None
        try:
            return self._observation_type.model_validate_json(raw)
        except Exception:                               # noqa: BLE001
            log.exception("could not revive observation for %s", self._tool_name)
            return None

    def _synthesize(self):
        """Describe a recovered effect when no observation was ever recorded.

        A probe-reconciled effect has this shape: the crash happened *before*
        the observation was written, so the ledger knows the effect landed but
        holds no result. There is nothing to revive.

        The agent still needs something truthful to continue on, so say plainly
        what is known — it ran, its output is unavailable — rather than
        inventing a plausible result or re-running the tool.
        """
        if self._observation_type is None:
            return None
        note = (
            f"[agentctl] {self._tool_name} already completed before an "
            f"interruption. The effect is confirmed; its original output was "
            f"not recorded and is unavailable. It was not run again."
        )
        try:
            obs = self._observation_type()          # defaults only
        except Exception:                           # noqa: BLE001
            return None                             # required fields: cannot describe
        try:
            # Observation.content is list[TextContent | ImageContent], not a
            # string. Assigning a bare str validates here and then explodes
            # later when the message is assembled.
            from openhands.sdk.llm import TextContent
            return obs.model_copy(update={"content": [TextContent(text=note)]})
        except Exception:                           # noqa: BLE001
            log.exception("could not attach a recovery note to %s", self._tool_name)
            return obs

    # Delegate lifecycle so the wrapper is transparent.
    def close(self) -> None:
        getattr(self._inner, "close", lambda: None)()

    def interrupt(self) -> None:
        getattr(self._inner, "interrupt", lambda: None)()


def gate_tools(tools, handoff: SubstitutionHandoff, idempotency: Any = None):
    """Replace each tool's executor with a gated one. `docs/0014` C1."""
    out = []
    for t in tools:
        if t.executor is None:
            out.append(t)
            continue
        out.append(t.model_copy(update={"executor": GatedExecutor(
            t.executor, handoff, t.observation_type, t.name, idempotency)}))
    return out


def gate_tool_class(inner_cls: type[ToolDefinition], handoff: SubstitutionHandoff,
                    idempotency: Any = None):
    """Build a subclass whose `create()` returns gated tools."""

    class Gated(inner_cls):                             # type: ignore[misc,valid-type]
        @classmethod
        def create(cls, conv_state=None, **params):
            return gate_tools(
                inner_cls.create(conv_state=conv_state, **params),
                handoff, idempotency)

    Gated.__name__ = f"Gated{inner_cls.__name__}"
    Gated.__qualname__ = Gated.__name__
    return Gated


def install(handoff: SubstitutionHandoff, tools: dict[str, type],
            idempotency: Any = None) -> list[str]:
    """Re-register each named tool with a gated executor.

    Call before constructing the Agent. Returns the names that were gated.
    """
    gated = []
    for name, cls in tools.items():
        try:
            register_tool(name, gate_tool_class(cls, handoff, idempotency))
            gated.append(name)
        except Exception:                               # noqa: BLE001
            log.exception("could not gate tool %s", name)
    return gated


def _args(action: Any) -> dict:
    try:
        d = action.model_dump()
    except Exception:                                   # noqa: BLE001
        d = {k: v for k, v in vars(action).items() if not k.startswith("_")}
    d.pop("kind", None)
    return d
