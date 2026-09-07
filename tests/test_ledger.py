"""Ledger state machine and durability. docs/0012 §2."""
import pytest

from agentctl.kernel.ledger.models import (
    EffectClass, EffectState, IllegalTransition, ToolCall,
)
from agentctl.kernel.ledger.store import LedgerStore, LeaseHeld


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "ledger.db", holder="test") as s:
        yield s


def call(cid="tc_1", tool="write_file", **args):
    return ToolCall(tool_call_id=cid, conversation_id="conv_1",
                    turn_id="turn_1", tool_name=tool, args=args or {"path": "a.txt"})


def test_durability_pragmas(store):
    row = store._db.execute("PRAGMA synchronous").fetchone()[0]
    assert row == 2, "synchronous must be FULL -- NORMAL can lose the last commit"
    assert store._db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_write_intent_then_commit(store):
    c = call()
    store.write_intent(c, EffectClass.IDEMPOTENT_WRITE, fence=1)
    assert store.lookup(c.tool_call_id).state is EffectState.INTENT
    store.commit(c.tool_call_id, b'{"ok":true}')
    rec = store.lookup(c.tool_call_id)
    assert rec.state is EffectState.COMMITTED
    assert rec.observation == b'{"ok":true}'
    assert rec.committed_at is not None


def test_pending_is_the_ambiguous_set(store):
    store.write_intent(call("tc_a"), EffectClass.EXTERNAL, 1)
    store.write_intent(call("tc_b"), EffectClass.EXTERNAL, 1)
    store.commit("tc_b", b"{}")
    pending = store.pending("conv_1")
    assert [r.tool_call_id for r in pending] == ["tc_a"]


def test_illegal_transition_raises(store):
    c = call()
    store.write_intent(c, EffectClass.PURE_READ, 1)
    store.commit(c.tool_call_id)
    store.observed(c.tool_call_id)
    with pytest.raises(IllegalTransition):
        store.commit(c.tool_call_id)          # OBSERVED is terminal


def test_failed_can_retry_and_bumps_attempt(store):
    c = call()
    store.write_intent(c, EffectClass.PURE_READ, 1)
    store.fail(c.tool_call_id, "boom")
    assert store.lookup(c.tool_call_id).state is EffectState.FAILED
    rec = store.write_intent(c, EffectClass.PURE_READ, 1)
    assert rec.state is EffectState.INTENT and rec.attempt == 2


def test_reconcile_landed_marks_committed(store):
    c = call(tool="execute_bash", command="git commit -m x")
    store.write_intent(c, EffectClass.NON_IDEMPOTENT_WRITE, 1)
    store.reconcile(c.tool_call_id, "LANDED", landed=True)
    rec = store.lookup(c.tool_call_id)
    assert rec.state is EffectState.COMMITTED and rec.probe_verdict == "LANDED"


def test_blocked_is_listed_for_human_resolution(store):
    c = call()
    store.write_intent(c, EffectClass.EXTERNAL, 1)
    store.block(c.tool_call_id, "probe inconclusive")
    assert [r.tool_call_id for r in store.blocked()] == [c.tool_call_id]


def test_lease_fencing_rejects_a_live_second_holder(tmp_path):
    a = LedgerStore(tmp_path / "l.db", holder="worker-a")
    b = LedgerStore(tmp_path / "l.db", holder="worker-b")
    t1 = a.acquire("conv_1", ttl_s=60)
    with pytest.raises(LeaseHeld):
        b.acquire("conv_1", ttl_s=60)
    a.release("conv_1")
    t2 = b.acquire("conv_1", ttl_s=60)
    assert t2 > t1, "fence tokens must be monotonic"
    a.close(); b.close()


def test_survives_reopen(tmp_path):
    """Durability: the record must be there after the process dies."""
    c = call()
    s1 = LedgerStore(tmp_path / "l.db"); s1.write_intent(c, EffectClass.EXTERNAL, 1)
    s1.close()
    s2 = LedgerStore(tmp_path / "l.db")
    assert s2.lookup(c.tool_call_id).state is EffectState.INTENT
    s2.close()


# ── lease takeover & fencing (found by the M2a chaos run) ──────────────
def test_crashed_holder_blocks_recovery_without_takeover(tmp_path):
    """A crashed process cannot release its lease. Recovery must be explicit.

    Found empirically: the M2a chaos run deadlocked because the killed process
    still held a live 300s lease and the resume refused to start.
    """
    dead = LedgerStore(tmp_path / "l.db", holder="crashed")
    dead.acquire("conv_1", ttl_s=300)          # process dies here
    recovery = LedgerStore(tmp_path / "l.db", holder="resume")
    with pytest.raises(LeaseHeld):
        recovery.acquire("conv_1")
    dead.close(); recovery.close()


def test_takeover_steals_a_live_lease_and_bumps_the_fence(tmp_path):
    dead = LedgerStore(tmp_path / "l.db", holder="crashed")
    t1 = dead.acquire("conv_1", ttl_s=300)
    recovery = LedgerStore(tmp_path / "l.db", holder="resume")
    t2 = recovery.acquire("conv_1", takeover=True)
    assert t2 > t1
    dead.close(); recovery.close()


def test_superseded_holder_is_fenced_out(tmp_path):
    """Takeover is only safe because the zombie is rejected on its next write."""
    from agentctl.kernel.ledger.store import StaleFence

    zombie = LedgerStore(tmp_path / "l.db", holder="zombie")
    zombie.acquire("conv_1", ttl_s=300)
    c = call("tc_z")
    zombie.write_intent(c, EffectClass.EXTERNAL, fence=1)

    recovery = LedgerStore(tmp_path / "l.db", holder="resume")
    recovery.acquire("conv_1", takeover=True)          # fence -> 2
    recovery.write_intent(c, EffectClass.EXTERNAL, fence=2)

    # The zombie wakes up and tries to finish its work.
    with pytest.raises(StaleFence):
        zombie.commit(c.tool_call_id, b"{}")
    zombie.close(); recovery.close()


def test_expired_lease_is_taken_without_force(tmp_path):
    a = LedgerStore(tmp_path / "l.db", holder="a")
    a.acquire("conv_1", ttl_s=-1)              # already expired
    b = LedgerStore(tmp_path / "l.db", holder="b")
    assert b.acquire("conv_1") > 0             # no takeover needed
    a.close(); b.close()


def test_renew_extends_the_lease(tmp_path):
    import time as _t
    a = LedgerStore(tmp_path / "l.db", holder="a")
    a.acquire("conv_1", ttl_s=0.3)
    a.renew("conv_1", ttl_s=60)
    _t.sleep(0.4)
    b = LedgerStore(tmp_path / "l.db", holder="b")
    with pytest.raises(LeaseHeld):
        b.acquire("conv_1")
    a.close(); b.close()
