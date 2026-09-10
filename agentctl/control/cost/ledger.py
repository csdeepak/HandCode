"""Cost ledger — spend attributed to logical work. `docs/0008` §8, M5.

Control plane, so it may fail: nothing here is on the request path. It consumes
Seam A telemetry after the fact.

**Pricing coverage is a first-class column, not a nicety.** `docs/0021` §5 found
that LiteLLM reports `response_cost: 0.0` for an endpoint it cannot price —
not `None`, *zero*. So an unpriced call and a genuinely free one are
indistinguishable in the raw data, and any budget built on it silently
under-counts exactly where a free-tier pool lives.

The ledger therefore records `priced` separately from `cost_usd`, and every
total is reported alongside the share of calls it actually covers. "I spent
$0.00" and "I do not know what I spent" must never render the same.
"""
from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS usage_record (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id          TEXT,
    conversation_id   TEXT,
    turn_id           TEXT,
    model             TEXT,
    deployment        TEXT,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    cached_tokens     INTEGER,
    cost_usd          REAL,
    -- The Q18 column. 0 means litellm could not price this call, so cost_usd
    -- is meaningless rather than zero. docs/0021 §5.
    priced            INTEGER NOT NULL DEFAULT 0,
    latency_s         REAL,
    ts                REAL NOT NULL,
    UNIQUE(trace_id, ts)
);

CREATE INDEX IF NOT EXISTS ix_usage_conv ON usage_record(conversation_id);
CREATE INDEX IF NOT EXISTS ix_usage_ts   ON usage_record(ts);
CREATE INDEX IF NOT EXISTS ix_usage_dep  ON usage_record(deployment);
"""


@dataclass(frozen=True)
class Totals:
    calls: int = 0
    priced_calls: int = 0
    cost_usd: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0

    @property
    def coverage(self) -> float:
        """Share of calls litellm could actually price. 1.0 means trustworthy."""
        return (self.priced_calls / self.calls) if self.calls else 0.0

    @property
    def trustworthy(self) -> bool:
        return self.calls > 0 and self.priced_calls == self.calls

    @property
    def cache_hit_ratio(self) -> float:
        return (self.cached_tokens / self.prompt_tokens) if self.prompt_tokens else 0.0

    def describe_cost(self) -> str:
        """Never render an unpriced total as though it were a real zero."""
        if self.calls == 0:
            return "no calls"
        if self.priced_calls == 0:
            return f"unknown (0/{self.calls} calls priced)"
        if not self.trustworthy:
            return (f"${self.cost_usd:.4f} + unknown "
                    f"({self.priced_calls}/{self.calls} priced)")
        return f"${self.cost_usd:.4f}"


class CostLedger:
    """Ingests Seam A telemetry and answers what work cost."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "CostLedger":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── ingest ─────────────────────────────────────────────────────────
    def ingest_record(self, rec: dict) -> bool:
        """Store one Seam A telemetry record. Idempotent on (trace_id, ts)."""
        trace = rec.get("trace_id") or ""
        conv, _, turn = trace.partition(":")
        cost = rec.get("cost")
        # THE Q18 DISTINCTION: a falsy cost means litellm could not price it.
        # Storing 0.0 as though it were a measured zero is the whole hazard.
        priced = 1 if cost else 0
        try:
            self._db.execute(
                "INSERT OR IGNORE INTO usage_record(trace_id, conversation_id, "
                "turn_id, model, deployment, prompt_tokens, completion_tokens, "
                "cached_tokens, cost_usd, priced, latency_s, ts) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (trace or None, conv or None, turn or None,
                 rec.get("model"), rec.get("deployment"),
                 rec.get("prompt_tokens") or 0, rec.get("completion_tokens") or 0,
                 rec.get("cached_tokens") or 0,
                 float(cost) if priced else 0.0, priced,
                 rec.get("latency_s"), rec.get("ts") or time.time()))
            return True
        except sqlite3.Error:
            return False

    def ingest_telemetry(self, path: str | Path) -> int:
        """Load a Seam A telemetry file. Returns the number of records stored."""
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:                               # noqa: BLE001
            return 0
        return sum(1 for r in data.get("records", []) if self.ingest_record(r))

    # ── queries ────────────────────────────────────────────────────────
    def totals(self, conversation_id: str | None = None,
               since: float | None = None) -> Totals:
        where, args = [], []
        if conversation_id:
            where.append("conversation_id=?")
            args.append(conversation_id)
        if since is not None:
            where.append("ts>=?")
            args.append(since)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        row = self._db.execute(
            "SELECT COUNT(*) calls, COALESCE(SUM(priced),0) priced_calls, "
            "COALESCE(SUM(cost_usd),0) cost, "
            "COALESCE(SUM(prompt_tokens),0) pt, "
            "COALESCE(SUM(completion_tokens),0) ct, "
            "COALESCE(SUM(cached_tokens),0) cached "
            f"FROM usage_record {clause}", args).fetchone()
        return Totals(row["calls"], row["priced_calls"], row["cost"],
                      row["pt"], row["ct"], row["cached"])

    def by_conversation(self, limit: int = 20) -> list[dict]:
        rows = self._db.execute(
            "SELECT conversation_id, COUNT(*) calls, SUM(priced) priced_calls, "
            "SUM(cost_usd) cost, SUM(prompt_tokens) pt, MAX(ts) last_ts "
            "FROM usage_record WHERE conversation_id IS NOT NULL "
            "GROUP BY conversation_id ORDER BY last_ts DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

    def by_deployment(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT deployment, COUNT(*) calls, SUM(priced) priced_calls, "
            "SUM(cost_usd) cost, SUM(cached_tokens) cached, SUM(prompt_tokens) pt "
            "FROM usage_record WHERE deployment IS NOT NULL "
            "GROUP BY deployment ORDER BY calls DESC").fetchall()
        return [dict(r) for r in rows]

    def unpriced_deployments(self) -> list[str]:
        """Endpoints whose spend is invisible. The budget guard's blind spot."""
        rows = self._db.execute(
            "SELECT deployment FROM usage_record WHERE deployment IS NOT NULL "
            "GROUP BY deployment HAVING SUM(priced)=0").fetchall()
        return [r["deployment"] for r in rows]

    def cost_per_task(self, conversation_id: str) -> Totals:
        """The metric that matters: what one completed task cost."""
        return self.totals(conversation_id=conversation_id)
