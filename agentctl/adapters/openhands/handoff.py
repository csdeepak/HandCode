"""Carries a SUBSTITUTE decision from Seam B to Seam C.

Why this exists: `ToolExecutor.__call__(action, conversation)` receives the
*action*, and `Action` carries no identity — `tool_call_id` lives only on the
`ActionEvent`, which Seam B sees and Seam C does not. So the seam that can
*identify* a call is not the seam that can *substitute* for it.

**Seam C is not a second gate.** Seam B makes every decision. Seam C exists
only to honour the one verdict Seam B cannot: returning a stored observation
instead of executing. A lookup miss therefore means "Seam B said EXECUTE", and
passing through is correct — Seam B would already have blocked anything
dangerous.

Matching is by object identity first (the harness passes the same `action`
instance the event carried), falling back to a content fingerprint so a
mismatch degrades to a missed substitution rather than a wrong one.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict, deque
from typing import Any

log = logging.getLogger("agentctl.handoff")


class SubstitutionHandoff:
    """A one-shot mailbox per action, written by Seam B and read by Seam C."""

    def __init__(self) -> None:
        self._by_identity: dict[int, tuple[Any, bytes | None]] = {}
        self._by_fingerprint: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def offer(self, action: Any, call, observation: bytes | None) -> None:
        """Seam B: this call already ran; hand Seam C the recorded result."""
        with self._lock:
            self._by_identity[id(action)] = (call, observation)
            self._by_fingerprint[call.intent_hash()].append((call, observation))

    def claim(self, action: Any, tool_name: str, args: dict) -> tuple | None:
        """Seam C: is there a substitution waiting for this action?

        Consumed on read — a substitution is honoured exactly once, so a
        genuinely repeated call is not silently short-circuited twice.
        """
        with self._lock:
            hit = self._by_identity.pop(id(action), None)
            if hit is not None:
                self._drop_fingerprint(hit[0])
                return hit

            fp = _fingerprint(tool_name, args)
            q = self._by_fingerprint.get(fp)
            if q:
                hit = q.popleft()
                self._by_identity.pop(id(hit[0]), None)
                log.debug("handoff matched by fingerprint, not identity")
                return hit
        return None

    def pending(self) -> int:
        with self._lock:
            return len(self._by_identity)

    def _drop_fingerprint(self, call) -> None:
        q = self._by_fingerprint.get(call.intent_hash())
        if not q:
            return
        for i, (c, _) in enumerate(q):
            if c is call:
                del q[i]
                return


def _fingerprint(tool_name: str, args: dict) -> str:
    import hashlib
    import json
    canonical = json.dumps({"t": tool_name, "a": args}, sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()
