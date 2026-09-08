"""Seam A — the LiteLLM request hook. Spec: `docs/0012` §3.4.

Runs inside the LiteLLM proxy, before the request reaches a provider. It is
the only seam that is harness-independent: anything speaking the
OpenAI-compatible format — OpenHands, Claude Code, Aider, Cline — passes
through it (`docs/0013` §5).

What it does:

1. **Turn-atomic routing** — an endpoint may change between turns and never
   within one. A message list ending in unresolved tool calls is pinned to the
   deployment that opened the turn (`docs/0010` §7.3). Model families mint
   `tool_call_id` differently, and the effect ledger is keyed on it, so a
   mid-turn switch could make a committed effect invisible.
2. **Attribution** — stamps a turn-scoped trace id. The SDK already sends a
   conversation-scoped `x-litellm-session-id` (`docs/0015` §5); this adds the
   turn.
3. **Telemetry** — records cost, tokens, cache hits and the chosen deployment.

Two things it deliberately does *not* do: decide anything about effects (that
is the gate's job at Seams B and C), and depend on the control plane being
reachable. It reads local state only.

**This module holds only the logic.** The LiteLLM binding lives in
`agentctl.adapters.litellm.hook` — the kernel must not import a data plane any
more than it imports a harness (`docs/0008` R6), and `tests/test_boundaries.py`
enforces that. `docs/0012` §1 originally placed the whole hook here; the split
is recorded in `docs/0021` §7.

**Seam A is best-effort and must be verified live.** LiteLLM has an open bug
where `async_pre_call_hook` is bypassed on the Anthropic `/v1/messages`
endpoint (#27518) and never fires for `/mcp/` tool calls (#25011) — silently,
in both cases. `docs/0021` asserts it actually fires rather than assuming.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("agentctl.hook")


def ends_with_unresolved_tool_calls(messages: list[dict] | None) -> bool:
    """Is the conversation mid-turn — awaiting tool results?

    True when the last assistant message asked for tools and no matching tool
    results follow it. Switching endpoints here is the hazard in `docs/0010`
    §7.3.
    """
    if not messages:
        return False

    pending: set[str] = set()
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "assistant":
            calls = m.get("tool_calls") or []
            # A fresh assistant turn supersedes anything left dangling.
            pending = {c.get("id") for c in calls if isinstance(c, dict) and c.get("id")}
        elif role == "tool":
            pending.discard(m.get("tool_call_id"))
        elif role == "user":
            # A user message means the turn was abandoned, not continued.
            pending.clear()
    return bool(pending)


def turn_signature(messages: list[dict] | None) -> str | None:
    """Identify the turn: the id of its first outstanding tool call."""
    if not messages:
        return None
    for m in reversed(messages):
        if isinstance(m, dict) and m.get("role") == "assistant":
            calls = m.get("tool_calls") or []
            ids = sorted(c.get("id") for c in calls
                         if isinstance(c, dict) and c.get("id"))
            return ids[0] if ids else None
    return None


class TurnAffinity:
    """Remembers which deployment opened each turn. Local, in-memory.

    Deliberately not shared state: `docs/0008` R2 says the hot path must not
    depend on anything that can be unreachable. Losing this map costs a pinning
    opportunity, never correctness.
    """

    def __init__(self, ttl_s: float = 900.0):
        self._pins: dict[str, tuple[str, float]] = {}
        self.ttl_s = ttl_s

    def remember(self, turn: str | None, deployment: str | None) -> None:
        if turn and deployment:
            self._pins[turn] = (deployment, time.time())

    def pinned(self, turn: str | None) -> str | None:
        if not turn:
            return None
        hit = self._pins.get(turn)
        if not hit:
            return None
        deployment, at = hit
        if time.time() - at > self.ttl_s:
            self._pins.pop(turn, None)
            return None
        return deployment

    def __len__(self) -> int:
        return len(self._pins)


class RequestHook:
    """Seam A. Subclasses LiteLLM's CustomLogger when it is importable.

    Written so the logic is testable without the proxy: every method takes
    plain dicts.
    """

    def __init__(self, telemetry_path: str | Path | None = None,
                 affinity: TurnAffinity | None = None):
        self.affinity = affinity or TurnAffinity()
        self.telemetry_path = Path(telemetry_path) if telemetry_path else None
        self.calls: list[dict] = []          # live-fire evidence for M1
        self.records: list[dict] = []

    # ── pre-call ───────────────────────────────────────────────────────
    def apply(self, data: dict) -> dict:
        """Mutate an outbound request. The testable core of the hook."""
        messages = data.get("messages") or []
        meta = data.setdefault("metadata", {})

        turn = turn_signature(messages)
        mid_turn = ends_with_unresolved_tool_calls(messages)

        if mid_turn:
            # THE RULE: the turn is the atomic unit of routing.
            if (pin := self.affinity.pinned(turn)):
                data["model"] = pin
                meta["agentctl_pinned"] = pin
            meta["agentctl_mid_turn"] = True
        else:
            self.affinity.remember(turn, data.get("model"))
            meta["agentctl_mid_turn"] = False

        conv = (meta.get("conversation_id")
                or (data.get("extra_headers") or {}).get("x-litellm-session-id")
                or "unknown")
        meta["agentctl_trace_id"] = f"{conv}:{turn or 'turn0'}"

        self.calls.append({
            "model": data.get("model"),
            "n_messages": len(messages),
            "mid_turn": mid_turn,
            "turn": turn,
            "trace_id": meta["agentctl_trace_id"],
            "ts": time.time(),
        })
        self._flush()
        return data

    # ── post-call ──────────────────────────────────────────────────────
    def record(self, kwargs: dict, response: Any,
               start: float | None = None, end: float | None = None) -> dict:
        """Extract the telemetry the cost ledger will need (M5)."""
        usage = _get(response, "usage") or {}
        details = _get(usage, "prompt_tokens_details") or {}
        # WHERE THE METADATA ACTUALLY IS (docs/0021 §4). Anything the
        # pre-call hook writes into data["metadata"] arrives on the logging
        # callback under litellm_params.metadata, NOT kwargs["metadata"],
        # which is empty. Reading only the obvious place yields trace_id=None
        # and silently breaks cost attribution.
        meta = kwargs.get("metadata") or {}
        nested = (kwargs.get("litellm_params") or {}).get("metadata") or {}
        trace = (meta.get("agentctl_trace_id")
                 or nested.get("agentctl_trace_id")
                 or (nested.get("requester_metadata") or {}).get("agentctl_trace_id"))
        rec = {
            "model": kwargs.get("model"),
            "deployment": ((kwargs.get("litellm_params") or {})
                           .get("model_info") or {}).get("id"),
            "trace_id": trace,
            "prompt_tokens": _get(usage, "prompt_tokens"),
            "completion_tokens": _get(usage, "completion_tokens"),
            "cached_tokens": _get(details, "cached_tokens"),
            "cost": kwargs.get("response_cost"),
            "latency_s": (end - start) if (start and end) else None,
            "ts": time.time(),
        }
        self.records.append(rec)
        self._flush()
        return rec

    def _flush(self) -> None:
        """Evidence on disk, so a subprocess proxy can be inspected."""
        if self.telemetry_path is None:
            return
        try:
            self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
            self.telemetry_path.write_text(
                json.dumps({"calls": self.calls, "records": self.records},
                           indent=2, default=str), encoding="utf-8")
        except Exception:                               # noqa: BLE001
            log.exception("could not write hook telemetry")


def _get(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)
