"""Cost ledger. docs/0008 §8, M5.

The point of these tests is the Q18 distinction: litellm reports 0.0 for an
endpoint it cannot price, so "I spent nothing" and "I do not know what I
spent" arrive as identical data. Conflating them silently under-counts exactly
where a free-tier pool lives.
"""
import json

import pytest

from agentctl.control.cost import CostLedger, Totals


def rec(trace="conv_1:turn_a", deployment="acct-a", cost=0.0042, **kw):
    base = {"trace_id": trace, "model": "gpt", "deployment": deployment,
            "prompt_tokens": 1000, "completion_tokens": 200,
            "cached_tokens": 800, "cost": cost, "latency_s": 1.0, "ts": 1000.0}
    base.update(kw)
    return base


@pytest.fixture
def ledger(tmp_path):
    with CostLedger(tmp_path / "cost.db") as c:
        yield c


# ══ THE Q18 DISTINCTION ═══════════════════════════════════════════════
def test_an_unpriced_call_is_not_recorded_as_free(ledger):
    ledger.ingest_record(rec(cost=0.0, deployment="free-tier"))
    t = ledger.totals()
    assert t.calls == 1
    assert t.priced_calls == 0
    assert not t.trustworthy
    assert "unknown" in t.describe_cost()


def test_a_priced_call_reports_a_real_number(ledger):
    ledger.ingest_record(rec(cost=0.0042))
    t = ledger.totals()
    assert t.trustworthy
    assert t.describe_cost() == "$0.0042"


def test_a_mixed_total_says_so_rather_than_understating(ledger):
    """The dangerous case: a real number that is quietly incomplete."""
    ledger.ingest_record(rec(trace="c:1", cost=0.0042))
    ledger.ingest_record(rec(trace="c:2", cost=0.0, deployment="free-tier"))
    t = ledger.totals()
    assert t.coverage == 0.5
    desc = t.describe_cost()
    assert "$0.0042" in desc and "unknown" in desc, (
        "a partial total must never render as though it were complete")


def test_unpriced_deployments_are_nameable(ledger):
    ledger.ingest_record(rec(trace="c:1", deployment="acct-a", cost=0.01))
    ledger.ingest_record(rec(trace="c:2", deployment="free-tier", cost=0.0))
    ledger.ingest_record(rec(trace="c:3", deployment="free-tier", cost=0.0))
    assert ledger.unpriced_deployments() == ["free-tier"]


def test_no_calls_is_not_zero_spend(ledger):
    assert ledger.totals().describe_cost() == "no calls"


# ══ attribution ═══════════════════════════════════════════════════════
def test_trace_id_splits_into_conversation_and_turn(ledger):
    ledger.ingest_record(rec(trace="conv_abc:turn_7"))
    row = ledger._db.execute("SELECT * FROM usage_record").fetchone()
    assert row["conversation_id"] == "conv_abc"
    assert row["turn_id"] == "turn_7"


def test_cost_per_task_is_scoped_to_one_conversation(ledger):
    ledger.ingest_record(rec(trace="conv_1:a", cost=0.01))
    ledger.ingest_record(rec(trace="conv_1:b", cost=0.02))
    ledger.ingest_record(rec(trace="conv_2:a", cost=0.99))
    t = ledger.cost_per_task("conv_1")
    assert t.calls == 2
    assert round(t.cost_usd, 4) == 0.03


def test_totals_can_be_windowed_by_time(ledger):
    ledger.ingest_record(rec(trace="c:old", ts=1000.0))
    ledger.ingest_record(rec(trace="c:new", ts=5000.0))
    assert ledger.totals(since=4000.0).calls == 1


def test_by_deployment_separates_priced_from_unpriced(ledger):
    ledger.ingest_record(rec(trace="c:1", deployment="acct-a", cost=0.01))
    ledger.ingest_record(rec(trace="c:2", deployment="free", cost=0.0))
    rows = {r["deployment"]: r for r in ledger.by_deployment()}
    assert rows["acct-a"]["priced_calls"] == 1
    assert rows["free"]["priced_calls"] == 0


# ══ ingest ════════════════════════════════════════════════════════════
def test_ingest_is_idempotent(ledger):
    """Re-ingesting the same telemetry must not double-count spend."""
    ledger.ingest_record(rec())
    ledger.ingest_record(rec())
    assert ledger.totals().calls == 1


