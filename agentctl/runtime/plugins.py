r"""Claude Code plugins, admitted one capability at a time.

`docs/0010` §9.1 gave plugins the only **Partial BUILD** in an otherwise
SKIP-heavy table, and §9.2 said exactly which slice: packaging is
harness-specific and not our job, but *"policy over what may be installed and
reached is not."* This is that slice, at its smallest useful size.

A Claude Code plugin directory can contribute six things:

    agents/         subagent definitions
    hooks/          event handlers
    commands/       slash commands
    skills/         agent skills
    .mcp.json       MCP servers
    plugin.json     the manifest

**Five of those six are refused here, and the refusal is the feature.** A
plugin is third-party content: `docs/0010` §8.2 records that MCP amplifies
the effect problem, and hooks and commands are arbitrary behaviour attached
to an agent loop that this project spends its whole correctness budget
guarding. Admitting them because they happened to be in the folder would be
the opposite of a broker.

So the rule is **default-deny with an itemised receipt**. Only read-only agent
definitions are admitted, every one re-validated by
`subagent.validate` rather than trusted for having arrived in a manifest, and
everything declined is counted and named. A broker that silently dropped what
it would not run would leave you believing you had installed something you
had not.

## What is still trusted, and should be said plainly

An admitted definition carries a third-party `system_prompt`, and that becomes
instructions to a model that can read your files. Read-only bounds the damage
to *reading* — it cannot write, shell out, or reach the network — and the
workspace is scoped per task, so it reads where you pointed it and nowhere
else. That is a real bound, not a complete one. Pin plugin versions and do not
install one you would not read.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

#: The one capability a plugin may contribute.
ADMITTED = "agents"

#: Everything else, with why. Named rather than silently skipped — the point of
#: a broker is that you can audit what it refused.
REFUSED: dict[str, str] = {
    "mcp_config": "an MCP server is an arbitrary tool surface reached over a "
                  "pipe; nothing here can inspect what it would do "
                  "(`docs/0010` §8.2)",
    "hooks": "a hook is arbitrary behaviour attached to the agent loop, which "
             "is the thing the gate exists to guard",
    "commands": "slash commands belong to a harness UI, not to a control "
                "plane (`docs/0010` §9.1)",
    "skills": "a skill injects instructions into the context window; the "
              "harness owns that and does it better (`0007`)",
}


def load(plugin_dir: str | Path) -> dict[str, Any]:
    """Inspect a plugin. Reports what would be admitted and what is refused.

    Loads nothing into a live agent — this is the audit step. `agentctl
    plugins` prints it, and a caller that wants the definitions takes
    `admitted`.
    """
    from openhands.sdk.plugin.format.claude_code import ClaudeCodePluginFormat

    from .subagent import NotReadOnly, validate

    d = Path(plugin_dir)
    if not d.is_dir():
        return {"path": str(d), "error": f"no such directory: {d}"}

    fmt = ClaudeCodePluginFormat()
    try:
        manifest = fmt.load_manifest(d)
    except Exception as e:                              # noqa: BLE001
        return {"path": str(d), "error": f"unreadable manifest: {e}"}

    admitted, rejected = [], []
    try:
        for defn in fmt.load_agents(d):
            try:
                validate(defn)
                admitted.append(defn)
            except NotReadOnly as e:
                rejected.append((getattr(defn, "name", "<unnamed>"), str(e)))
    except Exception as e:                              # noqa: BLE001
        rejected.append(("<agents/>", f"could not be read: {e}"))

    return {
        "path": str(d),
        "name": getattr(manifest, "name", d.name),
        "version": getattr(manifest, "version", "?"),
        "description": getattr(manifest, "description", ""),
        "admitted": admitted,
        "rejected": rejected,
        "refused": _refused_counts(fmt, d),
    }


def _refused_counts(fmt: Any, d: Path) -> list[tuple[str, int, str]]:
    """What the plugin carries that this project will not run.

    Counted, not just listed. "declines MCP servers" is a policy statement;
    "declines 3 MCP servers" is a fact about the thing in front of you, and
    only the second tells you whether refusing it matters.
    """
    out = []
    for cap, why in REFUSED.items():
        try:
            loader = {
                "mcp_config": fmt.load_mcp_config,
                "hooks": fmt.load_hooks,
                "commands": fmt.load_commands,
                "skills": lambda p: [],   # assembled by the base class' load()
            }[cap]
            got = loader(d)
        except Exception:                               # noqa: BLE001
            continue
        if got is None:
            continue
        n = len(got) if hasattr(got, "__len__") else 1
        if n:
            out.append((cap, n, why))
    return out
