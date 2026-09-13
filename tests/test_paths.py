r"""Writes that land outside the workspace. `docs/0027`.

The motivating case: `echo x > ~/.bashrc` classifies `IDEMPOTENT_WRITE`, which
is correct -- rewriting a whole file IS idempotent -- and so no confirmation
fired. The risk was never the operation. It was the destination.

Two halves are tested, and the second matters as much as the first:

* every escaping write is reported (or the mechanism is decorative)
* no ORDINARY write is reported (or the operator learns to answer `y` without
  reading, which disables the gate in a way nothing can observe)
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentctl.kernel.ledger.models import ToolCall
from agentctl.kernel.paths import escapes, escaping_writes, write_targets


def call(tool_name: str = "execute_bash", **args) -> ToolCall:
    return ToolCall(tool_call_id="t", conversation_id="c", turn_id="t1",
                    tool_name=tool_name, args=args)


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    (tmp_path / "sub").mkdir()
    return tmp_path


# ── the thing that started this ────────────────────────────────────────
def test_the_bashrc_case(ws):
    """`~` must be expanded, or it reads as a relative path safely inside."""
    assert escaping_writes(call(command="echo x > ~/.bashrc"), ws)


def test_a_home_relative_path_is_not_mistaken_for_a_workspace_path(ws):
    # Without expanduser, "~/.bashrc" joins onto the workspace and looks fine.
    assert escapes("~/.bashrc", ws)
    assert not escapes(".bashrc", ws)


# ── escapes ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("command", [
    "echo x > ~/.bashrc",
    "cat secrets.env > /tmp/stolen",
    "cp notes.txt /tmp/copy",
    "rm ../../important",
    "echo hi && tee /etc/motd",
    "mv report.md ~/Desktop/report.md",
    "touch /etc/cron.d/backdoor",
    "ls > ../outside.txt",
])
def test_escaping_writes_are_reported(ws, command):
    assert escaping_writes(call(command=command), ws), command


@pytest.mark.parametrize("path", [
    "/etc/passwd", "../escape.txt", "~/.ssh/authorized_keys",
    "../../../../etc/hosts",
])
def test_structured_tools_declare_their_path(ws, path):
    assert escaping_writes(call("write_file", path=path, content="x"), ws)


# ── does NOT escape: the half that keeps prompts meaningful ────────────
@pytest.mark.parametrize("command", [
    "ls -la",
    "cat f.txt | grep x",
    "cat a.txt > b.txt",
    "echo x >> notes.md",
    "mkdir -p build",
    "rm sub/tmp.txt",
    "git status",
    "ls 2>&1",                      # a file-descriptor redirect writes no file
    "grep secret /etc/shadow",      # a READ outside the root: out of scope
])
def test_ordinary_work_is_not_flagged(ws, command):
    assert escaping_writes(call(command=command), ws) == [], command


def test_a_workspace_relative_write_is_fine(ws):
    assert escaping_writes(call("write_file", path="sub/notes.md"), ws) == []


def test_no_root_configured_means_no_opinion(ws):
    """Embedders that never pass a workspace must not start getting prompts."""
    assert escaping_writes(call(command="rm -rf /"), None) == []


# ── extraction details ─────────────────────────────────────────────────
def test_redirect_targets_are_found_per_segment():
    t = write_targets(call(command="echo a > one.txt && echo b >> two.txt"))
    assert "one.txt" in t and "two.txt" in t


def test_flags_are_not_paths():
    t = write_targets(call(command="rm -rf -- build"))
    assert "-rf" not in t and "--" not in t
    assert "build" in t


def test_targets_are_deduplicated():
    t = write_targets(call(command="touch x.txt && touch x.txt"))
    assert t.count("x.txt") == 1


def test_resolution_is_lexical_not_symlink_following(ws, tmp_path):
    """`Path.resolve()` would follow a link OUT of the workspace back IN.

    Lexical normalisation cannot be tricked that way. The cost is that a benign
    symlink inside the workspace reads as an escape, which is the safe error.
    """
    outside = tmp_path.parent / "outside_target"
    outside.mkdir(exist_ok=True)
    # Lexically inside, whatever it points at.
    assert not escapes(str(ws / "link" / "f.txt"), ws)
    # Lexically outside, and normpath collapses the traversal.
    assert escapes(str(ws / ".." / "f.txt"), ws)


def test_absolute_path_inside_the_workspace_is_fine(ws):
    assert not escapes(str(ws / "sub" / "a.txt"), ws)


def test_a_sibling_directory_with_a_shared_prefix_does_not_count_as_inside(tmp_path):
    """`/work` and `/workspace-evil` share a string prefix but not a path.

    A `str.startswith` implementation gets this wrong, which is why the check
    is `PurePath.relative_to`.
    """
    root = tmp_path / "work"
    root.mkdir()
    (tmp_path / "work-evil").mkdir()
    assert escapes(str(tmp_path / "work-evil" / "f.txt"), root)


# ── the mechanism the operator actually meets ──────────────────────────
class _FakeGate:
    def __init__(self, decision):
        self._d = decision
        self.guard = lambda call: self._d


class _FakeGuard:
    def __init__(self, decision):
        self.gate = _FakeGate(decision)


def _wire(decision, ws, answer, monkeypatch):
    """Install the confirmation wrapper and answer its prompt with `answer`."""
    from agentctl.runtime.runner import _install_confirmation
    monkeypatch.setattr("builtins.input", lambda *_: answer)
    guard = _FakeGuard(decision)
    _install_confirmation(guard, verbose=False, workspace=ws)
    return guard.gate.guard


def test_an_escaping_write_actually_prompts_and_can_be_refused(ws, monkeypatch):
    """The end-to-end check: does the operator get asked, and does `n` stop it?"""
    from agentctl.kernel.ledger.models import EffectClass, GateDecision, Verdict

    allow = GateDecision(Verdict.EXECUTE, EffectClass.IDEMPOTENT_WRITE)
    guarded = _wire(allow, ws, "n", monkeypatch)

    refused = guarded(call(command="echo x > ~/.bashrc"))
    assert refused.verdict is Verdict.BLOCK
    assert "operator" in refused.reason
    # the class is NOT escalated -- this is an authorization decision, and the
    # ledger must still see an ordinary idempotent write (docs/0027)
    assert refused.effect_class is EffectClass.IDEMPOTENT_WRITE


def test_saying_yes_lets_it_through(ws, monkeypatch):
    from agentctl.kernel.ledger.models import EffectClass, GateDecision, Verdict

    allow = GateDecision(Verdict.EXECUTE, EffectClass.IDEMPOTENT_WRITE)
    guarded = _wire(allow, ws, "y", monkeypatch)
    assert guarded(call(command="echo x > ~/.bashrc")).verdict is Verdict.EXECUTE


def test_ordinary_work_is_never_interrupted(ws, monkeypatch):
    """If this prompts, operators learn to answer `y` without reading."""
    from agentctl.kernel.ledger.models import EffectClass, GateDecision, Verdict

    allow = GateDecision(Verdict.EXECUTE, EffectClass.IDEMPOTENT_WRITE)
    def _explode(*_):
        raise AssertionError("prompted for an ordinary in-workspace write")
    monkeypatch.setattr("builtins.input", _explode)

    from agentctl.runtime.runner import _install_confirmation
    guard = _FakeGuard(allow)
    _install_confirmation(guard, verbose=False, workspace=ws)
    assert guard.gate.guard(call(command="echo x > notes.md")).verdict is Verdict.EXECUTE


def test_a_blocked_decision_is_not_second_guessed(ws, monkeypatch):
    """Already blocked: do not ask the operator to confirm a refusal."""
    from agentctl.kernel.ledger.models import EffectClass, GateDecision, Verdict

    blocked = GateDecision(Verdict.BLOCK, EffectClass.DESTRUCTIVE, reason="ledger")
    def _explode(*_):
        raise AssertionError("prompted about an already-blocked call")
    monkeypatch.setattr("builtins.input", _explode)

    from agentctl.runtime.runner import _install_confirmation
    guard = _FakeGuard(blocked)
    _install_confirmation(guard, verbose=False, workspace=ws)
    assert guard.gate.guard(call(command="rm -rf /x")).verdict is Verdict.BLOCK


# ── source vs destination ──────────────────────────────────────────────
@pytest.mark.parametrize("command", [
    "cp /etc/hosts ./local",            # reads outside, writes inside
    "cp ~/template.md ./notes.md",
    "mv /tmp/download.zip ./archive.zip",
])
def test_copying_something_IN_is_not_an_escaping_write(ws, command):
    """Only the destination is written. Flagging the source is a false prompt.

    `cp` and friends take sources then one destination; collecting every
    operand would make `cp /etc/hosts ./local` look like an unauthorised write
    to /etc/hosts. A prompt that is wrong is worse than no prompt (`docs/0027`).
    """
    assert escaping_writes(call(command=command), ws) == [], command


@pytest.mark.parametrize("command", [
    "cp ./secret.txt /tmp/stolen",
    "mv ./report.md ~/Desktop/report.md",
])
def test_copying_something_OUT_still_is(ws, command):
    assert escaping_writes(call(command=command), ws), command


def test_rm_flags_every_operand_because_it_deletes_them_all(ws):
    t = write_targets(call(command="rm a.txt ../b.txt ../../c.txt"))
    assert t == ["a.txt", "../b.txt", "../../c.txt"]
