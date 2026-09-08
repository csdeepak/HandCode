"""Idempotency-key probe for EXTERNAL effects. `docs/0020`.

Git and filesystem effects are fingerprintable: we look at the world before and
after. A remote API is not — the world in question is somebody else's server,
and we cannot see it without its cooperation.

So this probe does not answer *"did it land?"*. It answers a different and
better question:

    Is it SAFE to send this again?

If the call carries a stable idempotency key, the answer is yes regardless of
what happened, because a compliant server collapses the retry into the original
effect. That is the mechanism Stripe standardised, and it is the only general
way to make a remote non-idempotent effect replay-safe.

**This probe only works because the same key goes out twice.** Seam C stamps a
key derived from the call's arguments before execution, so a crash and resume
produce the same value. A key the model supplied itself is equally good. What
the probe refuses is a request that carried *no* key, or a different one —
there the remote has nothing to deduplicate against and the retry is simply a
second effect.

What this does *not* give you: the original response. A deduped retry returns
the server's recorded response, which is usually what you want — but the agent
sees the retry's return value, not the pre-crash one.
"""
from __future__ import annotations

import json

from .base import INCONCLUSIVE, SAFE_TO_RETRY

#: Arguments a tool might already use for an idempotency key. Checked before
#: falling back to whatever the capability matrix declares.
_CONVENTIONAL_KEYS = (
    "idempotency_key", "idempotencyKey", "request_id", "requestId",
    "client_token", "clientToken", "dedupe_key", "dedupeKey",
)


class IdempotencyProbe:
    """Declares a retry safe when the call carries a stable idempotency key.

    Selection is deliberately conservative: it handles a call only when a key
    field is present or the capability matrix names one. An EXTERNAL effect
    with no key mechanism is left to fail closed, which is correct — there is
    genuinely no safe way to retry it.
    """

    name = "idempotency"

    def __init__(self, key_fields: dict[str, str] | None = None):
        #: {tool_name: argument holding the key}, from the capability matrix.
        self.key_fields = key_fields or {}

    # ── selection ──────────────────────────────────────────────────────
    def handles(self, call) -> bool:
        return self.key_field(call) is not None

    def key_field(self, call) -> str | None:
        """Which argument carries the idempotency key for this call."""
        declared = self.key_fields.get(call.tool_name)
        if declared:
            return declared
        for k in _CONVENTIONAL_KEYS:
            if k in call.args:
                return k
        return None

    def key_for(self, call) -> str:
        """The key we stamp when the call has none. Stable across a crash.

        Derived from the arguments *excluding the key field itself* — deriving
        it from arguments that contain it would be circular: stamping the key
        changes the args, which changes the key.
        """
        import hashlib
        import json as _json

        field = self.key_field(call)
        args = {k: v for k, v in call.args.items() if k != field}
        canonical = _json.dumps({"t": call.tool_name, "a": args},
                                sort_keys=True, separators=(",", ":"), default=str)
        return f"agentctl-{hashlib.sha256(canonical.encode()).hexdigest()[:32]}"

    # ── before ─────────────────────────────────────────────────────────
    def capture(self, call) -> dict | None:
        """Record the key that is actually going out with this request.

        Not the key we would choose — the one on the call. A model-supplied
        key is just as good, provided the same one is sent again.
        """
        field = self.key_field(call)
        if field is None:
            return None
        present = str(call.args.get(field) or "")
        return {
            "probe": self.name,
            "field": field,
            # Empty means no key went out, so a retry would be a second effect.
            # That happens on a Seam-B-only deployment, where nothing stamps.
            "key": present,
        }

    # ── after a crash ──────────────────────────────────────────────────
    def probe(self, call, record) -> str:
        pre = _pre(record)
        if not pre or pre.get("probe") != self.name:
            return INCONCLUSIVE

        field, sent = pre.get("field"), pre.get("key")
        if not field:
            return INCONCLUSIVE

        # No key went out, so the remote has nothing to deduplicate against
        # and a retry would be a second effect.
        if not sent:
            return INCONCLUSIVE

        # The same key must go out again. Anything else -- a regenerated key, a
        # changed argument that feeds it -- makes the retry a fresh request.
        now = str(call.args.get(field) or "") or self.key_for(call)
        if now != sent:
            return INCONCLUSIVE

        return SAFE_TO_RETRY


def _pre(record) -> dict | None:
    raw = getattr(record, "pre_state", None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:                                   # noqa: BLE001
        return None