def test_ingest_reads_a_seam_a_telemetry_file(tmp_path):
    p = tmp_path / "tel.json"
    p.write_text(json.dumps({"records": [rec(trace="c:1"), rec(trace="c:2")]}),
                 encoding="utf-8")
    with CostLedger(tmp_path / "cost.db") as c:
        assert c.ingest_telemetry(p) == 2
        assert c.totals().calls == 2


def test_a_missing_telemetry_file_is_survivable(tmp_path):
    with CostLedger(tmp_path / "cost.db") as c:
        assert c.ingest_telemetry(tmp_path / "nope.json") == 0


def test_cache_hit_ratio(ledger):
    ledger.ingest_record(rec(prompt_tokens=1000, cached_tokens=750))
    assert ledger.totals().cache_hit_ratio == 0.75


def test_totals_of_an_empty_ledger_are_safe():
    t = Totals()
    assert t.coverage == 0.0 and t.cache_hit_ratio == 0.0
    assert not t.trustworthy


# ══ the third state: free per the proxy config (docs/0042 I-10) ═══════
def test_a_free_pool_costs_a_known_zero(ledger):
    """Live 2026-10-03: `cost --conversation` said `$0.0141 + unknown
    (12/18 priced)` for a pool of free deployments, while the run's own
    report said $0.00. List prices on free calls, and OpenRouter `:free`
    calls as unknown -- wrong in both directions."""
    for i, c in enumerate((0.0021, 0.0, 0.0034)):
        ledger.ingest_record(rec(ts=1000.0 + i, cost=c, free=True))
    t = ledger.totals()
    assert t.trustworthy and t.cost_usd == 0.0 and t.free_calls == 3
    assert t.describe_cost().startswith("$0.0000") and "per proxy config" in t.describe_cost()


def test_a_list_price_on_a_free_call_is_not_spend(ledger):
    ledger.ingest_record(rec(cost=0.25, free=True))
    ledger.ingest_record(rec(ts=1001.0, cost=0.01))           # a paid call
    t = ledger.totals()
    assert t.cost_usd == pytest.approx(0.01) and t.trustworthy


def test_free_and_unknown_are_still_distinct(ledger):
    ledger.ingest_record(rec(cost=0.0, free=True))
    ledger.ingest_record(rec(ts=1001.0, cost=0.0))            # not free, unpriced
    t = ledger.totals()
    assert not t.trustworthy and t.known_calls == 1
    assert "unknown" in t.describe_cost()


def test_only_an_explicit_true_counts_as_free(ledger):
    """A config claim, read literally. "yes", 1 or a missing key is not it."""
    for i, v in enumerate(("yes", 1, None)):
        ledger.ingest_record(rec(ts=1000.0 + i, cost=0.0, free=v))
    assert ledger.totals().free_calls == 0


def test_a_free_deployment_is_not_listed_as_unpriced(ledger):
    ledger.ingest_record(rec(deployment="gemini-a1-m0", cost=0.0, free=True))
    ledger.ingest_record(rec(ts=1001.0, deployment="mystery", cost=0.0))
    assert ledger.unpriced_deployments() == ["mystery"]


def test_a_ledger_from_before_the_free_column_is_migrated(tmp_path):
    import sqlite3
    p = tmp_path / "old.db"
    db = sqlite3.connect(p)
    db.execute("CREATE TABLE usage_record (id INTEGER PRIMARY KEY, trace_id TEXT, "
               "conversation_id TEXT, turn_id TEXT, model TEXT, deployment TEXT, "
               "prompt_tokens INTEGER, completion_tokens INTEGER, cached_tokens "
               "INTEGER, cost_usd REAL, priced INTEGER NOT NULL DEFAULT 0, "
               "latency_s REAL, ts REAL NOT NULL, UNIQUE(trace_id, ts))")
    db.commit(); db.close()
    with CostLedger(p) as c:
        c.ingest_record(rec(cost=0.0, free=True))
        assert c.totals().free_calls == 1


def test_the_hook_records_the_configs_free_flag():
    from agentctl.kernel.hook import RequestHook
    r = RequestHook().record(
        {"model": "m", "litellm_params": {"model_info": {"id": "groq-a1-m0",
                                                          "free": True}}},
        {"usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    assert r["free"] is True and r["deployment"] == "groq-a1-m0"
