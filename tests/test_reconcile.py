"""Reconciliation probes against a real git repo and real files.

These are the tests that matter for M4: the probe must be right about whether
an effect landed, and must say INCONCLUSIVE rather than guess.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from agentctl.kernel.ledger.models import EffectClass, ToolCall
from agentctl.kernel.ledger.store import LedgerStore
from agentctl.kernel.reconcile import FileAppendProbe, GitProbe, default_registry
from agentctl.kernel.reconcile.base import DID_NOT_LAND, INCONCLUSIVE, LANDED

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("one\n", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "initial")
    return r


@pytest.fixture
def store(tmp_path):
    with LedgerStore(tmp_path / "l.db") as s:
        yield s


def bash_call(cmd, cwd, cid="tc_1"):
    return ToolCall(cid, "conv", "turn", "execute_bash",
                    {"command": cmd, "cwd": str(cwd)})


def _record(store, call, pre):
    import json
    return store.write_intent(call, EffectClass.NON_IDEMPOTENT_WRITE, 1,
                              json.dumps(pre) if pre else None)


# ══ GitProbe ═════════════════════════════════════════════════════════
@needs_git
def test_git_probe_handles_only_head_moving_commands(repo):
    p = GitProbe(repo)
    assert p.handles(bash_call("git commit -m x", repo))
    assert p.handles(bash_call("git merge feature", repo))
    assert not p.handles(bash_call("git status", repo))
    assert not p.handles(bash_call("ls -la", repo))
    assert not p.handles(bash_call("git push origin main", repo)), \
        "push is EXTERNAL -- a local probe cannot see the remote"


@needs_git
def test_git_landed_when_head_moved(repo, store):
    p, call = GitProbe(repo), bash_call("git commit -m work", repo)
    rec = _record(store, call, p.capture(call))

    (repo / "b.txt").write_text("two\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "the crashed agent's commit")

    assert p.probe(call, store.lookup(rec.tool_call_id)) == LANDED


@needs_git
def test_git_did_not_land_when_nothing_changed(repo, store):
    p, call = GitProbe(repo), bash_call("git commit -m work", repo)
    rec = _record(store, call, p.capture(call))
    assert p.probe(call, store.lookup(rec.tool_call_id)) == DID_NOT_LAND


@needs_git
def test_git_inconclusive_when_tree_moved_but_head_did_not(repo, store):
    """Something happened that was not a commit. Never guess."""
    p, call = GitProbe(repo), bash_call("git commit -m work", repo)
    rec = _record(store, call, p.capture(call))
    (repo / "unexpected.txt").write_text("someone else\n", encoding="utf-8")
    assert p.probe(call, store.lookup(rec.tool_call_id)) == INCONCLUSIVE


@needs_git
def test_git_probe_survives_a_repo_with_no_commits(tmp_path, store):
    r = tmp_path / "empty"; r.mkdir(); git(r, "init", "-q")
    git(r, "config", "user.email", "t@e.com"); git(r, "config", "user.name", "t")
    p, call = GitProbe(r), bash_call("git commit -m first", r)
    pre = p.capture(call)
    assert pre is not None and pre["head"] == "__NO_COMMITS__"

    rec = _record(store, call, pre)
    (r / "x.txt").write_text("x", encoding="utf-8")
    git(r, "add", "-A"); git(r, "commit", "-qm", "first")
    assert p.probe(call, store.lookup(rec.tool_call_id)) == LANDED


@needs_git
def test_git_inconclusive_without_a_fingerprint(repo, store):
    p, call = GitProbe(repo), bash_call("git commit -m x", repo)
    rec = _record(store, call, None)
    assert p.probe(call, store.lookup(rec.tool_call_id)) == INCONCLUSIVE


@needs_git
def test_git_records_the_repo_it_attached_to(repo):
    """A workspace nested in a larger repo resolves to the ANCESTOR.

    Found while writing these tests: the temp dir sits inside an enclosing git
    repo, so capture() succeeded against a repo the agent never touched. The
    fingerprint now records the toplevel so probe() can refuse a mismatch.
    """
    pre = GitProbe(repo).capture(bash_call("git commit -m x", repo))
    assert pre is not None
    assert Path(pre["toplevel"]).resolve() == repo.resolve()


@needs_git
def test_git_inconclusive_if_the_repo_changed_underneath(repo, tmp_path, store):
    p, call = GitProbe(repo), bash_call("git commit -m x", repo)
    pre = p.capture(call)
    pre["toplevel"] = str(tmp_path / "some" / "other" / "repo")   # simulate drift
    rec = _record(store, call, pre)
    assert p.probe(call, store.lookup(rec.tool_call_id)) == INCONCLUSIVE


# ══ FileAppendProbe ══════════════════════════════════════════════════
def test_file_unchanged_means_it_did_not_land(tmp_path, store):
    f = tmp_path / "log.txt"; f.write_text("one\n", encoding="utf-8")
    p = FileAppendProbe()
    call = ToolCall("tc_f1", "c", "t", "append", {"path": str(f), "content": "two\n"})
    rec = _record(store, call, p.capture(call))
    assert p.probe(call, store.lookup(rec.tool_call_id)) == DID_NOT_LAND


def test_verified_append_is_proof_not_inference(tmp_path, store):
    f = tmp_path / "log.txt"; f.write_text("one\n", encoding="utf-8")
    p = FileAppendProbe()
    call = ToolCall("tc_f2", "c", "t", "append", {"path": str(f), "content": "two\n"})
    pre = p.capture(call)
    assert pre["appended"] == "two\n", "the append must be recorded for verification"

    rec = _record(store, call, pre)
    with f.open("a", encoding="utf-8") as fh:
        fh.write("two\n")
    assert p.probe(call, store.lookup(rec.tool_call_id)) == LANDED


def test_unexpected_change_is_inconclusive_not_landed(tmp_path, store):
    """We knew what it should look like and it does not. Do not guess."""
    f = tmp_path / "log.txt"; f.write_text("one\n", encoding="utf-8")
    p = FileAppendProbe()
    call = ToolCall("tc_f3", "c", "t", "append", {"path": str(f), "content": "two\n"})
    rec = _record(store, call, p.capture(call))
    f.write_text("something else entirely\n", encoding="utf-8")
    assert p.probe(call, store.lookup(rec.tool_call_id)) == INCONCLUSIVE


def test_file_created_where_none_existed(tmp_path, store):
    f = tmp_path / "new.txt"
    p = FileAppendProbe()
    call = ToolCall("tc_f4", "c", "t", "append", {"path": str(f), "content": "hi\n"})
    rec = _record(store, call, p.capture(call))
    f.write_text("hi\n", encoding="utf-8")
    assert p.probe(call, store.lookup(rec.tool_call_id)) == LANDED


# ══ registry ═════════════════════════════════════════════════════════
@needs_git
def test_registry_prefers_the_named_probe(repo):
    reg = default_registry(repo)
    call = bash_call("git commit -m x", repo)
    assert reg.for_call(call, "git").name == "git"


def test_registry_returns_none_when_nothing_handles_the_call(tmp_path):
    reg = default_registry(tmp_path)
    call = ToolCall("tc", "c", "t", "send_email", {"to": "a@b.c"})
    assert reg.for_call(call, None) is None
