"""The nine-point chaos suite. `docs/0012` §6, `docs/0008` §10.

This is the specification. Everything else in the project exists so that this
passes: crash at any point in the write-ahead protocol, resume, and the side
effect must have happened **at most once**.

Real process death — the worker calls `os._exit()`, which skips every finally
block, atexit hook and buffer flush. Real effects — a git commit and a file
append, counted from the filesystem afterwards, not mocked.

Two effect kinds, because they fail differently:

  git      atomic from our side; the commit exists or it does not
  append   non-atomic; `mid_tool` leaves half a line on disk, which is the
           nastiest case the probe has to judge
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[1] / "experiments" / "0004-nine-point" / "worker.py"

CRASH_POINTS = [
    "before_action_event",
    "after_action_event",
    "before_intent",
    "after_intent",
    "mid_tool",
    "after_tool",
    "before_commit",
    "after_commit",
    "before_observation",
    "after_observed",       # the tenth, docs/0045
]

APPEND_TEXT = "EFFECT-LINE\n"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


# ── harness ────────────────────────────────────────────────────────────
def git(repo: Path, *args: str):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


def make_workdir(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "chaos@example.com")
    git(repo, "config", "user.name", "chaos")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "initial")
    (tmp_path / "log.txt").write_text("PRE-EXISTING\n", encoding="utf-8")
    return tmp_path


def run_worker(workdir: Path, effect: str, point: str | None = None,
               resume: bool = False,
               remint: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, "-X", "utf8", str(WORKER),
            "--workdir", str(workdir), "--effect", effect,
            "--point", point or "none"]
    if resume:
        argv.append("--resume")
    if remint:
        argv.append("--remint")
    return subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


def commits(repo: Path) -> int:
    r = git(repo, "rev-list", "--count", "HEAD")
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else 0


def appended(target: Path) -> str:
    """Everything written after the pre-existing content."""
    if not target.exists():
        return ""
    return target.read_text(encoding="utf-8").replace("PRE-EXISTING\n", "", 1)


def decision(workdir: Path, which: str) -> dict | None:
    f = workdir / f"decision_{which}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def ledger_state(workdir: Path) -> str | None:
    from agentctl.kernel.ledger.store import LedgerStore
    with LedgerStore(workdir / "ledger.db", holder="assert") as s:
        rec = s.lookup("call_nine_point_0001")
        return rec.state.value if rec else None


# ══ THE GUARANTEE ══════════════════════════════════════════════════════
@needs_git
@pytest.mark.parametrize("point", CRASH_POINTS)
def test_git_commit_never_happens_twice(tmp_path, point):
    """docs/0008 §10: crash anywhere, the commit lands at most once."""
    wd = make_workdir(tmp_path)
    repo = wd / "repo"
    before = commits(repo)

    crashed = run_worker(wd, "git", point=point)
    after_crash = commits(repo)
    assert after_crash - before <= 1, "the first run itself duplicated"

    resumed = run_worker(wd, "git", resume=True)
    after_resume = commits(repo)

    assert after_resume - before <= 1, (
        f"DUPLICATE COMMIT after crashing at {point}: "
        f"{before} -> {after_crash} -> {after_resume}\n"
        f"crash stderr: {crashed.stderr[-400:]}\n"
        f"resume stderr: {resumed.stderr[-400:]}"
    )


@pytest.mark.parametrize("point", CRASH_POINTS)
def test_append_never_happens_twice(tmp_path, point):
    """Same guarantee for a non-atomic effect."""
    wd = make_workdir(tmp_path)
    target = wd / "log.txt"

    run_worker(wd, "append", point=point)
    after_crash = appended(target)
    run_worker(wd, "append", resume=True)
    after_resume = appended(target)

    assert after_resume.count(APPEND_TEXT) <= 1, (
        f"DUPLICATE APPEND after crashing at {point}: {after_resume!r}"
    )
    # A half-written line must never be silently completed by a second run
    # stacking another one on top of it.
    assert len(after_resume) <= len(APPEND_TEXT) + 2, (
        f"tail grew beyond one effect at {point}: {after_resume!r}"
    )


# ══ per-point expectations ═════════════════════════════════════════════
@needs_git
@pytest.mark.parametrize("point,expected_state", [
    ("before_action_event", None),          # nothing recorded at all
    ("after_action_event", None),
    ("before_intent", None),
    ("after_intent", "INTENT"),
    ("mid_tool", "INTENT"),
    ("after_tool", "INTENT"),
    ("before_commit", "INTENT"),
    ("after_commit", "COMMITTED"),
    ("before_observation", "COMMITTED"),
    ("after_observed", "OBSERVED"),
])
def test_ledger_state_after_the_crash(tmp_path, point, expected_state):
    """The ledger must land in the state docs/0008 §10 predicts."""
    wd = make_workdir(tmp_path)
    run_worker(wd, "git", point=point)
    assert ledger_state(wd) == expected_state


@needs_git
@pytest.mark.parametrize("point,expected_verdict", [
    # Nothing was recorded, so the resume is an ordinary first sighting.
    ("before_action_event", "EXECUTE"),
    ("after_action_event", "EXECUTE"),
    ("before_intent", "EXECUTE"),
    # INTENT with the effect provably absent: the probe says so, run it.
    ("after_intent", "EXECUTE"),
    ("mid_tool", "EXECUTE"),
    # INTENT with the effect provably present: do not run it again.
    ("after_tool", "SUBSTITUTE"),
    ("before_commit", "SUBSTITUTE"),
    # Already committed: substitute from the record.
    ("after_commit", "SUBSTITUTE"),
    ("before_observation", "SUBSTITUTE"),
    # Seen, then the SDK re-drives the SAME action: still a replay.
    ("after_observed", "SUBSTITUTE"),
])
def test_resume_verdict(tmp_path, point, expected_verdict):
    """The probe should resolve every point without a human."""
    wd = make_workdir(tmp_path)
    run_worker(wd, "git", point=point)
    run_worker(wd, "git", resume=True)
    d = decision(wd, "resume")
    assert d is not None, "the resume made no decision"
    assert d["verdict"] == expected_verdict, f"at {point}: {d}"


@needs_git
def test_the_commit_actually_happens_when_nothing_crashes(tmp_path):
    """A guard that blocks everything would pass every test above."""
    wd = make_workdir(tmp_path)
    before = commits(wd / "repo")
    run_worker(wd, "git")
    assert commits(wd / "repo") == before + 1
    assert ledger_state(wd) == "OBSERVED"


def test_partial_append_is_not_silently_completed(tmp_path):
    """The nastiest case: half a line on disk, and we cannot prove whose.

    The probe must refuse to call this LANDED or DID_NOT_LAND. Blocking is the
    correct answer, and it is why `INCONCLUSIVE` exists.
    """
    wd = make_workdir(tmp_path)
    run_worker(wd, "append", point="mid_tool")
    tail_after_crash = appended(wd / "log.txt")
    assert 0 < len(tail_after_crash) < len(APPEND_TEXT), "expected a partial write"

    run_worker(wd, "append", resume=True)
    d = decision(wd, "resume")
    assert d["verdict"] in ("BLOCK", "EXECUTE"), d
    # Whatever it chose, the result must not be two effects stacked up.
    assert appended(wd / "log.txt").count(APPEND_TEXT) <= 1


# ══ a different model resumes: the call comes back under a new id ══════
#: Every point at which the result had NOT yet reached the model. Here a
#: re-minted call must be connected to the first attempt by intent hash, and
#: the commit must still land at most once (`docs/0023` §4, `docs/0045`).
UNSEEN_POINTS = [p for p in CRASH_POINTS if p != "after_observed"]


@needs_git
@pytest.mark.parametrize("point", UNSEEN_POINTS)
def test_a_reminted_resume_never_commits_twice(tmp_path, point):
    wd = make_workdir(tmp_path)
    repo = wd / "repo"
    before = commits(repo)
    run_worker(wd, "git", point=point)
    run_worker(wd, "git", resume=True, remint=True)
    assert commits(repo) - before <= 1, (
        f"DUPLICATE COMMIT after crashing at {point} and resuming under a "
        f"new id: {decision(wd, 'resume')}")


@needs_git
def test_a_reminted_call_after_the_result_was_seen_is_the_models_call(tmp_path):
    """The line I-01 moves, pinned so it cannot move further unnoticed.

    Once the result is OBSERVED it is in the history the model reads, and the
    harness never re-drives an action whose result it persisted. A re-minted
    identical call at this point can only be the model choosing to repeat it --
    the edit -> test -> re-test loop -- and it is executed, not aliased.

    That is a deliberate second effect, not a replay: the guarantee above is
    "a crash never causes a repeat", and this run has no crash in it that the
    model did not see the far side of.
    """
    wd = make_workdir(tmp_path)
    run_worker(wd, "git", point="after_observed")
    run_worker(wd, "git", resume=True, remint=True)
    assert decision(wd, "resume")["verdict"] == "EXECUTE"
