r"""A subagent that cannot produce an effect.

`docs/0038` §4 skipped multi-agent because four correctness mechanisms assume
a single writer, not because of cost. A read-only subagent sidesteps all four
by having nothing to record — which means the read-only property is not a
convenience here, it is the entire safety argument. These tests exist to stop
it being relaxed by someone who reads `tools: [read_file]` as a default rather
than as a boundary.

The enforcement is deliberately doubled (`subagent.py` module docstring):
`validate()` refuses a bad definition, AND the tool list handed to the agent is
built from a constant rather than from the definition. So there is a test for
the check and a separate test for the mechanism, because a property that
depends on one function returning correctly is one refactor from gone.
"""
import pytest

from agentctl.runtime import subagent
from agentctl.runtime.subagent import (
    READ_ONLY_TOOLS, NotReadOnly, discover, rejection, validate,
)

pytest.importorskip("openhands.sdk.subagent.schema")

from openhands.sdk.subagent.schema import AgentDefinition  # noqa: E402


def defn(**kw) -> AgentDefinition:
    kw.setdefault("name", "reviewer")
    kw.setdefault("tools", ["read_file"])
    return AgentDefinition(**kw)


# ══ the boundary ═════════════════════════════════════════════════════
def test_a_read_only_definition_is_accepted():
    validate(defn())


@pytest.mark.parametrize("tool", ["execute_bash", "write_file", "anything_else"])
def test_any_tool_that_can_change_the_world_is_refused(tool):
    with pytest.raises(NotReadOnly, match=tool):
        validate(defn(tools=["read_file", tool]))


def test_a_shell_is_refused_even_though_the_matrix_classifies_commands():
    """`execute_bash` is not a close call.

    The capability matrix classifies individual commands, but it is regex over
    a command string and `python -c "..."` is opaque to it by construction.
    Admitting a shell would make this module's safety argument depend on that
    classifier being complete, which it is not claimed to be.
    """
    with pytest.raises(NotReadOnly):
        validate(defn(tools=["execute_bash"]))


