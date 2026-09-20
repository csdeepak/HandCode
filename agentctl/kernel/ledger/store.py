"""Durable effect ledger. Local, single-writer, fsynced.

Spec: `docs/0012` §2.1, §3.1.

The one rule that matters: **a write returns only when it is durable.**
`synchronous = FULL` is deliberate — `NORMAL` can lose the last commit on power
failure, and that is precisely the record whose absence causes a double effect.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .models import (
    TRANSITIONS,
    EffectClass,
    EffectRecord,
    EffectState,
    IllegalTransition,
    ToolCall,
)

SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


class LeaseHeld(RuntimeError):
    """Another live holder owns this conversation. Refuse to act."""


class StaleFence(RuntimeError):
    """A superseded holder tried to write. Its lease was taken over."""


class LedgerStore:
    """SQLite-backed effect ledger.

    Not thread-safe by design: one conversation, one writer, one lease.
    """

    def __init__(self, path: str | Path, holder: str = "local"):
        self.path = Path(path)
        self.holder = holder
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._fences: dict[str, int] = {}   # conversation_id -> our fence token

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "LedgerStore":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── lease / fencing ────────────────────────────────────────────────
    def acquire(
        self,
        conversation_id: str,
        ttl_s: float = 60.0,
        takeover: bool = False,
    ) -> int:
        """Take the writer lease. Returns a monotonic fence token.

        An expired lease is taken silently. A *live* one raises `LeaseHeld`,
        because two processes must never act on the same pending effect.

        `takeover=True` steals a live lease. That is safe only because every
        write is fenced (see `_assert_fence`): the superseded holder — a
        process that crashed, or hung and is about to wake up — is rejected on
        its next write rather than corrupting the ledger.

        A crashed process cannot release its own lease, so recovery needs
        either a short TTL or an explicit takeover. Keep `ttl_s` short and
        renew it while working.
        """
        now = time.time()
        row = self._db.execute(
            "SELECT holder, fence_token, expires_at FROM lease WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()

        if (row and row["expires_at"] > now and row["holder"] != self.holder
                and not takeover):
            raise LeaseHeld(
                f"conversation {conversation_id} held by {row['holder']} "
                f"for another {row['expires_at'] - now:.1f}s "
                f"(pass takeover=True to steal it; fencing makes that safe)"
            )

        token = (row["fence_token"] + 1) if row else 1
        self._db.execute(
            "INSERT INTO lease(conversation_id, holder, fence_token, expires_at) "
            "VALUES(?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET "
            "holder=excluded.holder, fence_token=excluded.fence_token, "
            "expires_at=excluded.expires_at",
            (conversation_id, self.holder, token, now + ttl_s),
        )
        self._fences[conversation_id] = token
        return token

    def renew(self, conversation_id: str, ttl_s: float = 60.0) -> None:
        """Extend our lease. Call periodically while working."""
        self._db.execute(
            "UPDATE lease SET expires_at=? WHERE conversation_id=? AND holder=?",
            (time.time() + ttl_s, conversation_id, self.holder),
        )

    def release(self, conversation_id: str) -> None:
        self._db.execute(
            "UPDATE lease SET expires_at=0 WHERE conversation_id=? AND holder=?",
            (conversation_id, self.holder),
        )

    # ── reads ──────────────────────────────────────────────────────────
    def lookup(self, tool_call_id: str) -> EffectRecord | None:
        row = self._db.execute(
            "SELECT * FROM effect_record WHERE tool_call_id=?", (tool_call_id,)
        ).fetchone()
        return _to_record(row) if row else None

    def find_by_intent(self, conversation_id: str, intent_hash: str,
                       exclude_tool_call_id: str | None = None) -> EffectRecord | None:
        """The same logical effect under a different `tool_call_id`.

        WHY THIS EXISTS (`docs/0023` §4). The ledger is keyed on
        `tool_call_id`, which the *model* mints. Ask a different model the same
        question -- as any multi-model pool will on a retry or resume -- and it
        returns a different id for the identical call. Keyed lookup misses, the
        gate sees a first sighting, and the effect repeats.

        `intent_hash` is ours: tool name plus canonicalised arguments. Same
        logical effect, same hash, whoever asked.

        Deliberately conservative. A genuine repeat of an identical call also
        matches, and is treated as the same effect -- for a non-idempotent
        effect that is the safe direction, and the probe or a human resolves it.
        """
        rows = self._db.execute(
            "SELECT * FROM effect_record WHERE conversation_id=? AND intent_hash=? "
            "ORDER BY started_at DESC", (conversation_id, intent_hash)).fetchall()
        for r in rows:
            if exclude_tool_call_id and r["tool_call_id"] == exclude_tool_call_id:
                continue
            return _to_record(r)
        return None

    def pending(self, conversation_id: str) -> list[EffectRecord]:
        """Records stuck in INTENT — the ambiguous set after a crash."""
        rows = self._db.execute(
            "SELECT * FROM effect_record WHERE conversation_id=? AND state=? "
            "ORDER BY started_at",
            (conversation_id, EffectState.INTENT.value),
        ).fetchall()
        return [_to_record(r) for r in rows]

    def committed_since(self, conversation_id: str, since: float,
                        exclude_tool_call_id: str) -> list[EffectRecord]:
        """Effects in this conversation that landed at or after `since`.

        WHY THIS EXISTS (`docs/0038` §3). A probe that reasons from world state
        — HEAD moved, therefore my commit landed — is only sound while this
        call is the sole writer. A sibling call that executed after this one
        was fingerprinted breaks that, and the probe cannot see siblings: it is
        handed one record and asked about the world.

        The gate can see them. This is the query that lets it check the
        assumption before trusting a verdict built on it.

        The comparison is against `committed_at`, not `started_at`: what
        threatens a fingerprint is a sibling whose effect *landed* after it was
        taken, not one that was merely decided earlier in the same batch. A
        sibling that committed *before* this call was fingerprinted is already
        part of the world that fingerprint describes, and is no threat at all.

        `>=` rather than `>`: two records can share a timestamp, and counting a
        simultaneous sibling as concurrent costs a human decision, while
        missing one costs a dropped effect.
        """
        rows = self._db.execute(
            "SELECT * FROM effect_record WHERE conversation_id=? AND state=? "
            "AND COALESCE(committed_at, started_at)>=? AND tool_call_id!=? "
            "ORDER BY committed_at",
            (conversation_id, EffectState.COMMITTED.value, since,
             exclude_tool_call_id),
        ).fetchall()
        return [_to_record(r) for r in rows]

    def blocked(self, conversation_id: str | None = None) -> list[EffectRecord]:
        """Effects awaiting a human decision (`docs/0013` §3, Panel 3)."""
        if conversation_id:
            rows = self._db.execute(
                "SELECT * FROM effect_record WHERE state=? AND conversation_id=?",
                (EffectState.BLOCKED.value, conversation_id),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM effect_record WHERE state=?",
                (EffectState.BLOCKED.value,),
            ).fetchall()
        return [_to_record(r) for r in rows]

    # ── the write-ahead protocol ───────────────────────────────────────
    def _assert_fence(self, conversation_id: str, record_fence: int | None) -> None:
        """Reject a write from a superseded holder.

        This is what makes lease takeover safe: a zombie process that wakes up
        after its lease was stolen holds an older token and is refused here.
        """
        ours = self._fences.get(conversation_id)
        if ours is None or record_fence is None:
            return                       # no lease taken; single-process use
        if record_fence > ours:
            raise StaleFence(
                f"fence {ours} superseded by {record_fence} for {conversation_id}"
            )

    def write_intent(
        self, call: ToolCall, cls: EffectClass, fence: int,
        pre_state: str | None = None,
    ) -> EffectRecord:
        """Record intent *before* the tool runs. Durable on return."""
        prev = self.lookup(call.tool_call_id)
        if prev is not None:
            self._assert_fence(call.conversation_id, prev.fence_token)
        _check(prev.state if prev else None, EffectState.INTENT)
        attempt = (prev.attempt + 1) if prev else 1
        now = time.time()

        self._db.execute(
            "INSERT INTO effect_record(tool_call_id, conversation_id, turn_id, "
            "action_event_id, tool_name, intent_hash, effect_class, state, "
            "fence_token, attempt, started_at, pre_state) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(tool_call_id) DO UPDATE SET state=excluded.state, "
            "attempt=excluded.attempt, started_at=excluded.started_at, "
            "fence_token=excluded.fence_token, error=NULL, "
            "pre_state=COALESCE(excluded.pre_state, effect_record.pre_state)",
            (call.tool_call_id, call.conversation_id, call.turn_id, None,
             call.tool_name, call.intent_hash(), cls.value,
             EffectState.INTENT.value, fence, attempt, now, pre_state),
        )
        rec = self.lookup(call.tool_call_id)
        assert rec is not None
        return rec

    def refresh_pre_state(self, tool_call_id: str, pre_state: str | None) -> None:
        """Re-fingerprint the world immediately before this call executes.

        WHY THIS EXISTS (`docs/0038` §3). The gate decides at Seam B, which the
        harness runs for *every* call in an assistant message before it
        executes *any* of them. So a batch of calls all carry a fingerprint of
        the world as it was before the first one ran — and the git probe's
        LANDED rule ("HEAD moved, and there is a single writer, so it was our
        commit") is then wrong about every call but the first.

        Seam C is the only place that sees a call at its own execution moment.
        Refreshing here makes each fingerprint describe the world that call
        actually acts on.

        Deliberately narrow: `pre_state` and `started_at` only. The state
        machine is untouched and `attempt` is not incremented, because this is
        not a new attempt — it is the same attempt, finally about to run.
        A record that has left INTENT is not refreshed: it has already
        executed, and its fingerprint is evidence rather than a prediction.
        """
        if pre_state is None:
            return
        self._db.execute(
            "UPDATE effect_record SET pre_state=?, started_at=? "
            "WHERE tool_call_id=? AND state=?",
            (pre_state, time.time(), tool_call_id, EffectState.INTENT.value),
        )

    def commit(self, tool_call_id: str, observation: bytes | None = None) -> None:
        """The effect landed. Durable on return."""
        self._transition(
            tool_call_id, EffectState.COMMITTED,
            extra={"committed_at": time.time(), "observation": observation},
        )

    def fail(self, tool_call_id: str, error: str) -> None:
        """The effect provably did not land."""
        self._transition(tool_call_id, EffectState.FAILED, extra={"error": error[:2000]})

    def block(self, tool_call_id: str, reason: str) -> None:
        """Fail closed. A human must resolve this."""
        self._transition(tool_call_id, EffectState.BLOCKED, extra={"error": reason[:2000]})

    def observed(self, tool_call_id: str) -> None:
        self._transition(tool_call_id, EffectState.OBSERVED)

    def reconcile(self, tool_call_id: str, verdict: str, landed: bool) -> None:
        """Resolve an ambiguous INTENT using out-of-band evidence."""
        target = EffectState.COMMITTED if landed else EffectState.FAILED
        self._transition(tool_call_id, target, extra={
            "probe_verdict": verdict,
            **({"committed_at": time.time()} if landed else {}),
        })

    # ── internals ──────────────────────────────────────────────────────
    def _transition(self, tool_call_id: str, target: EffectState, extra: dict | None = None) -> None:
        rec = self.lookup(tool_call_id)
        if rec is None:
            raise IllegalTransition(f"no record for {tool_call_id}")
        self._assert_fence(rec.conversation_id, rec.fence_token)
        _check(rec.state, target)

        cols, vals = ["state=?"], [target.value]
        for k, v in (extra or {}).items():
            cols.append(f"{k}=?")
            vals.append(v)
        vals.append(tool_call_id)
        self._db.execute(
            f"UPDATE effect_record SET {', '.join(cols)} WHERE tool_call_id=?", vals
        )


def _check(current: EffectState | None, target: EffectState) -> None:
    allowed = TRANSITIONS.get(current, set())
    if target not in allowed:
        raise IllegalTransition(
            f"{current.value if current else 'None'} -> {target.value} is not legal"
        )


def _to_record(row: sqlite3.Row) -> EffectRecord:
    return EffectRecord(
        tool_call_id=row["tool_call_id"],
        conversation_id=row["conversation_id"],
        turn_id=row["turn_id"],
        tool_name=row["tool_name"],
        intent_hash=row["intent_hash"],
        effect_class=EffectClass(row["effect_class"]),
        state=EffectState(row["state"]),
        fence_token=row["fence_token"],
        attempt=row["attempt"],
        started_at=row["started_at"],
        committed_at=row["committed_at"],
        observation=row["observation"],
        probe_verdict=row["probe_verdict"],
        pre_state=row["pre_state"],
        error=row["error"],
        action_event_id=row["action_event_id"],
    )
