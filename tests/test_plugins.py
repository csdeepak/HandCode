r"""A plugin is admitted one capability at a time, and the refusals are counted.

`docs/0010` §9.1 gave plugins the only Partial BUILD in an otherwise SKIP-heavy
table, and §9.2 named the slice: packaging is the harness's job, *"policy over
what may be installed and reached is not."*

So the test that matters is not "can it read a manifest". It is that a plugin
carrying a shell-using agent, two MCP servers and a slash command yields
exactly one admitted agent and an itemised account of everything declined —
because a broker that silently dropped what it would not run would leave you
believing you had installed something you had not.
"""
import json

import pytest

pytest.importorskip("openhands.sdk.plugin.format.claude_code")

from agentctl.runtime.plugins import REFUSED, load  # noqa: E402

READ_ONLY = ("---\nname: skim\ndescription: Reads and summarises\n"
             "tools:\n  - read_file\n---\n\nSummarise what you read.\n")
WRITES = ("---\nname: fixer\ndescription: Edits files\n"
          "tools:\n  - write_file\n  - execute_bash\n---\n\nFix things.\n")


def plugin(tmp_path, *, agents=(), mcp=None, commands=()):
    d = tmp_path / "pack"
    (d / ".claude-plugin").mkdir(parents=True)
    (d / ".claude-plugin" / "plugin.json").write_text(json.dumps(
        {"name": "pack", "version": "1.0.0", "description": "a pack"}),
        encoding="utf-8")
    if agents:
        (d / "agents").mkdir()
        for name, body in agents:
            (d / "agents" / f"{name}.md").write_text(body, encoding="utf-8")
    if mcp:
        (d / ".mcp.json").write_text(json.dumps({"mcpServers": mcp}),
                                     encoding="utf-8")
    if commands:
        (d / "commands").mkdir()
        for name in commands:
            (d / "commands" / f"{name}.md").write_text(
                f"---\nname: {name}\ndescription: x\n---\nDo it.\n",
                encoding="utf-8")
    return d


# ══ the admission decision ═══════════════════════════════════════════
def test_a_read_only_agent_is_admitted(tmp_path):
    info = load(plugin(tmp_path, agents=[("skim", READ_ONLY)]))
    assert [a.name for a in info["admitted"]] == ["skim"]
    assert info["rejected"] == []


def test_an_agent_that_could_change_the_world_is_rejected(tmp_path):
    info = load(plugin(tmp_path, agents=[("fixer", WRITES)]))
    assert info["admitted"] == []
    assert len(info["rejected"]) == 1
    name, why = info["rejected"][0]
    assert name == "fixer"
    assert "execute_bash" in why


def test_one_bad_agent_does_not_block_a_good_one(tmp_path):
    """A plugin is partially admitted, not all-or-nothing."""
    info = load(plugin(tmp_path, agents=[("skim", READ_ONLY),
                                         ("fixer", WRITES)]))
    assert [a.name for a in info["admitted"]] == ["skim"]
    assert [n for n, _ in info["rejected"]] == ["fixer"]


# ══ the receipt, which is the point ══════════════════════════════════
def test_mcp_servers_are_counted_not_silently_dropped(tmp_path):
    d = plugin(tmp_path, agents=[("skim", READ_ONLY)],
               mcp={"fetch": {"command": "uvx", "args": ["mcp-server-fetch"]},
                    "db": {"command": "uvx", "args": ["mcp-server-db"]}})
    refused = {cap: n for cap, n, _ in load(d)["refused"]}
    assert refused.get("mcp_config") == 2, (
        "a plugin's MCP servers must be reported with a count -- 'declines "
        "MCP' is a policy, '2 declared' is a fact about this plugin")


def test_commands_are_counted_too(tmp_path):
    d = plugin(tmp_path, agents=[("skim", READ_ONLY)], commands=["review"])
    refused = {cap: n for cap, n, _ in load(d)["refused"]}
    assert refused.get("commands") == 1


def test_a_plugin_carrying_nothing_refusable_reports_nothing_refused(tmp_path):
    """The receipt must not cry wolf on a clean plugin."""
    info = load(plugin(tmp_path, agents=[("skim", READ_ONLY)]))
    assert info["refused"] == []


def test_every_refusal_carries_a_reason(tmp_path):
    d = plugin(tmp_path, agents=[("skim", READ_ONLY)],
               mcp={"fetch": {"command": "uvx", "args": []}},
               commands=["review"])
    for cap, _n, why in load(d)["refused"]:
        assert why and why == REFUSED[cap], f"{cap} refused without its reason"


# ══ nothing is installed or run ══════════════════════════════════════
def test_inspecting_a_plugin_runs_nothing(tmp_path):
    """`load` is the audit step. It must not start an agent or a server."""
    info = load(plugin(tmp_path, agents=[("skim", READ_ONLY)],
                       mcp={"fetch": {"command": "uvx", "args": []}}))
    assert "admitted" in info and "refused" in info
    # The admitted entry is a definition, not a running thing.
    assert not hasattr(info["admitted"][0], "run")


def test_a_missing_directory_is_reported_not_raised(tmp_path):
    info = load(tmp_path / "nope")
    assert "error" in info and "no such directory" in info["error"]
