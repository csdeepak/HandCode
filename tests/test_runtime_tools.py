"""Runtime tools. `docs/0025`.

One test here matters more than the rest: no Observation subclass may define a
field named `content`. The base declares it as list[TextContent | ImageContent],
so a str shadow validates at construction and fails several components later,
during message assembly, with no reference to the field that caused it. It has
now bitten this project twice (docs/0018 §4, docs/0025).
"""
import pytest

pytest.importorskip("openhands.sdk", reason="SDK not installed")

from agentctl.runtime.tools import (
    BashObservation, ReadObservation, WriteObservation, TOOLS,
)

RESERVED = {"content"}


@pytest.mark.parametrize("obs", [BashObservation, ReadObservation, WriteObservation])
def test_no_observation_shadows_a_reserved_base_field(obs):
    own = set(obs.model_fields) - set(obs.__bases__[0].model_fields)
    clash = own & RESERVED
    assert not clash, (
        f"{obs.__name__} shadows {clash}; see the module docstring")


@pytest.mark.parametrize("obs,args", [
    (BashObservation, (0, "hello")),
    (ReadObservation, ("file body",)),
    (WriteObservation, ("written", 12)),
])
def test_the_model_actually_sees_the_output(obs, args):
    """The SDK reads `content` via `to_llm_content`, nothing else.

    An observation that stores its text in a custom field and exposes it via
    some other property renders as "[no text content]", and the agent concludes
    the tool returned nothing. That happened (docs/0025).
    """
    o = obs.make(*args)
    rendered = list(o.to_llm_content)
    assert rendered, f"{obs.__name__} renders empty -- the model sees nothing"
    text = "".join(getattr(b, "text", "") for b in rendered)
    assert text.strip(), f"{obs.__name__} produced no text"


def test_a_failing_command_is_marked_as_an_error():
    assert BashObservation.make(1, "boom").is_error
    assert not BashObservation.make(0, "fine").is_error


def test_the_three_tools_match_the_capability_matrix():
    """The tool names must be ones the classifier already knows."""
    from agentctl.kernel.classify import Classifier
    from agentctl.kernel.ledger.models import EffectClass, ToolCall

    clf = Classifier()
    assert clf.classify(ToolCall("t", "c", "t", "read_file", {})) is EffectClass.PURE_READ
    assert clf.classify(ToolCall("t", "c", "t", "write_file", {})) is EffectClass.IDEMPOTENT_WRITE
    assert clf.classify(ToolCall("t", "c", "t", "execute_bash",
                                 {"command": "rm -rf /"})) is EffectClass.DESTRUCTIVE
    assert set(TOOLS) == {"execute_bash", "read_file", "write_file"}


# ── the tool must run the shell it is named after (docs/0031 §9) ───────
def test_execute_bash_actually_runs_bash():
    """`shell=True` uses COMSPEC on Windows -- cmd.exe -- for a tool called
    `execute_bash`. A real run produced `<< was unexpected at this time.`
    from a heredoc five times, wrote nothing, and reported success."""
    import shutil

    from agentctl.runtime.tools import _shell

    if not (shutil.which("bash") or shutil.which("sh")):
        pytest.skip("no bash on this machine")
    argv = _shell()
    assert argv and argv[-1] == "-c"
    assert "bash" in argv[0].lower() or argv[0].lower().endswith("sh.exe") \
        or argv[0].endswith("/sh")


def test_a_heredoc_works(tmp_path, monkeypatch):
    """The exact command the model wrote, which cmd.exe rejected."""
    import shutil
    if not shutil.which("bash"):
        pytest.skip("no bash on this machine")
    monkeypatch.setenv("AGENTCTL_WORKSPACE", str(tmp_path))
    from agentctl.runtime.tools import BashAction, BashExecutor

    obs = BashExecutor()(BashAction(
        command="cat << 'EOF' > made.py\nprint('hi')\nEOF"))
    assert obs.exit_code == 0, obs.output
    assert (tmp_path / "made.py").read_text(encoding="utf-8") == "print('hi')\n"


def test_bash_syntax_the_classifier_assumes_actually_works(tmp_path, monkeypatch):
    """The matrix splits on `&&` `||` `;` `|` and matches `rm -rf`.

    Those are bash rules. Under cmd.exe the classifier would be guarding a
    shell nobody is running.
    """
    import shutil
    if not shutil.which("bash"):
        pytest.skip("no bash on this machine")
    monkeypatch.setenv("AGENTCTL_WORKSPACE", str(tmp_path))
    from agentctl.runtime.tools import BashAction, BashExecutor

    ex = BashExecutor()
    assert ex(BashAction(command="echo one && echo two")).output.splitlines() \
        == ["one", "two"]
    assert ex(BashAction(command="echo a; echo b")).output.splitlines() == ["a", "b"]
    assert "1" in ex(BashAction(command="echo hello | wc -l")).output


def test_a_failing_command_is_reported_as_an_error(tmp_path, monkeypatch):
    """`is_error` is what Seam B now reads to avoid committing a failure."""
    monkeypatch.setenv("AGENTCTL_WORKSPACE", str(tmp_path))
    from agentctl.runtime.tools import BashAction, BashExecutor

    obs = BashExecutor()(BashAction(command="exit 3"))
    assert obs.exit_code == 3 and obs.is_error is True
