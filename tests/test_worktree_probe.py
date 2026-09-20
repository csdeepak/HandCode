r"""Per-worker `git worktree` isolation restores correct probe verdicts.

`docs/0038` §4.2/§4.4, `research/phase-10-2-multiagent-cost-and-safety.md`
V15/V17/V18. The bug this guards against, stated once:

    A single shared workspace has one HEAD. If agent B commits while agent A
    is mid-effect, A's own probe reads HEAD-moved and reports `LANDED` for a
    commit that never ran -- silently dropping A's effect and recording it as
    `COMMITTED` (V15, and the mechanism behind `docs/0038` §3's batch bug in
    miniature).

`git worktree` gives each worker its own `HEAD`
(`.git/worktrees/<name>/HEAD`) over one shared object store, so a sibling's
commit structurally cannot move another worktree's HEAD -- not because
`GitProbe` was taught about siblings, but because the world it fingerprints is
now actually private. `--show-toplevel` also resolves per-worktree, so the
`docs/0019` toplevel guard distinguishes workers as a second, independent
signal. Verified here as evidence for a future multi-agent design, NOT as a
claim that `agentctl` runs multi-agent today -- it does not (`docs/0038` §4).

No LLM, no network, no cost: real `git` subprocesses against a real
repository, same style as `tests/test_reconcile.py`.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from agentctl.kernel.reconcile import GitProbe
from agentctl.kernel.reconcile.base import DID_NOT_LAND, LANDED

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)


def head(cwd) -> str:
    return git(cwd, "rev-parse", "HEAD").stdout.strip()


def commit_count(cwd) -> int:
    r = git(cwd, "rev-list", "--count", "HEAD")
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else 0


@pytest.fixture
def repo(tmp_path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "initial")
    return r


def add_worktree(repo: Path, tmp_path: Path, name: str, branch: str) -> Path:
    path = tmp_path / name
    result = git(repo, "worktree", "add", str(path), "-b", branch, "-q")
    assert result.returncode == 0, f"git worktree add failed: {result.stderr}"
    return path


def commit_call(cwd, message="c"):
    from agentctl.kernel.ledger.models import ToolCall

    return ToolCall("tc_1", "conv_1", "turn_1", "execute_bash",
                    {"command": f"git commit -m {message}", "cwd": str(cwd)})


# ══ V17: the probe is right in a worktree where it was wrong in a shared repo ══
@needs_git
def test_probe_is_not_fooled_by_a_siblings_commit_in_another_worktree(repo, tmp_path):
    """The exact shape of V15's bug, with the fix applied.

    In a single shared repo, a sibling's commit moves the one shared HEAD and
    the probe misreads it as our own (that IS the multi-agent hazard `0038`
    §4.2 names). In separate worktrees, HEAD is per-worktree, so this must
    resolve to DID_NOT_LAND -- not because the probe learned anything, but
    because there is no longer a shared HEAD to misread.
    """
    worker_a = add_worktree(repo, tmp_path, "worker_a", "branch-a")
    worker_b = add_worktree(repo, tmp_path, "worker_b", "branch-b")

    probe_a = GitProbe(worker_a)
    pre = probe_a.capture(commit_call(worker_a))
    assert pre is not None
    head_before = head(worker_a)

    # A sibling worker commits in ITS OWN worktree, sharing only the .git.
    (worker_b / "b.txt").write_text("from b\n", encoding="utf-8")
    r = git(worker_b, "add", "-A")
    assert r.returncode == 0
    r = git(worker_b, "commit", "-qm", "b's commit")
    assert r.returncode == 0

    # A's own worktree is untouched: HEAD did not move.
    assert head(worker_a) == head_before, (
        "a sibling worktree's commit must not move this worktree's HEAD -- "
        "if it did, worktree isolation is not doing its job"
    )

    class _Record:
        def __init__(self, pre_state):
            import json
            self.pre_state = json.dumps(pre_state)

    verdict = probe_a.probe(commit_call(worker_a), _Record(pre))
    assert verdict == DID_NOT_LAND, (
        f"a sibling's commit in another worktree was misread as our own "
        f"effect landing: {verdict}. This is V15's bug back again."
    )


@needs_git
def test_probe_still_says_landed_for_the_workers_own_commit(repo, tmp_path):
    """The positive case, so the test above cannot be satisfied by a probe
    that has simply stopped detecting LANDED at all."""
    worker_a = add_worktree(repo, tmp_path, "worker_a", "branch-a")

    probe_a = GitProbe(worker_a)
    pre = probe_a.capture(commit_call(worker_a))
    assert pre is not None

    (worker_a / "a.txt").write_text("from a\n", encoding="utf-8")
    git(worker_a, "add", "-A")
    r = git(worker_a, "commit", "-qm", "a's own commit")
    assert r.returncode == 0

    class _Record:
        def __init__(self, pre_state):
            import json
            self.pre_state = json.dumps(pre_state)

    verdict = probe_a.probe(commit_call(worker_a), _Record(pre))
    assert verdict == LANDED


@needs_git
def test_worktree_toplevel_distinguishes_workers(repo, tmp_path):
    """`docs/0019`'s toplevel guard, exercised across worktrees: each worker's
    `--show-toplevel` must resolve to ITS OWN worktree, not the shared repo
    and not each other's -- the second, independent signal V17 measured."""
    worker_a = add_worktree(repo, tmp_path, "worker_a", "branch-a")
    worker_b = add_worktree(repo, tmp_path, "worker_b", "branch-b")

    top_a = git(worker_a, "rev-parse", "--show-toplevel").stdout.strip()
    top_b = git(worker_b, "rev-parse", "--show-toplevel").stdout.strip()

    assert Path(top_a).resolve() == worker_a.resolve()
    assert Path(top_b).resolve() == worker_b.resolve()
    assert top_a != top_b


