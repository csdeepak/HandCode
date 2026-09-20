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

**The mailbox holds a strong reference to the action, and that is load
bearing.** `id()` is unique only among *live* objects: CPython reuses
addresses, so an entry keyed on a bare `id()` whose action had been collected
could be hit by an unrelated action allocated at the same address — returning
one call's recorded observation for a different call. Keeping the action alive
makes the address unreusable for as long as the entry exists, and the identity
re-check on read is what turns a stale entry into a miss instead of a
mismatch. Found by CI on 3.12; 3.13's allocator simply did not recycle the
address (`docs/0028`).
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
        # The action itself is kept, not just its id. See the module docstring:
        # without a live reference the address can be recycled under a
        # different action, and the entry would then be claimed by the wrong
        # call. The stored action is never read except to compare identity.
        self._by_identity: dict[int, tuple[Any, Any, bytes | None]] = {}
        self._by_fingerprint: dict[str, deque] = defaultdict(deque)
        #: Calls cleared to execute, awaiting a re-capture at Seam C. Holds the
        #: action for the same reason as `_by_identity` above.
        self._armed: dict[int, tuple[Any, Any, Any]] = {}
        self._lock = threading.Lock()

    def offer(self, action: Any, call, observation: bytes | None) -> None:
        """Seam B: this call already ran; hand Seam C the recorded result."""
        with self._lock:
            self._by_identity[id(action)] = (action, call, observation)
            self._by_fingerprint[call.intent_hash()].append((call, observation))

    def arm(self, action: Any, call, recapture: Any) -> None:
        """Seam B: this call was cleared to run; let Seam C refresh it first.

        Seam B decides for every call in an assistant message before any of
        them executes, so the fingerprint it took is the world *before the
        batch*, not the world this call will act on (`docs/0038` §3). Seam C is
        the only place that sees a call at its own execution moment.

        What is stored is a bound thunk, not the gate: Seam C still decides
        nothing, and all knowledge of the kernel stays on this side of the
        mailbox.
        """
        with self._lock:
            self._armed[id(action)] = (action, call, recapture)

    def before_execute(self, action: Any, tool_name: str, args: dict) -> bool:
        """Seam C: re-fingerprint the world for this call, if it was armed.

        Consumed on read, and matched by the same identity-then-fingerprint
        discipline as `claim` — a recycled address must read as a miss.
        Returns whether a re-capture ran, for logging and tests.
        """
        with self._lock:
            entry = self._armed.get(id(action))
            if entry is not None and entry[0] is action:
                del self._armed[id(action)]
                recapture = entry[2]
            else:
                fp = _fingerprint(tool_name, args)
                hit = next(((k, e) for k, e in self._armed.items()
                            if e[1].intent_hash() == fp), None)
                if hit is None:
                    return False
                del self._armed[hit[0]]
                recapture = hit[1][2]
        # Outside the lock: a re-capture shells out to git, and holding the
        # mailbox lock across a subprocess would serialise unrelated calls.
        recapture()
        return True

    def claim(self, action: Any, tool_name: str, args: dict) -> tuple | None:
        """Seam C: is there a substitution waiting for this action?

        Consumed on read — a substitution is honoured exactly once, so a
        genuinely repeated call is not silently short-circuited twice.
        """
        with self._lock:
            entry = self._by_identity.get(id(action))
            # `is`, not `==`: a recycled address must read as a miss, and the
            # fingerprint path below is then free to answer correctly.
            if entry is not None and entry[0] is action:
                del self._by_identity[id(action)]
                hit = (entry[1], entry[2])
                self._drop_fingerprint(hit[0])
                return hit

            fp = _fingerprint(tool_name, args)
            q = self._by_fingerprint.get(fp)
            if q:
                hit = q.popleft()
                self._drop_identity(hit[0])
                log.debug("handoff matched by fingerprint, not identity")
                return hit
        return None

    def _drop_identity(self, call) -> None:
        """Remove the identity entry for `call`, whatever action it was under.

        `id(call)` is not the key — the key is the id of the *action*. Popping
        `id(call)` removed nothing and left the identity entry behind to be
        claimed a second time.
        """
        for key, (_, c, _obs) in list(self._by_identity.items()):
            if c is call:
                del self._by_identity[key]
                return

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
