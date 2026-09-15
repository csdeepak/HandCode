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


# ── line endings survive an edit (docs/0035) ───────────────────────────
@pytest.mark.parametrize("before,content,expect_crlf", [
    (b"a\r\nb\r\n", "a\nB\n",     True),    # CRLF file, model sends LF
    (b"a\r\nb\r\n", "a\r\nB\r\n", True),    # CRLF file, model sends CRLF
    (b"a\nb\n",     "a\nB\n",     False),   # LF file, model sends LF
    (b"a\nb\n",     "a\r\nB\r\n", False),   # LF file, model sends CRLF
    (b"a\r\nb\r\nc\n", "x\ny\n",  True),    # mixed: the dominant ending wins
])
def test_write_preserves_the_files_line_endings(tmp_path, monkeypatch,
                                                before, content, expect_crlf):
    """An 8-line change arrived as a 149-line diff on the first real edit.

    `write_file` wrote `\n` over a CRLF file, so every line counted as
    changed: unreviewable, and it pollutes history in any repo checked out on
    Windows.
    """
    monkeypatch.setenv("AGENTCTL_WORKSPACE", str(tmp_path))
    from agentctl.runtime.tools import WriteAction, WriteExecutor

    f = tmp_path / "f.txt"
    f.write_bytes(before)
    WriteExecutor()(WriteAction(path="f.txt", content=content))

    raw = f.read_bytes()
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    assert (crlf > 0 and lf == 0) is expect_crlf
    assert b"\r\r" not in raw, "normalise before converting, or CRLF doubles"


def test_a_new_file_gets_plain_lf(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCTL_WORKSPACE", str(tmp_path))
    from agentctl.runtime.tools import WriteAction, WriteExecutor

    WriteExecutor()(WriteAction(path="new.txt", content="x\ny\n"))
    assert (tmp_path / "new.txt").read_bytes() == b"x\ny\n"


def test_the_content_itself_is_unchanged(tmp_path, monkeypatch):
    """Only the endings may differ -- never the text."""
    monkeypatch.setenv("AGENTCTL_WORKSPACE", str(tmp_path))
    from agentctl.runtime.tools import WriteAction, WriteExecutor

    f = tmp_path / "f.txt"
    f.write_bytes(b"old\r\n")
    WriteExecutor()(WriteAction(path="f.txt", content="line one\nline two\n"))
    assert f.read_text(encoding="utf-8").splitlines() == ["line one", "line two"]


# ── the timeout must actually bound the call (docs/0036) ───────────────
def test_a_grandchild_cannot_hold_the_agent_open(tmp_path, monkeypatch):
    """The timeout was advisory, not enforced.

    `subprocess.run(timeout=...)` kills its direct child then drains the
    pipes -- but a grandchild still holds the write end, so the drain blocks
    until that grandchild exits by itself. Measured on a live run: a 3-second
    limit returned after 60.1 seconds, and a model that wrote
    `cd / && find . -name x` hung the agent for minutes.

    The guarantee is BOUNDED, not instant: some grandchildren survive
    `taskkill /T`, so the contract is `limit + grace`.
    """
    import shutil
    import time

    if not shutil.which("bash"):
        pytest.skip("no bash on this machine")
    monkeypatch.setenv("AGENTCTL_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("AGENTCTL_BASH_TIMEOUT", "3")
    from agentctl.runtime.tools import BashAction, BashExecutor

    started = time.time()
    obs = BashExecutor()(BashAction(command="sleep 60 | cat"))
    elapsed = time.time() - started

    assert obs.exit_code == 124 and obs.is_error
    assert "timed out" in obs.output
    assert elapsed < 30, f"took {elapsed:.1f}s -- the timeout is not enforced"


def test_a_plain_long_command_is_killed_promptly(tmp_path, monkeypatch):
    import shutil
    import time

    if not shutil.which("bash"):
        pytest.skip("no bash on this machine")
    monkeypatch.setenv("AGENTCTL_WORKSPACE", str(tmp_path))
    monkeypatch.setenv("AGENTCTL_BASH_TIMEOUT", "3")
    from agentctl.runtime.tools import BashAction, BashExecutor

    started = time.time()
    obs = BashExecutor()(BashAction(command="sleep 60"))
    assert obs.exit_code == 124
    assert time.time() - started < 12


def test_a_normal_command_is_not_slowed_down(tmp_path, monkeypatch):
    """The fix must not add latency to the 99% case."""
    import time

    monkeypatch.setenv("AGENTCTL_WORKSPACE", str(tmp_path))
    from agentctl.runtime.tools import BashAction, BashExecutor

    started = time.time()
    obs = BashExecutor()(BashAction(command="echo hello"))
    assert obs.exit_code == 0 and "hello" in obs.output
    assert time.time() - started < 10


# ── pointing at a proxy needs no client credential (docs/0036) ─────────
def test_a_base_url_without_a_key_supplies_a_placeholder(monkeypatch):
    """`agentctl proxy` prints "no key needed client-side". That was false.

    litellm rejects `api_key=None` with "Missing credentials ... set
    OPENAI_API_KEY", which sends you looking for a key you deliberately do not
    have -- the credentials live in the proxy.
    """
    import inspect

    from agentctl.runtime import runner

    src = inspect.getsource(runner.run)
    assert "elif base_url and not api_key:" in src
    assert "proxy-holds-the-credentials" in src


def test_a_missing_key_with_no_proxy_still_refuses(monkeypatch, tmp_path):
    """The placeholder must not paper over a genuinely missing key."""
    from agentctl.runtime.runner import run

    for var in ("OPENROUTER_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                "GEMINI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AGENTCTL_KEYS", str(tmp_path / "none.env"))

    with pytest.raises(SystemExit, match="No API key found"):
        run("x", tmp_path, model="anthropic/claude-sonnet-5", verbose=False)
