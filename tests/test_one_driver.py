r"""One driver per conversation, enforced. `docs/0042` I-02, `docs/0046`.

Three gaps combined into two live drivers of one conversation:

1. the lease was never renewed (`renew()` had no callers; TTL 60 s);
2. `--resume` always stole it (`takeover=bool(resume)`), even from a live run;
3. `write_intent` checked the fence only when a record already existed, so a
   superseded holder's FRESH call went straight through (probe P2).

"Zero duplicate side effects" is charter criterion 1, and `docs/0038` §4.2
skips multi-agent on the strength of this single-writer invariant. It was
enforced more weakly than it was stated: a second terminal was enough.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time

import pytest

from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import EffectClass, ToolCall, Verdict
from agentctl.kernel.ledger.store import (
    LeaseHeartbeat, LeaseHeld, LedgerStore, StaleFence,
)
from agentctl.runtime import lease
from agentctl.runtime.lease import StillRunning, claim, holder_alive, holder_id

CID = "conv_one_driver"


def _call(tcid: str, cmd: str = "git commit -m x") -> ToolCall:
    return ToolCall(tcid, CID, "t", "execute_bash", {"command": cmd})


# ══ gap 3: a superseded holder's FRESH call (P2) ═══════════════════════
def test_a_zombie_cannot_start_a_fresh_effect(tmp_path):
    """P2, made permanent. Before: `EXECUTE`, then the zombie's commit landed."""
    db = tmp_path / "l.db"
    zombie = LedgerStore(db, holder="run-1")
    fz = zombie.acquire(CID)
    recovery = LedgerStore(db, holder="run-2")
    fr = recovery.acquire(CID, takeover=True)
    assert (fz, fr) == (1, 2)

    with pytest.raises(StaleFence):
        zombie.write_intent(_call("fresh_id"), EffectClass.EXTERNAL, fz)
    assert zombie.lookup("fresh_id") is None
    zombie.close(); recovery.close()


def test_the_zombies_gate_fails_closed(tmp_path):
    """Through the gate the StaleFence becomes BLOCK -- never an effect."""
    db = tmp_path / "l.db"
    zombie = LedgerStore(db, holder="run-1")
    gate = EffectGate(zombie, Classifier(), fence=zombie.acquire(CID))
    LedgerStore(db, holder="run-2").acquire(CID, takeover=True)

    d = gate.guard(_call("fresh_id"))
    assert d.verdict is Verdict.BLOCK, d
    zombie.close()


def test_the_current_holder_is_unaffected(tmp_path):
    s = LedgerStore(tmp_path / "l.db", holder="run-1")
    f = s.acquire(CID)
    s.write_intent(_call("a"), EffectClass.EXTERNAL, f)
    assert s.lookup("a") is not None
    s.close()


# ══ gap 1: the lease has to outlive a long tool call ═══════════════════
def test_the_heartbeat_keeps_the_lease_past_its_ttl(tmp_path):
    db = tmp_path / "l.db"
    a = LedgerStore(db, holder="a")
    a.acquire(CID, ttl_s=0.6)
    beat = LeaseHeartbeat(db, "a", CID, ttl_s=0.6, interval_s=0.1).start()
    try:
        time.sleep(1.5)                       # well past the TTL
        with pytest.raises(LeaseHeld):
            LedgerStore(db, holder="b").acquire(CID)
    finally:
        beat.stop()
    a.close()


def test_a_stopped_heartbeat_lets_the_lease_expire(tmp_path):
    """Which is what a crash does, and what lets recovery proceed."""
    db = tmp_path / "l.db"
    LedgerStore(db, holder="a").acquire(CID, ttl_s=0.4)
    beat = LeaseHeartbeat(db, "a", CID, ttl_s=0.4, interval_s=0.1).start()
    beat.stop()
    time.sleep(0.6)
    assert LedgerStore(db, holder="b").acquire(CID) == 2


def test_the_heartbeat_cannot_resurrect_a_lease_it_lost(tmp_path):
    db = tmp_path / "l.db"
    LedgerStore(db, holder="a").acquire(CID, ttl_s=0.4)
    beat = LeaseHeartbeat(db, "a", CID, ttl_s=0.4, interval_s=0.05).start()
    try:
        LedgerStore(db, holder="b").acquire(CID, takeover=True)
        time.sleep(0.3)
        row = LedgerStore(db, holder="x").lease(CID)
        assert row["holder"] == "b" and row["fence_token"] == 2
    finally:
        beat.stop()


# ══ who is alive ═══════════════════════════════════════════════════════
def test_this_process_is_alive():
    assert holder_alive(holder_id()) is True


def test_an_exited_process_is_dead():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert holder_alive(holder_id(p.pid)) is False


@pytest.mark.parametrize("holder", ["run@some-other-host:123", "run-4242",
                                    "agentctl", "run@host:notapid"])
def test_a_holder_this_machine_cannot_check_is_unknown(holder):
    """Unknown is treated as alive by `claim`: waiting is slow, stealing
    from a live run is the failure."""
    assert holder_alive(holder) is None


def test_the_windows_liveness_check_never_signals_the_process():
    """`os.kill(pid, 0)` on Windows calls TerminateProcess."""
    import inspect
    src = inspect.getsource(lease.pid_alive)
    win = src[src.index('sys.platform == "win32"'):src.index("try:\n        os.kill")]
    assert "os.kill" not in win.replace("Never `os.kill(pid, 0)`", "")


