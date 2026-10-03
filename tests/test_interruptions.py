"""Interruptions and decisions. `docs/0043` Phase 4, `docs/0049`.

The promise: a run that is killed, left unattended, or rate-limited ends with
ONE command that continues it -- and nothing asks a terminal nobody is at.
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import EffectState, ToolCall, Verdict
from agentctl.kernel.ledger.store import LedgerStore
from agentctl.runtime import runs
from agentctl.runtime.runner import (AWAITING, RateLimited, _install_confirmation,
                                     _PauseOnInterrupt, _tell_decisions)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCTL_HOME", str(tmp_path / "ah"))
    return tmp_path


# ══ the run index ══════════════════════════════════════════════════════
def test_a_run_is_recorded_from_start_to_end(home):
    rid = runs.start("c0ffee00-0000-0000-0000-000000000001", home, home / "l.db",
                     "m", None, "fix the bug")
    r = runs.recent()[0]
    assert (r.status, r.task, r.state) == ("running", "fix the bug", "running")
    runs.end(rid, "done", outcome="PASS", requests=9)
    r = runs.recent()[0]
    assert (r.status, r.outcome, r.requests) == ("done", "PASS", 9)


def test_a_running_row_whose_process_is_gone_died(home, monkeypatch):
    """Writing the start first is what makes a missing end evidence."""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    monkeypatch.setattr(os, "getpid", lambda: p.pid)
    runs.start("dead0000-0000-0000-0000-000000000001", home, home / "l.db",
               "m", None, "t")
    assert runs.recent()[0].state == "died"


def test_find_prefers_this_workspace_then_anywhere(home):
    a, b = home / "a", home / "b"
    a.mkdir(); b.mkdir()
    runs.start("aaaa0000-0000-0000-0000-000000000001", a, a / "l.db", "m", None, "t")
    runs.start("bbbb0000-0000-0000-0000-000000000001", b, b / "l.db", "m", None, "t")
    assert runs.find(workspace=a).conversation_id.startswith("aaaa")
    assert runs.find(workspace=home / "elsewhere").conversation_id.startswith("bbbb")


def test_find_by_prefix_refuses_ambiguity(home):
    for c in ("abcd1111-0000-0000-0000-000000000001",
              "abcd2222-0000-0000-0000-000000000001"):
        runs.start(c, home, home / "l.db", "m", None, "t")
    assert runs.find("abcd1").conversation_id.startswith("abcd1111")
    with pytest.raises(SystemExit, match="matches 2 conversations"):
        runs.find("abcd")
    with pytest.raises(SystemExit, match="no run with an id starting"):
        runs.find("ffff")


def test_no_runs_says_how_to_start_one(home):
    with pytest.raises(SystemExit, match="agentctl run"):
        runs.find()


def test_the_index_never_breaks_a_run(home, monkeypatch):
    monkeypatch.setattr(runs, "_db", lambda: (_ for _ in ()).throw(OSError("disk")))
    assert runs.start("c", home, home / "l.db", "m", None, "t") is None
    runs.end(None, "done")                                   # must not raise


# ══ approvals with nobody at a terminal (I-06, F7) ════════════════════
RM = {"command": "rm -rf build"}                             # DESTRUCTIVE


@pytest.fixture
def wired(tmp_path):
    store = LedgerStore(tmp_path / "l.db", holder="t")
    cid = str(uuid.uuid4())
    gate = EffectGate(store, Classifier(), fence=store.acquire(cid))

    class G:
        pass

    guard = G()
    guard.gate = gate
    _install_confirmation(guard, verbose=False, workspace=tmp_path, interactive=False)
    yield gate, store, cid
    store.close()


def _c(cid, tcid, args=RM):
    return ToolCall(tcid, cid, "t", "execute_bash", dict(args))


def test_unattended_a_dangerous_action_is_queued_not_refused(wired):
    gate, store, cid = wired
    d = gate.guard(_c(cid, "c1"))
    assert d.verdict is Verdict.BLOCK and "queued" in d.reason
    assert "Do NOT repeat it" in d.reason
    rec = store.lookup("c1")
    assert rec.state is EffectState.BLOCKED and rec.error.startswith(AWAITING)
    assert "rm -rf build" in rec.error


def test_a_repeat_of_a_queued_action_is_the_same_one(wired):
    """Analyst A's check: three re-issues must alias to ONE pending record."""
    gate, store, cid = wired
    for i in range(3):
        assert gate.guard(_c(cid, f"r{i}")).verdict is Verdict.BLOCK
    assert len(store.blocked(cid)) == 1


