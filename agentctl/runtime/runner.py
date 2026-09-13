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
import time
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


def _env_var_for(model: str) -> str:
    """The environment variable this model's provider actually reads."""
    for prefix, env in (("openrouter/", "OPENROUTER_API_KEY"),
                        ("anthropic/", "ANTHROPIC_API_KEY"),
                        ("openai/", "OPENAI_API_KEY"),
                        ("gemini/", "GEMINI_API_KEY"),
                        ("mistral/", "MISTRAL_API_KEY"),
                        ("cerebras/", "CEREBRAS_API_KEY"),
                        ("groq/", "GROQ_API_KEY")):
        if model.startswith(prefix):
            return env
    return "the API key variable for your provider"


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
    record: str | Path | None = None,
    replay: str | Path | None = None,
    policy: str | Path | None = None,
    cost_ledger: str | Path | None = None,
    verbose: bool = True,
) -> dict:
    """Run one agent task. Returns a summary dict.

    `record` writes every completion to a cassette; `replay` serves them back
    from disk with no API key, no network and no sampling (M6, `docs/0029`).
    """
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

    # Replay stands in for the provider entirely: the cassette decides the
    # model, so a `--model` flag cannot silently invalidate every fingerprint.
    replay_server = None
    if replay is not None:
        from agentctl.control.replay import Cassette, ReplayServer

        cassette = Cassette.load(replay)
        if not cassette.turns:
            raise SystemExit(f"cassette {replay} has no turns")
        first = cassette.turns[0]
        model = first.provider_model or first.model or model
        replay_server = ReplayServer(cassette).start()
        base_url = replay_server.base_url
        if verbose:
            print(f"  replay        {replay} ({len(cassette)} turns)")

    api_key, key_env = _key_for(model)
    if replay_server is not None:
        api_key, key_env = "replay-no-key-needed", None
    if not api_key and not base_url:
        raise SystemExit(
            f"No API key found for {model}.\n"
            # Name the variable THIS model needs. Telling someone to set
            # OPENROUTER_API_KEY for an anthropic/ model is advice that
            # cannot work.
            f"  Set {_env_var_for(model)} in your environment.\n"
            f"  It is read from the environment and never logged.\n"
            f"  Check what you have:  agentctl doctor")

    recorder = None
    if record is not None:
        from agentctl.adapters.litellm.recorder import attach

        recorder = attach(record, configured_model=model)
        if verbose:
            print(f"  recording     {record}")

    pol = _load_policy(policy)
    if pol:
        _enforce_before_spending(pol, model, cost_ledger, max_budget_usd,
                                 replay is not None, verbose)
        if max_budget_usd is None:
            max_budget_usd = pol.limit("per_task")
        # `docs/0002` §5: never silently spend. A policy that names DESTRUCTIVE
        # as requiring approval turns the confirmation on regardless of flags.
        if pol.requires_approval("DESTRUCTIVE"):
            confirm_destructive = True

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

    try:
        if not resume:
            conv.send_message(task)
        conv.run()
    except Exception as e:                              # noqa: BLE001
        # A provider refusing to serve is not a bug in the agent framework, and
        # the SDK's own error ends with "please file a bug report at
        # github.com/OpenHands" -- which sends you to the wrong place. Say what
        # actually happened (`docs/0031`).
        detail = _explain_provider_error(e)
        if detail:
            raise SystemExit(detail) from None
        raise
    finally:
        # A cassette is only useful if it survives the run that produced it,
        # including a run that died -- which is the interesting case here.
        if recorder is not None:
            from agentctl.adapters.litellm.recorder import detach
            detach(recorder)

    blocked = guard.blocked()
    guard.close()

    out = {"conversation_id": str(cid), "workspace": str(ws),
           "ledger": str(ledger_path), "decisions": decisions,
           "blocked": [b.tool_call_id for b in blocked]}

    if recorder is not None:
        out["recorded"] = {"cassette": str(record),
                           "turns": len(recorder.cassette),
                           "errors": recorder.errors}
    if replay_server is not None:
        from agentctl.control.replay import summarise
        out["replay"] = summarise(replay_server.cassette)
        replay_server.stop()

    return out


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


# ── policy enforcement (M7, docs/0030) ─────────────────────────────────
def _load_policy(policy):
    """Load a compiled policy, or compile a .yaml on the spot.

    Accepting the source form is a convenience with a sharp edge: compiling
    here means a malformed policy is discovered at run time, which is exactly
    what `docs/0012` §5.2 wants to avoid. So it is compiled BEFORE anything
    else happens, and a failure stops the run before a single effect.
    """
    from pathlib import Path as _P

    from agentctl.kernel.policy import Policy

    if policy is None:
        return Policy.empty()
    p = _P(policy)
    if p.suffix in (".yaml", ".yml"):
        from agentctl.control.policy import PolicyError, compile_policy
        try:
            return Policy(compile_policy(p))
        except PolicyError as e:
            raise SystemExit(f"policy {p} does not compile:\n{e}")
    return Policy.load(p)