# ══ V18: concurrent commits across worktrees do not fail ══════════════════
@needs_git
def test_concurrent_commits_across_worktrees_do_not_fail(repo, tmp_path):
    """Reduced from the research experiment's 3 worktrees x 40 commits (120
    total, 0 failures on Windows) to 3 x 15 (45 total) for CI speed. Same
    property -- real concurrent `git commit` subprocesses against one shared
    `.git` never corrupt or fail -- at a smaller, faster magnitude. The
    120-commit run is the evidence and lives in
    `research/phase-10-2-multiagent-cost-and-safety.md` V18; this is the
    regression pin, not a re-run of the experiment.
    """
    n_workers = 3
    n_commits = 15

    worktrees = [add_worktree(repo, tmp_path, f"worker_{i}", f"branch-{i}")
                for i in range(n_workers)]

    errors: list[str] = []
    errors_lock = threading.Lock()

    def hammer(wt: Path, idx: int) -> None:
        for j in range(n_commits):
            (wt / "log.txt").write_text(f"{idx}-{j}\n", encoding="utf-8")
            r_add = git(wt, "add", "-A")
            r_commit = git(wt, "commit", "-qm", f"worker {idx} commit {j}")
            if r_add.returncode != 0 or r_commit.returncode != 0:
                with errors_lock:
                    errors.append(
                        f"worker {idx} commit {j}: add rc={r_add.returncode} "
                        f"{r_add.stderr!r} commit rc={r_commit.returncode} "
                        f"{r_commit.stderr!r}"
                    )

    threads = [threading.Thread(target=hammer, args=(wt, i))
              for i, wt in enumerate(worktrees)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)
        assert not t.is_alive(), "a worker thread hung"

    assert errors == [], f"{len(errors)} failure(s) out of {n_workers * n_commits}:\n" + "\n".join(errors)

    for wt in worktrees:
        # +1 for the initial commit shared from the main worktree.
        assert commit_count(wt) == n_commits + 1