def test_approved_it_runs_once_without_asking_again(wired):
    gate, store, cid = wired
    gate.guard(_c(cid, "c1"))
    store._fences[cid] = store.lookup("c1").fence_token
    store.decide(store.lookup("c1"), "approve", "bash: rm -rf build")
    assert store.lookup("c1").state is EffectState.FAILED       # did not run
    assert store.blocked(cid) == []

    assert gate.guard(_c(cid, "c2")).verdict is Verdict.EXECUTE
    # Used once: the next identical action is asked about (queued) again.
    gate.store.deliver("c2", b"{}")
    assert gate.guard(_c(cid, "c3")).verdict is Verdict.BLOCK


def test_denied_it_never_runs(wired):
    gate, store, cid = wired
    gate.guard(_c(cid, "c1"))
    store.decide(store.lookup("c1"), "deny", "bash: rm -rf build")
    d = gate.guard(_c(cid, "c2"))
    assert d.verdict is Verdict.BLOCK and "denied" in d.reason
    assert store.lookup("c2").state is EffectState.FAILED


def test_a_refusal_at_the_terminal_is_recorded_as_not_run(tmp_path, monkeypatch):
    """It used to leave an INTENT record, which a later identical call would
    have treated as a crash to reconcile."""
    store = LedgerStore(tmp_path / "l.db", holder="t")
    cid = str(uuid.uuid4())
    gate = EffectGate(store, Classifier(), fence=store.acquire(cid))
    guard = type("G", (), {})()
    guard.gate = gate
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    _install_confirmation(guard, verbose=False, workspace=tmp_path, interactive=True)
    assert gate.guard(_c(cid, "c1")).reason == "refused by the operator"
    assert store.lookup("c1").state is EffectState.FAILED
    store.close()


def test_a_terminal_that_closes_mid_question_queues(tmp_path, monkeypatch):
    store = LedgerStore(tmp_path / "l.db", holder="t")
    cid = str(uuid.uuid4())
    gate = EffectGate(store, Classifier(), fence=store.acquire(cid))
    guard = type("G", (), {})()
    guard.gate = gate

    def eof(*_):
        raise EOFError

    monkeypatch.setattr("builtins.input", eof)
    _install_confirmation(guard, verbose=False, workspace=tmp_path, interactive=True)
    assert "queued" in gate.guard(_c(cid, "c1")).reason
    store.close()


def test_the_resumed_agent_is_told_what_was_decided_once(wired):
    gate, store, cid = wired
    gate.guard(_c(cid, "c1"))
    gate.guard(_c(cid, "d1", {"command": "rm -rf dist"}))
    store.decide(store.lookup("c1"), "approve", "bash: rm -rf build")
    store.decide(store.lookup("d1"), "deny", "bash: rm -rf dist")
    msg = _tell_decisions(store, cid)
    assert "APPROVED: bash: rm -rf build" in msg and "DENIED: bash: rm -rf dist" in msg
    assert _tell_decisions(store, cid) is None, "told once, not on every resume"


# ══ the CLI ════════════════════════════════════════════════════════════
@pytest.fixture
def queued(home):
    """A real workspace ledger, indexed, holding one action awaiting approval
    and one ambiguous one."""
    ws = home / "ws"
    ws.mkdir()
    ledger = ws / ".agentctl" / "ledger.db"
    cid = "feed0000-0000-0000-0000-000000000001"
    with LedgerStore(ledger, holder="t") as s:
        f = s.acquire(cid, ttl_s=-1)
        s.write_intent(_c(cid, "call_waiting_01"), Classifier().classify(_c(cid, "x")), f)
        s.block("call_waiting_01", f"{AWAITING} (DESTRUCTIVE): bash: rm -rf build")
        s.write_intent(_c(cid, "call_unknown_01", {"command": "git commit -m x"}),
                       Classifier().classify(_c(cid, "x")), f)
        s.block("call_unknown_01", "cannot determine whether it executed")
    runs.start(cid, ws, ledger, "openrouter/x:free", None, "clean up")
    return ws, ledger, cid


def test_approve_finds_the_effect_without_a_path(queued, capsys, monkeypatch, tmp_path):
    from agentctl import cli
    monkeypatch.chdir(tmp_path)                               # no ./ledger.db here
    assert cli.main(["approve", "call_waiting"]) == 0
    assert "agentctl resume feed0000" in capsys.readouterr().out
    with LedgerStore(queued[1]) as s:
        assert s.lookup("call_waiting_01").state is EffectState.FAILED
        assert s.approval(queued[2], s.lookup("call_waiting_01").intent_hash) == "approve"