def _daily_spend(cost_ledger) -> tuple[float, float] | None:
    """(spent, coverage) for the last 24h, or None if nothing is recorded.

    Read HERE, in the runtime, and handed to the kernel as a number. The kernel
    may not import the cost ledger (`docs/0008` R2) and should not: a budget
    guard that queried a database in-band would fail closed whenever the
    control plane was down, turning a cost feature into an outage.
    """
    from pathlib import Path as _P

    p = _P(cost_ledger) if cost_ledger else _P("cost.db")
    if not p.exists():
        return None
    try:
        from agentctl.control.cost import CostLedger
        with CostLedger(p) as c:
            t = c.totals(since=time.time() - 86400)
        return (t.cost_usd, t.coverage) if t.calls else None
    except Exception:                                   # noqa: BLE001
        return None


def _enforce_before_spending(pol, model, cost_ledger, max_budget_usd,
                             replaying: bool, verbose: bool) -> None:
    """Refuse the run outright if policy already says no.

    Before the ledger, before the agent, before a single token: a budget check
    that happens after the work is an audit, not a cap.
    """
    if verbose:
        print(f"  policy        {len(pol.pool(pol.default_pool or ''))} "
              f"deployment(s) in {pol.default_pool!r}"
              f"  per-task ${pol.limit('per_task') or 0:.2f}")

    # Replay spends nothing, so a budget cannot bind and a stale ledger must
    # not stop an offline run.
    if replaying:
        return

    spend = _daily_spend(cost_ledger)
    if spend is not None:
        spent, coverage = spend
        v = pol.check_budget(spent, "daily", coverage)
        if not v.allowed:
            raise SystemExit(
                f"refusing to start: {v.reason}\n"
                f"  raise budget.daily_usd, or wait for the window to roll.")
        if not v.trustworthy and verbose:
            print(f"  ! budget      {v.describe()}", file=sys.stderr)

    # Escalation: using something outside the default pool is spending money
    # the policy did not pre-authorise (`docs/0002` §5).
    default = pol.default_pool
    if default and model not in pol.pool(default):
        esc = pol.escalation or {}
        target = esc.get("pool")
        in_escalation_pool = target and model in pol.pool(target)
        if esc.get("require_confirmation", True):
            where = f"the {target!r} pool" if in_escalation_pool else "no pool"
            print(f"\n  !! {model} is not in the default pool {default!r} "
                  f"({where})", file=sys.stderr)
            try:
                answer = input("     spend on it? [y/N] ").strip().lower()
            except EOFError:
                answer = "n"
            if answer != "y":
                raise SystemExit("refused: policy requires confirmation "
                                 "before leaving the default pool")


def _explain_provider_error(exc: Exception) -> str | None:
    """Turn a provider refusal into something actionable, or None.

    Returns None for anything not recognised -- guessing at an unfamiliar
    error would hide it, and an unhandled traceback is better than a confident
    wrong explanation.
    """
    import re

    text = str(exc)
    low = text.lower()

    if "rate limit" in low or "429" in text or "ratelimiterror" in low:
        when = ""
        if m := re.search(r'"X-RateLimit-Reset":"(\d{10,13})"', text):
            from datetime import datetime
            ts = int(m.group(1))
            ts = ts / 1000 if ts > 10_000_000_000 else ts
            r = datetime.fromtimestamp(ts).astimezone()
            when = f"\n  resets       {r:%Y-%m-%d %H:%M} local"
        remaining = ""
        if m := re.search(r'"X-RateLimit-Remaining":"(\d+)"', text):
            remaining = f"\n  remaining    {m.group(1)}"
        per_day = ("\n  note         the free-model cap is account-wide across "
                   "every `:free`\n               model, so switching model "
                   "does not help"
                   if "free-models-per-day" in low else "")
        return (f"the provider is rate limiting you. This is not an agent "
                f"error.{remaining}{when}{per_day}\n"
                f"  options      wait for the reset, use a different provider "
                f"key,\n               or run offline:  agentctl run '' "
                f"--replay <cassette>")

    if "insufficient" in low and "credit" in low:
        return ("the provider says the account is out of credit. Nothing was "
                "spent on this run.")

    if "no auth credentials" in low or "invalid api key" in low or "401" in text:
        return ("the provider rejected the API key. Check the environment "
                "variable for your model's provider; the value is read from "
                "the environment and never logged.")

    if ("400 bad request" in low or "badrequesterror" in low
            or "not a valid model" in low):
        return ("the provider rejected the request — usually an unknown or "
                "unavailable model id.\n"
                "  check        the id at openrouter.ai/models; it needs the "
                "provider prefix,\n"
                "               e.g. openrouter/vendor/model:free\n"
                "  known-good   agentctl proxy   (lists the ids it builds a "
                "pool from)")

    if "overloaded" in low or "503" in text or "502" in text:
        return ("the provider is overloaded and refused the request. Free-tier "
                "endpoints do this under load.\n"
                "  options      retry, or point --base-url at a proxy with a "
                "pool so a failure fails over.")
    return None
