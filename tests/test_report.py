"""The end-of-run report. `docs/0043` Phase 3, `docs/0048`.

Phase 0 ended every run with `decisions {'EXECUTE': 9}`, and both successful
tasks exited 1. The report must answer: did it work, what changed, what did it
cost, what is left -- and must never print a success it did not check.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from agentctl.runtime import report as rp


def git(ws: Path, *a):
    subprocess.run(["git", *a], cwd=ws, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "user.email", "t@example.com")
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "seed")
    return tmp_path


# ══ what changed ═══════════════════════════════════════════════════════
def test_edits_new_files_and_commits_are_all_counted(repo):
    start = rp.snapshot(repo)
    (repo / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    (repo / "b.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
    git(repo, "add", "b.py")
    git(repo, "commit", "-qm", "agent commit")
    (repo / "c.txt").write_text("new\n", encoding="utf-8")          # untracked

    c = rp.changes(repo, start)
    files = {p: (a, d) for p, a, d in c.files}
    assert files == {"a.py": (1, 0), "b.py": (3, 0), "c.txt": (1, 0)}
    assert c.commits == 1 and (c.added, c.removed) == (5, 0)


def test_agentctls_own_state_is_never_a_change(repo):
    start = rp.snapshot(repo)
    (repo / ".agentctl").mkdir()
    (repo / ".agentctl" / "ledger.db").write_bytes(b"x")
    assert rp.changes(repo, start).files == []


def test_files_already_dirty_are_flagged_not_hidden(repo):
    (repo / "a.py").write_text("users edit\n", encoding="utf-8")
    start = rp.snapshot(repo)
    c = rp.changes(repo, start)
    assert c.already_dirty == 1
    assert [p for p, _, _ in c.files] == ["a.py"]   # differs from HEAD; mixed


def test_a_repo_with_no_commits_still_reports_new_files(tmp_path):
    git(tmp_path, "init", "-q")
    start = rp.snapshot(tmp_path)
    (tmp_path / "n.py").write_text("a\nb\n", encoding="utf-8")
    assert rp.changes(tmp_path, start).files == [("n.py", 2, 0)]


def test_a_workspace_inside_a_bigger_repo_reports_only_itself(repo):
    """Found live: a scratch workspace inside the owner's home-directory repo.
    Unscoped, the report would describe the whole home repository."""
    ws = repo / "sub" / "ws"
    ws.mkdir(parents=True)
    (repo / "outside.txt").write_text("not ours\n", encoding="utf-8")
    start = rp.snapshot(ws)
    (repo / "a.py").write_text("changed outside\n", encoding="utf-8")
    (ws / "inside.py").write_text("x\n", encoding="utf-8")

    c = rp.changes(ws, start)
    assert [p for p, _, _ in c.files] == ["inside.py"]
    assert "inside the repository at" in c.note
    text = "\n".join(rp.Report(
        outcome="not checked", accept=None, changes=c, agent_said=None,
        usage=rp.Usage(0, 0, 0.0), model="m", seconds=1, decisions=[],
        blocked=[], ledger="L", conversation_id="C", workspace=str(ws)).lines())
    assert "inside.py" in text and "outside.txt" not in text and "a.py" not in text


def test_outside_git_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "_git", lambda *a: None)
    c = rp.changes(tmp_path, rp.snapshot(tmp_path))
    assert "not a git repository" in c.note


# ══ what it cost ═══════════════════════════════════════════════════════
@pytest.mark.parametrize("model,cost,expect", [
    ("openrouter/nvidia/x:free", 0.0, "$0.00 (free-tier model)"),
    ("openai/pool", 0.0123, "$0.00 (free-tier model)"),
    ("openai/pool-gemini", 0.0, "$0.00 (free-tier model)"),
    ("gemini/gemini-3.6-flash", 0.0042, "at list price"),
    ("anthropic/claude-x", 0.25, "$0.2500 (as litellm priced it)"),
    ("anthropic/claude-x", 0.0, "unknown"),
])
def test_cost_is_labelled_with_what_it_can_be_trusted_for(model, cost, expect):
    """`docs/0042` I-10: list prices on free calls, nothing on `:free` ones."""
    assert expect in rp.describe_cost(model, cost)


def test_usage_is_the_difference_across_the_run():
    class M:
        response_latencies = [1, 2, 3]
        accumulated_cost = 0.5

        class accumulated_token_usage:
            prompt_tokens, completion_tokens = 900, 100

    class Conv:
        class state:
            class stats:
                @staticmethod
                def get_combined_metrics():
                    return M

    u = rp.Usage.of(Conv)
    assert (u.requests, u.tokens, u.cost) == (3, 1000, 0.5)
    assert (u - rp.Usage(1, 400, 0.5)) == rp.Usage(2, 600, 0.0)


def test_unreadable_metrics_are_zero_not_a_crash():
    assert rp.Usage.of(object()) == rp.Usage(0, 0, 0.0)


# ══ the report ═════════════════════════════════════════════════════════
def _report(**kw):
    base = dict(outcome="not checked", accept=None, changes=rp.Changes(),
                agent_said="Fixed it.\nAlso added a test.", usage=rp.Usage(11, 47700, 0.0),
                model="openrouter/x:free", seconds=160, decisions=[
                    {"verdict": "EXECUTE", "class": "PURE_READ"},
                    {"verdict": "EXECUTE", "class": "EXTERNAL"},
                    {"verdict": "SUBSTITUTE", "class": "EXTERNAL"}],
                blocked=[], ledger="L", conversation_id="C", workspace="W")
    base.update(kw)
    return rp.Report(**base)


def test_not_checked_is_never_printed_as_a_pass():
    text = "\n".join(_report().lines())
    assert "not checked" in text and "PASS" not in text
    assert _report().ok, "unchecked is not a failure either"


def test_a_failed_check_shows_why_and_fails_the_run():
    r = _report(outcome="FAIL", accept={"command": "pytest -q", "exit": 1,
                                        "tail": ["1 failed, 2 passed"]})
    text = "\n".join(r.lines())
    assert "FAIL" in text and "1 failed, 2 passed" in text
    assert not r.ok


def test_a_paused_action_is_what_needs_you():
    """An effect whose outcome is unknown. `agentctl blocked` finds it through
    the run index -- no `--ledger` (docs/0049)."""
    r = _report(blocked=["call_abc"])
    text = "\n".join(r.lines())
    assert "1 action whose outcome is unknown: agentctl blocked" in text
    assert "--ledger" not in text
    assert not r.ok


def test_an_action_waiting_for_approval_says_how_to_answer():
    r = _report(blocked=["call_abcdef123456789"],
                awaiting=[("call_abcdef123456789", "bash: rm -rf build")])
    text = "\n".join(r.lines())
    assert "waiting for your approval" in text and "rm -rf build" in text
    assert "agentctl approve call_abcdef1" in text and "agentctl deny call_abcdef1" in text
    assert "outcome is unknown" not in text
    assert "agentctl resume C" in text and not r.ok


def test_a_paused_run_is_not_done_and_says_how_to_continue():
    r = _report(paused=True)
    assert "paused      by you. Continue:  agentctl resume C" in "\n".join(r.lines())
    assert not r.ok


def test_it_speaks_the_users_words_not_the_gates():
    text = "\n".join(_report().lines())
    assert "1 read" in text and "2 commands" in text and "1 already done, reused" in text
    for internal in ("EXECUTE", "SUBSTITUTE", "PURE_READ", "EXTERNAL"):
        assert internal not in text
    assert "11 requests" in text and "47.7K tokens" in text and "2m 40s" in text
    assert 'agent said  "Fixed it."' in text


# ══ acceptance ═════════════════════════════════════════════════════════
def test_accept_passes_on_exit_zero(tmp_path):
    a = rp.accept(f'"{sys.executable}" -c "print(1)"', tmp_path)
    assert a["passed"] and a["exit"] == 0


def test_accept_fails_on_nonzero_and_keeps_the_tail(tmp_path):
    a = rp.accept(f'"{sys.executable}" -c "import sys; print(\'2 failed\'); sys.exit(3)"',
                  tmp_path)
    assert not a["passed"] and a["exit"] == 3 and "2 failed" in a["tail"][-1]


def test_accept_times_out_as_a_failure(tmp_path):
    a = rp.accept(f'"{sys.executable}" -c "import time; time.sleep(5)"', tmp_path,
                  timeout_s=0.5)
    assert not a["passed"] and a["exit"] is None and "timed out" in a["tail"][0]


# ══ the exit code ══════════════════════════════════════════════════════
@pytest.mark.parametrize("kw,code", [
    ({}, 0),
    ({"blocked": ["x"]}, 1),
    ({"outcome": "FAIL", "accept": {"command": "c", "exit": 1, "tail": []}}, 1),
    ({"outcome": "PASS", "accept": {"command": "c", "exit": 0, "tail": []}}, 0),
])
def test_run_exits_by_the_report(tmp_path, monkeypatch, kw, code):
    """Both of Phase 0's successful tasks exited 1 (`docs/0044` N15)."""
    from agentctl import cli

    monkeypatch.setenv("AGENTCTL_MODEL", "openrouter/x:free")
    monkeypatch.setattr("agentctl.runtime.runner.run",
                        lambda **a: {"conversation_id": "c", "ledger": "l",
                                     "decisions": [], "blocked": kw.get("blocked", []),
                                     "workspace": "w", "report": _report(**kw)})
    assert cli.main(["run", "x", "--workspace", str(tmp_path)]) == code