def test_approve_refuses_an_effect_that_is_not_waiting(queued, capsys, monkeypatch, tmp_path):
    from agentctl import cli
    monkeypatch.chdir(tmp_path)
    assert cli.main(["approve", "call_unknown"]) == 2
    assert "agentctl resolve" in capsys.readouterr().err


def test_blocked_and_status_need_no_ledger_path(queued, capsys, monkeypatch, tmp_path):
    """Phase 0 F4: "no ledger at ledger.db" from inside the workspace."""
    from agentctl import cli
    monkeypatch.chdir(tmp_path)
    assert cli.main(["blocked"]) == 0
    out = capsys.readouterr().out
    assert "waiting for your approval" in out and "agentctl approve call_waiting" in out
    assert "call_unknown" in out
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "feed0000" in out and "2 action(s) need you" in out


def test_resume_needs_no_id_and_keeps_the_model(queued, monkeypatch):
    from agentctl import cli
    ws, _, cid = queued
    got = {}
    monkeypatch.chdir(ws)
    monkeypatch.setattr("agentctl.runtime.runner.run",
                        lambda **kw: got.update(kw) or {"blocked": [], "decisions": []})
    assert cli.main(["resume"]) == 0
    assert got["resume"] == cid and got["task"] == ""
    assert Path(got["workspace"]) == ws and got["model"] == "openrouter/x:free"


# ══ waiting out a rate limit (I-05, wait-only) ════════════════════════
def _flaky_run(fails: int, reset_at=None):
    calls = []

    def run(**kw):
        calls.append(kw)
        if len(calls) <= fails:
            raise RateLimited("the provider is rate limiting you", "cafe0000-x", reset_at)
        return {"blocked": [], "decisions": []}
    return run, calls


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr("agentctl.cli.time.sleep", lambda s: slept.append(s))
    monkeypatch.setenv("AGENTCTL_MODEL", "openrouter/x:free")
    return slept


def test_without_wait_a_rate_limit_ends_with_the_resume_command(home, no_sleep, capsys,
                                                                 monkeypatch):
    from agentctl import cli
    run, calls = _flaky_run(1)
    monkeypatch.setattr("agentctl.runtime.runner.run", run)
    assert cli.main(["run", "x", "--workspace", str(home)]) == 1
    out = capsys.readouterr().out
    assert "agentctl resume cafe0000" in out and "--wait" in out
    assert no_sleep == [] and len(calls) == 1


def test_with_wait_it_waits_and_resumes_the_same_conversation(home, no_sleep, monkeypatch):
    from agentctl import cli
    run, calls = _flaky_run(2)
    monkeypatch.setattr("agentctl.runtime.runner.run", run)
    assert cli.main(["run", "x", "--workspace", str(home), "--wait", "10m"]) == 0
    assert no_sleep == [60.0, 120.0], "a doubling backoff with no reset header"
    assert calls[1]["resume"] == "cafe0000-x" and calls[1]["task"] == ""


def test_a_reset_past_the_wait_stops_and_says_so(home, no_sleep, capsys, monkeypatch):
    import time as _t
    from agentctl import cli
    run, _ = _flaky_run(1, reset_at=_t.time() + 7200)
    monkeypatch.setattr("agentctl.runtime.runner.run", run)
    assert cli.main(["run", "x", "--workspace", str(home), "--wait", "30m"]) == 1
    assert no_sleep == [] and "past --wait" in capsys.readouterr().out


def test_waiting_is_bounded_in_attempts(home, no_sleep, monkeypatch):
    from agentctl import cli
    run, calls = _flaky_run(99)
    monkeypatch.setattr("agentctl.runtime.runner.run", run)
    assert cli.main(["run", "x", "--workspace", str(home), "--wait", "100h"]) == 1
    assert len(calls) == 6 and len(no_sleep) == 5


@pytest.mark.parametrize("text,s", [("90s", 90), ("30m", 1800), ("2h", 7200), ("45", 45)])
def test_durations(text, s):
    from agentctl.cli import _duration_s
    assert _duration_s(text) == s


# ══ Ctrl-C ═════════════════════════════════════════════════════════════
def test_the_first_ctrl_c_pauses_the_second_stops():
    class Conv:
        paused = 0

        def pause(self):
            Conv.paused += 1

    stop = _PauseOnInterrupt(Conv(), verbose=False)
    stop._handle(2, None)
    assert stop.paused and Conv.paused == 1
    with pytest.raises(KeyboardInterrupt):
        stop._handle(2, None)


def test_the_handler_is_restored_afterwards():
    import signal
    before = signal.getsignal(signal.SIGINT)
    with _PauseOnInterrupt(object(), verbose=False):
        assert signal.getsignal(signal.SIGINT) != before
    assert signal.getsignal(signal.SIGINT) == before
