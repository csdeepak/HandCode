r"""Read-only subagents: the affordable slice of multi-agent.

`docs/0038` §4 skips multi-agent, and the reason is not cost — it is that four
correctness mechanisms assume a single writer. The lease keys on
`conversation_id`, `find_by_intent` is conversation-scoped, the git probe
infers "HEAD moved, so my commit landed", and `SubstitutionHandoff`
fingerprints carry no agent. Two workers editing one workspace break all four,
and fixing that was priced at 24 engineering days.

**A subagent that cannot produce an effect needs none of them.** No effect
means nothing to duplicate, nothing to reconcile, nothing to lease, and
nothing for a probe to be wrong about. That is the whole argument for this
module, and it holds only for exactly as long as "cannot produce an effect"
stays true — so that property is enforced twice, below.

## What this uses, and what it had to build

The SDK ships the *format*: `AgentDefinition` reads Markdown frontmatter with
`model`, `tools`, `max_iteration_per_run`, `max_budget_per_run`, hooks and a
system prompt, and `openhands.sdk.subagent.load` discovers them from a
directory. That is the Claude Code subagent format, and this module is the
first thing in `agentctl/` that calls it.

It does not ship the *runtime*. `TaskManager` appears in two docstrings and no
module; there is no `task` tool. So dispatch is ours.

## Two enforcements, not one

1. **`validate()` refuses** a definition asking for anything outside
   `READ_ONLY_TOOLS`, and refuses one carrying `mcp_config` at all — an MCP
   server is a tool with effects behind it that no allowlist here can see.
2. **The tool list handed to the agent is built from the constant**, never
   from `definition.tools`. If validation were ever bypassed or wrongly
   relaxed, the subagent still receives only read tools.

The second is what makes the first a check rather than the mechanism. A
safety property that depends on one function returning correctly is one
refactor away from not being a safety property.

## `max_budget_per_run` is inert here, deliberately not relied on

It compares `accumulated_cost`, which LiteLLM reports as `0.0` on every
unpriced free endpoint (`docs/0038` §2). A budget cap reading zero is not a
cap, so iteration count is the bound that actually binds.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

#: Tools a subagent may hold. `read_file` only.
#:
#: `execute_bash` is deliberately absent and is not a close call: a shell is
#: not a read tool, it is every tool. The capability matrix classifies
#: individual commands, but it is regex over a command string and an
#: interpreter (`python -c "..."`) is opaque to it by construction (README,
#: "What it does not do yet"). Handing a read-only agent a shell would make
#: this module's entire safety argument depend on that classifier being
#: complete, which it is not claimed to be.
READ_ONLY_TOOLS = frozenset({"read_file"})

#: Where definitions live, relative to the workspace.
AGENTS_DIR = Path(".agentctl") / "agents"


class NotReadOnly(ValueError):
    """A definition asked for something that could change the world."""


def validate(definition: Any) -> None:
    """Refuse anything that could produce an effect. Raises `NotReadOnly`.

    Deliberately strict about `mcp_config`: an MCP server is an arbitrary
    tool surface reached over a pipe, and nothing here can inspect what it
    would do. `docs/0010` §8.2 already records that MCP amplifies the effect
    problem; a read-only agent is not the place to find out.
    """
    name = getattr(definition, "name", "<unnamed>")

    tools = set(getattr(definition, "tools", None) or ())
    forbidden = tools - READ_ONLY_TOOLS
    if forbidden:
        raise NotReadOnly(
            f"subagent {name!r} asks for {sorted(forbidden)}, which can "
            f"change the world. A read-only subagent may hold only "
            f"{sorted(READ_ONLY_TOOLS)}. It runs outside the effect ledger "
            f"precisely because it cannot produce an effect, so this is not "
            f"a restriction that can be relaxed without building the "
            f"24 days of prerequisites in docs/0038 §4.2 first."
        )

    if getattr(definition, "mcp_config", None):
        raise NotReadOnly(
            f"subagent {name!r} declares MCP servers. An MCP server is a "
            f"tool surface this module cannot inspect, so it cannot be "
            f"admitted to a read-only agent (`docs/0010` §8.2)."
        )


def discover(workspace: str | Path = ".") -> list[Any]:
    """Definitions under `<workspace>/.agentctl/agents/`, valid ones only.

    An invalid definition is skipped rather than raising, so one bad file
    does not hide every good one — but it is never silently skipped: the
    reason is attached for the caller to print.
    """
    from openhands.sdk.subagent.load import load_agents_from_dir

    d = Path(workspace) / AGENTS_DIR
    if not d.is_dir():
        return []
    out = []
    for defn in load_agents_from_dir(d):
        try:
            validate(defn)
        except NotReadOnly as e:
            defn.__dict__["_agentctl_rejected"] = str(e)
        out.append(defn)
    return out


def rejection(definition: Any) -> str | None:
    """Why `discover` would not run this one, or None."""
    return definition.__dict__.get("_agentctl_rejected")


def run(definition: Any, task: str, *, workspace: str | Path = ".",
        model: str | None = None, api_key: str | None = None,
        base_url: str | None = None, max_iterations: int = 15) -> str:
    """Run a read-only subagent on `task`. Returns what it reported.

    No ledger, no gate, no lease — see the module docstring. `validate` runs
    again here rather than trusting `discover`, because this is a public
    entry point and the caller may have built the definition itself.
    """
    from openhands.sdk import LLM, Conversation

    from . import tools as rt
    from .runner import _build_agent

    validate(definition)
    # The SDK resolves tools by name from a process-global registry, so they
    # must be registered before an Agent naming them is constructed.
    # `agentctl run` does this on its own path; a subagent started straight
    # from the CLI has no parent run to have done it.
    #
    # `overwrite=False` is load-bearing. Seam C registers GATED tools under
    # these same names, and a plain re-registration silently replaces them --
    # un-gating every effect the parent's guard was wrapping, with nothing
    # failing to say so. Never clobber a registration that already exists.
    rt.register_all(overwrite=False)

    ws = Path(workspace).resolve()
    # `read_file` resolves against this, not against the Conversation's
    # workspace argument -- deliberately, since it is configuration and never
    # model input (`docs/0023` §3). Setting only the latter left the subagent
    # hunting for `/gate.py` and, to its credit, refusing to guess.
    #
    # Scoped to this task, not the process: the env var version leaked a file
    # from one workspace into a subagent scoped to another, and leaked the
    # subagent's workspace back to the parent after it returned.
    token = rt._scoped_workspace.set(str(ws))
    try:
        return _run_scoped(definition, task, ws, model, api_key, base_url,
                           max_iterations)
    finally:
        # Even when construction fails. A subagent that raised before it ever
        # reached the model must not leave the parent's next `read_file`
        # resolving against the subagent's workspace.
        rt._scoped_workspace.reset(token)


def _run_scoped(definition, task, ws, model, api_key, base_url,
                max_iterations) -> str:
    """The body of `run`, with the workspace already scoped.

    Split out so the scope is released by one `finally` covering every failure
    path -- including `_build_agent` and `LLM(...)` construction, which is
    where a broken model id or a missing key actually raises.
    """
    from openhands.sdk import LLM, Conversation

    from .runner import _build_agent

    # NOT `definition.tools`. See the module docstring: the allowlist is the
    # mechanism, the validation is the check.
    tools = sorted(READ_ONLY_TOOLS)

    declared = getattr(definition, "model", "inherit")
    # `inherit` means "whatever the parent is using". Run straight from the
    # CLI there is no parent, and handing `None` to a validated `LLM` raised a
    # pydantic traceback from the very command `--init` tells you to type.
    # Fall back to the same default `agentctl run` uses.
    from .runner import DEFAULT_MODEL
    chosen = (model or DEFAULT_MODEL) if declared in ("inherit", "", None)         else declared

    if api_key is None and not base_url:
        # Direct calls need the key for THIS model's provider. Without this
        # the subagent inherited whatever litellm happened to find, which is
        # the wrong account as often as not. A proxy run needs no key at all:
        # the proxy holds them (`docs/0038` §5.2).
        from .runner import _key_for
        api_key, _ = _key_for(chosen)
    if base_url and api_key is None:
        # litellm still wants something; the proxy ignores it.
        api_key = "proxy-holds-the-credentials"

    llm = LLM(model=chosen, api_key=api_key, base_url=base_url,
              service_id=f"agentctl-subagent-{definition.name}",
              temperature=0.0, num_retries=2, max_output_tokens=4096)

    agent = _build_agent(llm, tools)
    if (prompt := getattr(definition, "system_prompt", "")):
        task = f"{prompt}\n\n---\n\n{task}"

    conv = Conversation(
        agent=agent, workspace=str(ws),
        persistence_dir=str(ws / ".agentctl" / "subagents" / definition.name),
        delete_on_close=False,
        # The bound that actually binds; max_budget_per_run does not.
        max_iteration_per_run=(
            getattr(definition, "max_iteration_per_run", None) or max_iterations),
    )
    conv.send_message(task)
    conv.run()
    return _final_text(conv)


def _content_text(item: Any) -> str:
    """Text out of one content part.

    In memory a part is a `TextContent` with `.text`; once persisted and
    reloaded it is a plain dict. Both shapes reach this function depending on
    whether the caller is holding a live conversation or a resumed one, so it
    handles both rather than assuming the happy one.
    """
    if isinstance(item, dict):
        return item.get("text") or ""
    return getattr(item, "text", "") or ""


def _final_text(conv: Any) -> str:
    """The last thing the subagent *said*, as text.

    Only agent messages count. An earlier version took the newest event
    carrying any content at all and so returned the user's own prompt back --
    which reads like an answer, is not one, and would have been spliced into a
    parent agent's context as though the subagent had reported something.

    Returns a plain marker rather than an empty string when there is nothing,
    because a caller must be able to tell "it found nothing" from "it never
    ran".
    """
    try:
        events = list(getattr(conv.state, "events", []) or [])
    except Exception:                                   # noqa: BLE001
        return "[subagent produced no readable transcript]"

    for ev in reversed(events):
        msg = getattr(ev, "llm_message", None)
        if msg is None:
            continue
        source = getattr(ev, "source", None)
        role = getattr(msg, "role", None) or (
            msg.get("role") if isinstance(msg, dict) else None)
        if source != "agent" and role != "assistant":
            continue
        content = (getattr(msg, "content", None)
                   or (msg.get("content") if isinstance(msg, dict) else None))
        parts = [t for t in (_content_text(c) for c in (content or [])) if t]
        if parts:
            return "\n".join(parts).strip()
    return "[subagent produced no readable transcript]"