def test_mcp_servers_are_refused_outright():
    """An MCP server is a tool surface nothing here can inspect."""
    d = defn()
    d.mcp_config = {"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]}}
    with pytest.raises(NotReadOnly, match="MCP"):
        validate(d)


def test_the_allowlist_is_exactly_read_file():
    """If this changes, the safety argument changes with it."""
    assert READ_ONLY_TOOLS == frozenset({"read_file"})


# ══ the mechanism, not just the check ════════════════════════════════
def test_the_tool_list_comes_from_the_constant_not_the_definition(monkeypatch):
    """Belt and braces: even a definition that slipped past validation gets
    only read tools, because `run` never passes `definition.tools` through."""
    seen = {}

    def fake_build_agent(llm, tools):
        seen["tools"] = list(tools)
        raise RuntimeError("stop here -- we only wanted the tool list")

    from agentctl.runtime import runner
    monkeypatch.setattr(runner, "_build_agent", fake_build_agent)
    monkeypatch.setattr(subagent, "validate", lambda d: None)  # bypass the check

    sneaky = defn(tools=["read_file", "execute_bash", "write_file"])
    with pytest.raises(RuntimeError, match="stop here"):
        subagent.run(sneaky, "read something", model="openrouter/x",
                     api_key="k")

    assert seen["tools"] == sorted(READ_ONLY_TOOLS), \
        "run() passed the definition's tools through instead of the allowlist"


# ══ discovery ════════════════════════════════════════════════════════
def write(tmp_path, name: str, body: str):
    d = tmp_path / ".agentctl" / "agents"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(body, encoding="utf-8")


def test_discovery_finds_a_definition(tmp_path):
    write(tmp_path, "reviewer",
          "---\nname: reviewer\ntools:\n  - read_file\n---\n\nRead things.\n")
    found = discover(tmp_path)
    assert [d.name for d in found] == ["reviewer"]
    assert rejection(found[0]) is None


def test_a_bad_definition_is_surfaced_not_silently_skipped(tmp_path):
    """One bad file must not hide the good ones, and must not hide itself."""
    write(tmp_path, "reviewer",
          "---\nname: reviewer\ntools:\n  - read_file\n---\n\nok\n")
    write(tmp_path, "shell",
          "---\nname: shell\ntools:\n  - execute_bash\n---\n\nnope\n")

    by_name = {d.name: d for d in discover(tmp_path)}
    assert set(by_name) == {"reviewer", "shell"}, "a bad file hid the good one"
    assert rejection(by_name["reviewer"]) is None
    assert "execute_bash" in (rejection(by_name["shell"]) or "")


def test_no_agents_directory_is_not_an_error(tmp_path):
    assert discover(tmp_path) == []


# ══ the transcript ═══════════════════════════════════════════════════
class _Part:
    def __init__(self, text): self.text = text


class _Msg:
    def __init__(self, text, role): self.content = [_Part(text)]; self.role = role


class _Ev:
    def __init__(self, text, source="agent", role="assistant"):
        self.llm_message = _Msg(text, role)
        self.source = source


class _Conv:
    def __init__(self, events):
        self.state = type("S", (), {"events": events})()


def test_the_last_thing_it_said_is_returned():
    conv = _Conv([_Ev("first"), _Ev("second")])
    assert subagent._final_text(conv) == "second"


def test_the_users_own_prompt_is_never_returned_as_an_answer():
    """The bug a live run found.

    Taking the newest event with any content at all handed back the prompt,
    which reads like an answer and would have been spliced into a parent
    agent's context as though the subagent had reported something.
    """
    conv = _Conv([_Ev("the real answer"),
                  _Ev("read gate.py and tell me...", source="user", role="user")])
    assert subagent._final_text(conv) == "the real answer"


def test_persisted_dict_content_is_read_too():
    """In memory a part has `.text`; reloaded from disk it is a dict."""
    ev = _Ev("x")
    ev.llm_message = {"role": "assistant",
                      "content": [{"type": "text", "text": "from disk"}]}
    assert subagent._final_text(_Conv([ev])) == "from disk"


def test_finding_nothing_is_distinguishable_from_never_running():
    """A caller splicing this into a parent's context must be able to tell."""
    assert "no readable transcript" in subagent._final_text(_Conv([]))


# ══ two bugs a concurrency experiment found ══════════════════════════
def test_registering_plain_tools_never_un_gates_seam_c():
    """The silent gate bypass.

    Seam C registers GATED tools under the same names as the plain ones, in
    the SDK's process-global registry. `register_tool` replaces a duplicate
    with only a log warning — its own source carries a TODO saying it should
    raise. So a later plain registration un-gates every effect the guard had
    wrapped, and nothing fails to say so.
    """
    from openhands.sdk.tool import list_registered_tools, register_tool

    from agentctl.runtime import tools as rt

    class Sentinel(rt.ReadFileTool):
        """Stands in for the gated version Seam C installs."""

    register_tool("read_file", Sentinel)
    from openhands.sdk.tool.registry import get_tool_module_qualnames
    before = get_tool_module_qualnames().get("read_file")

    newly = rt.register_all(overwrite=False)

    assert "read_file" not in newly, "clobbered an existing registration"
    assert get_tool_module_qualnames().get("read_file") == before, \
        "a plain re-registration replaced the gated tool -- gate bypassed"
    assert "read_file" in list_registered_tools()


def test_the_subagent_workspace_does_not_leak_back_to_the_parent(
        monkeypatch, tmp_path):
    """The scoped workspace must be restored even when the run raises.

    The env-var version leaked both ways: concurrently a subagent scoped to
    one workspace read another's file and reported it, and sequentially the
    parent's next `read_file` resolved against the subagent's workspace.

    `_build_agent` is where this bites — it raises *before* the conversation
    exists, on a bad model id or a missing key, which is exactly the path an
    inner `try` around `conv.run()` would miss.
    """
    from agentctl.runtime import runner
    from agentctl.runtime import tools as rt

    def boom(llm, tools):
        raise RuntimeError("the run failed after the workspace was scoped")

    monkeypatch.setattr(runner, "_build_agent", boom)

    # A KNOWN sentinel, not the ambient value. The first version of this test
    # compared against whatever was already set and passed because an earlier
    # test in this file leaked the same path — green, and testing nothing
    # (`docs/0024`).
    sentinel = rt._scoped_workspace.set("/parent/workspace")
    try:
        with pytest.raises(RuntimeError, match="the run failed"):
            subagent.run(defn(), "anything", workspace=tmp_path,
                         model="openrouter/x", api_key="k")
        assert rt._scoped_workspace.get() == "/parent/workspace", \
            "a failed subagent left its own workspace scoped for the parent"
    finally:
        rt._scoped_workspace.reset(sentinel)