# ══ gap 2: what `--resume` does with the lease ═════════════════════════
def _lease(db, holder, ttl=60.0):
    s = LedgerStore(db, holder=holder)
    s.acquire(CID, ttl_s=ttl)
    s.close()


def test_no_ledger_or_no_lease_needs_no_takeover(tmp_path):
    assert claim(tmp_path / "none.db", CID).takeover is False
    LedgerStore(tmp_path / "l.db").close()
    assert claim(tmp_path / "l.db", CID).takeover is False


def test_an_expired_lease_needs_no_takeover(tmp_path):
    _lease(tmp_path / "l.db", holder_id(), ttl=-1)
    assert claim(tmp_path / "l.db", CID).takeover is False


def test_a_dead_holder_is_taken_over_without_asking(tmp_path):
    """Crash, then resume: the case that must stay frictionless."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    _lease(tmp_path / "l.db", holder_id(p.pid))
    c = claim(tmp_path / "l.db", CID)
    assert c.takeover is True and "is gone" in c.note


def test_a_live_holder_is_refused_and_named(tmp_path):
    _lease(tmp_path / "l.db", holder_id())          # this process: alive
    with pytest.raises(StillRunning) as e:
        claim(tmp_path / "l.db", CID)
    msg = str(e.value)
    assert holder_id() in msg and "--takeover" in msg


def test_takeover_overrides_and_says_what_it_is_doing(tmp_path):
    _lease(tmp_path / "l.db", holder_id())
    c = claim(tmp_path / "l.db", CID, force=True)
    assert c.takeover is True and "ALIVE" in c.note


def test_an_unknowable_holder_is_refused_too(tmp_path):
    _lease(tmp_path / "l.db", "run-1234")           # the pre-0046 format
    with pytest.raises(StillRunning):
        claim(tmp_path / "l.db", CID)


def test_the_runner_no_longer_steals_on_every_resume():
    import inspect

    from agentctl.runtime import runner
    code = "\n".join(l.split("#")[0] for l in
                     inspect.getsource(runner.run).splitlines())
    assert "takeover=bool(resume)" not in code
    assert "claim(" in code


# ══ opening a ledger its last holder was killed holding ═══════════════
def test_a_transient_open_failure_is_retried(tmp_path, monkeypatch):
    """Windows releases a killed process's -shm locks asynchronously, and the
    next open fails with "disk I/O error" (5 of 8 kill-then-open trials,
    `docs/0046`). Retried briefly; succeeded ~50 ms later every time."""
    import sqlite3

    from agentctl.kernel.ledger import store as st

    real, fails = sqlite3.connect, {"n": 1}

    class Flaky:
        def __init__(self, conn):
            self._c = conn

        def executescript(self, s):
            if fails["n"]:
                fails["n"] -= 1
                raise sqlite3.OperationalError("disk I/O error")
            return self._c.executescript(s)

        def __getattr__(self, k):
            return getattr(self._c, k)

        def __setattr__(self, k, v):
            if k == "_c":
                object.__setattr__(self, k, v)
            else:
                setattr(self._c, k, v)

    monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: Flaky(real(*a, **k)))
    s = LedgerStore(tmp_path / "l.db")
    assert s.acquire(CID) == 1 and fails["n"] == 0
    s.close()


def test_a_real_error_is_not_retried(tmp_path, monkeypatch):
    import sqlite3

    from agentctl.kernel.ledger import store as st

    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise sqlite3.OperationalError("no such table: nope")

    class C:
        row_factory = None
        executescript = staticmethod(boom)

        def close(self):
            pass

    monkeypatch.setattr(st.sqlite3, "connect", lambda *a, **k: C())
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        LedgerStore(tmp_path / "l.db")
    assert len(calls) == 1


# ══ E-02, with real processes ══════════════════════════════════════════
HOLDER = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {root!r})
    from agentctl.kernel.ledger.store import LedgerStore, LeaseHeartbeat
    from agentctl.runtime.lease import holder_id
    db, cid = sys.argv[1], sys.argv[2]
    s = LedgerStore(db, holder=holder_id()); s.acquire(cid, ttl_s=1.0)
    LeaseHeartbeat(db, holder_id(), cid, ttl_s=1.0, interval_s=0.2).start()
    print("holding", flush=True)
    time.sleep(60)
""")


def test_a_second_driver_is_refused_while_the_first_lives_then_admitted(tmp_path):
    """E-02 (`docs/0042` §3.1). Run A holds the conversation and outlives its
    TTL; resume B must refuse. A is then killed hard; B must take over at
    once, without waiting the TTL out and without `--takeover`."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db = tmp_path / "l.db"
    a = subprocess.Popen([sys.executable, "-c", HOLDER.format(root=root),
                          str(db), CID], stdout=subprocess.PIPE, text=True)
    try:
        assert a.stdout.readline().strip() == "holding"
        time.sleep(2.0)                                 # twice the TTL
        with pytest.raises(StillRunning):
            claim(db, CID)
    finally:
        a.kill()
        a.wait()
    c = claim(db, CID)
    assert c.takeover is True and "is gone" in c.note
    assert LedgerStore(db, holder=holder_id()).acquire(CID, takeover=c.takeover) > 1
