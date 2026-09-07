"""Capability matrix. docs/0012 §5.1.

execute_bash is the hard case: one tool name spanning every effect class.
Getting this table wrong is how the gate ends up protecting the wrong things.
"""
import pytest

from agentctl.kernel.classify import Classifier
from agentctl.kernel.ledger.models import EffectClass, ToolCall


@pytest.fixture(scope="module")
def clf():
    return Classifier()


def bash(cmd):
    return ToolCall("tc", "c", "t", "execute_bash", {"command": cmd})


@pytest.mark.parametrize("cmd,expected", [
    ("ls -la",                       EffectClass.PURE_READ),
    ("cat README.md",                EffectClass.PURE_READ),
    ("git status",                   EffectClass.PURE_READ),
    ("git log --oneline",            EffectClass.PURE_READ),
    ("mkdir -p build/out",           EffectClass.IDEMPOTENT_WRITE),
    ("git commit -m 'x'",            EffectClass.NON_IDEMPOTENT_WRITE),
    ("git push origin main",         EffectClass.EXTERNAL),
    ("curl https://example.com",     EffectClass.EXTERNAL),
    ("echo hi >> log.txt",           EffectClass.NON_IDEMPOTENT_WRITE),
    ("rm -rf /tmp/x",                EffectClass.DESTRUCTIVE),
    ("git push --force origin main", EffectClass.DESTRUCTIVE),
    ("some_unknown_binary --go",     EffectClass.EXTERNAL),
])
def test_bash_classification(clf, cmd, expected):
    assert clf.classify(bash(cmd)) is expected


def test_destructive_beats_less_dangerous_matches(clf):
    """Ordering matters: rm -rf must not be caught by an earlier benign rule."""
    assert clf.classify(bash("ls && rm -rf /important")) is EffectClass.DESTRUCTIVE


def test_unknown_tool_defaults_to_external(clf):
    assert clf.classify(ToolCall("t", "c", "t", "wat", {})) is EffectClass.EXTERNAL


def test_named_tools(clf):
    assert clf.classify(ToolCall("t", "c", "t", "read_file", {})) is EffectClass.PURE_READ
    assert clf.classify(ToolCall("t", "c", "t", "write_file", {})) is EffectClass.IDEMPOTENT_WRITE


def test_sdk_suffix_stripping_is_tolerated(clf):
    """docs/0014 §3 C3 -- the SDK resolves read_file_tool to read_file."""
    assert clf.classify(ToolCall("t", "c", "t", "read_file_tool", {})) is EffectClass.PURE_READ


def test_mcp_tools_default_to_external(clf):
    assert clf.classify(ToolCall("t", "c", "t", "mcp__stripe__create_charge", {})) \
        is EffectClass.EXTERNAL


def test_declared_mcp_tool_is_honoured(clf):
    assert clf.classify(ToolCall("t", "c", "t", "mcp__filesystem__read_file", {})) \
        is EffectClass.PURE_READ


def test_probe_selection(clf):
    assert clf.probe_for(bash("git commit -m x")) == "git"
    assert clf.probe_for(bash("ls")) is None


def test_speculation_is_stricter_than_replay():
    """docs/0010 §6.4 -- a discarded speculative write still mutated the world."""
    assert EffectClass.IDEMPOTENT_WRITE.replay_safe
    assert not EffectClass.IDEMPOTENT_WRITE.speculation_safe
    assert EffectClass.PURE_READ.speculation_safe
