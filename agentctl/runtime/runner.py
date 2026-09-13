"""Run a real agent on a real workspace, behind the gate.

This is the thing to use. Everything in `experiments/` is a test harness; this
does actual work.

    agentctl run "add type hints to utils.py" --workspace ./myproject

What it wires up:

    real tools          bash, read, write -- classified by the capability matrix
    the gate            Seams B and C, so a crash cannot duplicate an effect
    a real model        via OpenRouter, or any OpenAI-compatible base URL
    the ledgers         effect ledger + Seam A telemetry for `agentctl cost`

**Two different safety properties, and they are not the same thing:**

* The **gate** stops an effect happening *twice*. That is replay safety.
* `--confirm-destructive` stops a dangerous effect happening *at all* without
  a human saying yes. That is authorization.

A first-time `rm -rf` is not a replay, so the gate admits it. If you point this
at a repository you care about, keep the confirmation on — it is the default.

The confirmation asks on two independent grounds: the effect is `DESTRUCTIVE`,
or it writes somewhere outside the workspace. The second is not a lesser form
of the first — `echo x > ~/.bashrc` is an ordinary idempotent write that simply
is not the agent's business (`docs/0027`).
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

DEFAULT_MODEL = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"


def _key_for(model: str) -> tuple[str | None, str | None]:
    """Find a key for this model without ever printing it."""
    for prefix, env in (("openrouter/", "OPENROUTER_API_KEY"),
                        ("anthropic/", "ANTHROPIC_API_KEY"),
                        ("openai/", "OPENAI_API_KEY"),
                        ("gemini/", "GEMINI_API_KEY"),
                        ("mistral/", "MISTRAL_API_KEY")):
        if model.startswith(prefix):
            return os.environ.get(env), env
    for env in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if os.environ.get(env):
            return os.environ[env], env
    return None, None


def run(
    task: str,
    workspace: str | Path = ".",
    *,
    model: str = DEFAULT_MODEL,
    base_url: str | None = None,
    ledger: str | Path | None = None,
    confirm_destructive: bool = True,
    max_iterations: int = 30,
    max_budget_usd: float | None = None,
    resume: str | None = None,
    verbose: bool = True,
) -> dict:
    """Run one agent task. Returns a summary dict."""
    from agentctl.adapters.openhands import protect
    from agentctl.runtime import tools as rt
    from openhands.sdk import LLM, Agent, Conversation
    from openhands.sdk.tool import Tool

    ws = Path(workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    ledger_path = Path(ledger) if ledger else ws / ".agentctl" / "ledger.db"

    os.environ[rt.WORKSPACE_ENV] = str(ws)
    os.environ.setdefault("AGENTCTL_TELEMETRY",
                          str(ws / ".agentctl" / "hook_telemetry.json"))
    # Do NOT register the plain tools here: protect() registers gated versions
    # under the same names, and doing both only produces duplicate warnings.

    api_key, key_env = _key_for(model)
    if not api_key and not base_url:
        raise SystemExit(
            f"No API key found for {model}.\n"
            f"  Set one in your environment, e.g. OPENROUTER_API_KEY.\n"
            f"  It is read from the environment and never logged.")

    cid = uuid.UUID(resume) if resume else uuid.uuid4()

    decisions: list[dict] = []

    def on_decision(call, decision):
        decisions.append({"tool": call.tool_name,
                          "verdict": decision.verdict.value,
                          "reason": decision.reason})
        if verbose and decision.verdict.value != "EXECUTE":
            print(f"  [agentctl] {decision.verdict.value} {call.tool_name}: "
                  f"{decision.reason}", file=sys.stderr)

    guard = protect(
        ledger=ledger_path,
        conversation_id=str(cid),
        tools=rt.TOOLS,
        repo_root=ws,
        holder=f"run-{os.getpid()}",
        takeover=bool(resume),
        on_decision=on_decision,
    )

    if confirm_destructive:
        _install_confirmation(guard, verbose, workspace=ws)

    llm = LLM(model=model, api_key=api_key, base_url=base_url,
              service_id="agentctl-run", temperature=0.0,
              num_retries=2, max_output_tokens=4096)
    agent = Agent(llm=llm,
                  tools=[Tool(name=n) for n in rt.TOOLS],
                  include_default_tools=[])

    conv = Conversation(
        agent=agent, workspace=str(ws),
        persistence_dir=str(ws / ".agentctl" / "conversations"),
        conversation_id=cid, delete_on_close=False,
        max_iteration_per_run=max_iterations,
        callbacks=[guard.seam_b])

    # `Conversation(...)` is a strict factory and rejects this, but the
    # LocalConversation it returns honours the attribute (`docs/0015` §4).
    if max_budget_usd is not None:
        try:
            conv.max_budget_per_run = max_budget_usd
        except Exception:                               # noqa: BLE001
            print("  [agentctl] budget cap unsupported by this SDK build",
                  file=sys.stderr)

    guard.attach(conv)

    if verbose:
        print(f"  workspace     {ws}")
        print(f"  model         {model}"
              + (f"  (key from {key_env})" if key_env else ""))
        print(f"  conversation  {cid}")
        print(f"  ledger        {ledger_path}")
        print(f"  destructive   {'CONFIRM' if confirm_destructive else 'ALLOWED'}")
        print()

    if not resume:
        conv.send_message(task)
    conv.run()

    blocked = guard.blocked()
    guard.close()

    return {"conversation_id": str(cid), "workspace": str(ws),
            "ledger": str(ledger_path), "decisions": decisions,
            "blocked": [b.tool_call_id for b in blocked]}


def _install_confirmation(guard, verbose: bool, workspace: Path | None = None) -> None:
    """Ask before an effect that is dangerous, or that lands outside the workspace.

    The gate is about replay safety, so a first-time `rm -rf` passes it. This is
    the separate authorization question, asked here rather than buried in the
    gate so the two stay distinguishable (`docs/0025` §4).

    Two independent reasons to ask, and they are not the same question:

        DESTRUCTIVE          the effect is dangerous wherever it happens
        escapes the root     the effect is ordinary, but not the agent's
                             business -- `echo x > ~/.bashrc` classifies
                             IDEMPOTENT_WRITE and is correct to (`docs/0027`)

    Escalating the *class* for the second case would have been the easy fix and
    the wrong one: the ledger would then treat a replayable write as
    unrecoverable, and a safe resume would start failing closed.
    """
    from agentctl.kernel.ledger.models import EffectClass, GateDecision, Verdict
    from agentctl.kernel.paths import escaping_writes

    inner = guard.gate.guard

    def guard_with_confirmation(call):
        decision = inner(call)
        if decision.verdict is not Verdict.EXECUTE:
            return decision

        reasons: list[str] = []
        if decision.effect_class is EffectClass.DESTRUCTIVE:
            reasons.append("DESTRUCTIVE")
        if outside := escaping_writes(call, workspace):
            reasons.append("writes outside the workspace: "
                           + ", ".join(outside[:4]))
        if not reasons:
            return decision

        print(f"\n  !! {' | '.join(reasons)}", file=sys.stderr)
        print(f"     {call.tool_name} {str(call.args)[:200]}", file=sys.stderr)
        try:
            answer = input("     allow? [y/N] ").strip().lower()
        except EOFError:
            answer = "n"
        if answer != "y":
            return GateDecision(Verdict.BLOCK, decision.effect_class,
                                reason="refused by the operator")
        return decision

    guard.gate.guard = guard_with_confirmation
