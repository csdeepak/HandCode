"""The workspace's `.agentctl/` must never show up in the user's `git status`.

Phase 0 (`docs/0044` N11): after one run, `git status` in the user's own
repository listed `?? .agentctl/` -- a ledger and every conversation, with task
text and command output, one `git add -A` from a commit.

Asserted through real git, not by reading the file back: a `.gitignore` that
parses and ignores nothing is exactly the kind of check this project keeps
writing (`docs/0039`).
"""
import subprocess

from agentctl.runtime.runner import STATE_GITIGNORE, state_dir


def _status(repo) -> list[str]:
    out = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=repo,
                         capture_output=True, text=True, check=True).stdout
    return [line[3:] for line in out.splitlines()]


def _repo(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def test_runtime_state_is_invisible_to_git(tmp_path):
    repo = _repo(tmp_path)
    d = state_dir(repo)
    (d / "ledger.db").write_bytes(b"x")
    (d / "conversations" / "abc").mkdir(parents=True)
    (d / "conversations" / "abc" / "event.json").write_text("{}")
    assert _status(repo) == []


def test_subagent_definitions_stay_visible(tmp_path):
    """The user writes these; they may belong in the repository."""
    repo = _repo(tmp_path)
    d = state_dir(repo)
    (d / "agents").mkdir()
    (d / "agents" / "reviewer.md").write_text("---\nname: reviewer\n---\n")
    (d / "ledger.db").write_bytes(b"x")
    assert _status(repo) == [".agentctl/agents/reviewer.md"]


def test_an_existing_gitignore_is_left_alone(tmp_path):
    d = tmp_path / ".agentctl"
    d.mkdir()
    (d / ".gitignore").write_text("mine\n")
    state_dir(tmp_path)
    assert (d / ".gitignore").read_text() == "mine\n"


def test_it_is_idempotent(tmp_path):
    state_dir(tmp_path)
    state_dir(tmp_path)
    assert (tmp_path / ".agentctl" / ".gitignore").read_text() == STATE_GITIGNORE
