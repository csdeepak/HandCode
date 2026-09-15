"""agentctl — inspect and resolve the effect ledger.

The human interface to fail-closed. When the gate cannot tell whether an effect
landed it blocks and waits; without a way to see and answer those, the design
is correct and unusable (`docs/0013` §3, Panel 3).

    agentctl keys                    provider keys: what is set, where to get more
    agentctl dash                    one screen: providers, effects, spend, policy
    agentctl doctor                  is everything ready? check before running
    agentctl run "<task>"            run an agent on a real workspace
    agentctl status                  what is in the ledger
    agentctl cost                    what the work cost, and how much is known
    agentctl ingest <telemetry>      load Seam A telemetry into the cost ledger
    agentctl blocked                 effects awaiting a decision
    agentctl show <tool_call_id>     everything known about one effect
    agentctl resolve <id> --landed   record that it did happen
    agentctl resolve <id> --retry    record that it did not; allow a retry

Read-only by default. The two `resolve` forms are the only writes, and both
require an explicit choice — there is no "probably fine".
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from agentctl.control.cost import CostLedger
from agentctl.kernel.ledger.models import EffectState
from agentctl.kernel.ledger.store import LedgerStore

DEFAULT_LEDGER = Path("ledger.db")
DEFAULT_COST_LEDGER = Path("cost.db")


def _ascii_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _ts(v: float | None) -> str:
    if not v:
        return "-"
    return datetime.fromtimestamp(v, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _open(path: Path) -> LedgerStore:
    if not path.exists():
        print(f"no ledger at {path}", file=sys.stderr)
        raise SystemExit(2)
    return LedgerStore(path, holder="cli")


# ── commands ───────────────────────────────────────────────────────────
def cmd_status(args) -> int:
    with _open(args.ledger) as s:
        rows = s._db.execute(
            "SELECT state, effect_class, COUNT(*) n FROM effect_record "
            "GROUP BY state, effect_class ORDER BY state, effect_class"
        ).fetchall()
        total = s._db.execute("SELECT COUNT(*) n FROM effect_record").fetchone()["n"]
        convs = s._db.execute(
            "SELECT COUNT(DISTINCT conversation_id) n FROM effect_record"
        ).fetchone()["n"]

    print(f"ledger {args.ledger}")
    print(f"  {total} effect(s) across {convs} conversation(s)\n")
    if not rows:
        print("  empty")
        return 0
    print(f"  {'STATE':<12} {'CLASS':<22} COUNT")
    for r in rows:
        print(f"  {r['state']:<12} {r['effect_class']:<22} {r['n']}")

    blocked = sum(r["n"] for r in rows if r["state"] == EffectState.BLOCKED.value)
    pending = sum(r["n"] for r in rows if r["state"] == EffectState.INTENT.value)
    print()
    if blocked:
        print(f"  {blocked} effect(s) need a decision -> agentctl blocked")
    if pending:
        print(f"  {pending} effect(s) still INTENT (a run may be in flight)")
    if not blocked and not pending:
        print("  nothing waiting")
    return 0


def cmd_blocked(args) -> int:
    with _open(args.ledger) as s:
        recs = s.blocked(args.conversation)
    if not recs:
        print("nothing blocked")
        return 0

    print(f"{len(recs)} effect(s) awaiting a decision:\n")
    for r in recs:
        print(f"  {r.tool_call_id}")
        print(f"    tool      {r.tool_name}  [{r.effect_class.value}]")
        print(f"    started   {_ts(r.started_at)}   attempt {r.attempt}")
        print(f"    reason    {r.error or '-'}")
        if r.probe_verdict:
            print(f"    probe     {r.probe_verdict}")
        print(f"    resolve   agentctl resolve {r.tool_call_id} --landed | --retry")
        print()
    return 0


def cmd_show(args) -> int:
    with _open(args.ledger) as s:
        r = s.lookup(args.tool_call_id)
    if r is None:
        print(f"no such effect: {args.tool_call_id}", file=sys.stderr)
        return 2

    print(f"{r.tool_call_id}")
    for label, value in [
        ("tool", r.tool_name), ("class", r.effect_class.value),
        ("state", r.state.value), ("conversation", r.conversation_id),
        ("turn", r.turn_id), ("attempt", r.attempt),
        ("started", _ts(r.started_at)), ("committed", _ts(r.committed_at)),
        ("fence", r.fence_token), ("probe", r.probe_verdict or "-"),
        ("error", r.error or "-"), ("intent_hash", r.intent_hash[:16] + "..."),
    ]:
        print(f"  {label:<13} {value}")

    if r.pre_state:
        print("  pre_state")
        try:
            for k, v in json.loads(r.pre_state).items():
                print(f"    {k:<11} {str(v)[:70]}")
        except Exception:
            print(f"    {r.pre_state[:200]}")
    print(f"  observation   {'recorded' if r.observation else 'none'}")
    return 0


def cmd_resolve(args) -> int:
    with _open(args.ledger) as s:
        r = s.lookup(args.tool_call_id)
        if r is None:
            print(f"no such effect: {args.tool_call_id}", file=sys.stderr)
            return 2
        if r.state is not EffectState.BLOCKED:
            print(f"effect is {r.state.value}, not BLOCKED - nothing to resolve",
                  file=sys.stderr)
            return 2

        # The CLI holds no lease, so adopt the record's fence to write.
        s._fences[r.conversation_id] = r.fence_token
        s.reconcile(args.tool_call_id, "HUMAN", landed=args.landed)

    if args.landed:
        print(f"{args.tool_call_id} -> COMMITTED (recorded as having happened)")
        print("  it will not be re-run.")
    else:
        print(f"{args.tool_call_id} -> FAILED (recorded as not having happened)")
        print("  the agent may retry it on the next run.")
    return 0


def cmd_cost(args) -> int:
    if not args.cost_ledger.exists():
        print(f"no cost ledger at {args.cost_ledger}\n"
              f"  run: agentctl ingest <hook_telemetry.json>", file=sys.stderr)
        return 2

    since = (time.time() - 86400) if args.today else None
    with CostLedger(args.cost_ledger) as c:
        t = c.totals(conversation_id=args.conversation, since=since)
        scope = ("today" if args.today else
                 f"conversation {args.conversation}" if args.conversation else "all time")

        print(f"cost ({scope})")
        print(f"  spend           {t.describe_cost()}")
        print(f"  calls           {t.calls}")
        print(f"  tokens          {t.prompt_tokens} in / {t.completion_tokens} out")
        if t.prompt_tokens:
            print(f"  cache hits      {t.cached_tokens} "
                  f"({t.cache_hit_ratio:.0%} of input)")

        if not t.trustworthy and t.calls:
            print()
            print(f"  ! PRICING COVERAGE {t.coverage:.0%} "
                  f"({t.priced_calls}/{t.calls} calls)")
            print("    litellm reports 0.0 for endpoints it cannot price, so an")
            print("    unpriced call is indistinguishable from a free one. The")
            print("    real total is HIGHER than the figure above.")
            if (blind := c.unpriced_deployments()):
                print(f"    unpriced: {', '.join(blind)}")

        if args.by_deployment:
            rows = c.by_deployment()
            if rows:
                print(f"\n  {'DEPLOYMENT':<18} {'CALLS':>6} {'PRICED':>7} {'COST':>10}")
                for r in rows:
                    priced = f"{r['priced_calls']}/{r['calls']}"
                    cost = (f"${r['cost']:.4f}" if r["priced_calls"] else "unknown")
                    print(f"  {(r['deployment'] or '-'):<18} {r['calls']:>6} "
                          f"{priced:>7} {cost:>10}")

        if args.by_conversation:
            rows = c.by_conversation()
            if rows:
                print(f"\n  {'CONVERSATION':<38} {'CALLS':>6} {'COST':>10}")
                for r in rows:
                    cost = (f"${r['cost']:.4f}" if r["priced_calls"] else "unknown")
                    print(f"  {(r['conversation_id'] or '-')[:36]:<38} "
                          f"{r['calls']:>6} {cost:>10}")
    return 0


def cmd_ingest(args) -> int:
    with CostLedger(args.cost_ledger) as c:
        n = c.ingest_telemetry(args.telemetry)
    if n == 0:
        print(f"nothing ingested from {args.telemetry}", file=sys.stderr)
        return 2
    print(f"ingested {n} record(s) into {args.cost_ledger}")
    print("  agentctl cost --by-deployment")
    return 0


def cmd_run(args) -> int:
    from agentctl.runtime.runner import run
    print("agentctl run")
    result = run(
        task=args.task, workspace=args.workspace, model=args.model,
        base_url=args.base_url, ledger=args.ledger if args.ledger != DEFAULT_LEDGER
        else None,
        confirm_destructive=not args.allow_destructive,
        max_iterations=args.max_iterations, max_budget_usd=args.max_budget,
        resume=args.resume, record=args.record, replay=args.replay,
        policy=args.policy,
    )
    print()
    print(f"  conversation  {result['conversation_id']}")
    print(f"  ledger        {result['ledger']}")
    verdicts = {}
    for d in result["decisions"]:
        verdicts[d["verdict"]] = verdicts.get(d["verdict"], 0) + 1
    print(f"  decisions     {verdicts or 'none'}")

    if rec := result.get("recorded"):
        print(f"  recorded      {rec['turns']} turns -> {rec['cassette']}"
              + (f"  ({rec['errors']} errors)" if rec["errors"] else ""))
        print(f"  replay it:    agentctl run '' --workspace "
              f"{result['workspace']} --replay {rec['cassette']}")

    if rep := result.get("replay"):
        print(f"  replayed      {rep['turns_replayed']}/{rep['turns_recorded']}"
              f" turns, $0.00")
        if rep["diverged"]:
            # The point of M6: a divergence is the finding, not an error.
            print(f"  DIVERGED      {rep['misses']} miss(es), "
                  f"{rep['unplayed']} turn(s) never reached")
            if rep["first_divergence"]:
                print(f"                {rep['first_divergence']}")
        else:
            print("  identical     the run matched the recording exactly")

    if result["blocked"]:
        print(f"  BLOCKED       {len(result['blocked'])} effect(s) need you:")
        print(f"                agentctl --ledger {result['ledger']} blocked")
        return 1
    print()
    print(f"  resume with:  agentctl run '' "
          f"--workspace {result['workspace']} "
          f"--resume {result['conversation_id']}")
    return 0


def cmd_doctor(args) -> int:
    """Preflight. What is ready, what is missing, what will stop you."""
    from agentctl.runtime.doctor import check_all, report

    print("agentctl doctor")
    print()
    rows = check_all(workspace=args.workspace, probe_network=not args.offline)
    return report(rows)


def cmd_keys(args) -> int:
    """Show which provider keys are set, and where to get the rest.

    Never prints a value. `set (73 chars)` is the most it will say.
    """
    from agentctl.control.keys import (HOME_PATH, check_not_tracked, resolve,
                                       write_template)
    from agentctl.control.providers import (PROVIDERS, accounts_for,
                                            all_accounts, missing)

    path = Path(args.file) if args.file else (resolve() or HOME_PATH)

    if args.init:
        p, created = write_template(path)
        print(f"{'wrote' if created else 'kept existing'} {p}")
        print("  added ignore rules to .gitignore BEFORE writing it")
        if created:
            print("  fill in the keys you have; blanks are fine")
        print()

    if (warn := check_not_tracked(path)):
        print(f"  !! {warn}", file=sys.stderr)
        print(file=sys.stderr)

    import os as _os

    accts = all_accounts()
    print(f"keys {path}{'' if path.exists() else '  (not created yet)'}")
    print()
    for p in PROVIDERS:
        tag = "" if p.free_tier else " (paid)"
        mine = accounts_for(p)
        if not mine:
            print(f"  --   {p.name:<15}{tag:<7} {p.console}")
            continue
        for a in mine:
            # Length only. The value never leaves the file.
            print(f"  ok   {a.label:<15}{tag:<7} {a.env:<26} "
                  f"set ({len(_os.environ.get(a.env, ''))} chars)")

    if args.check:
        from agentctl.control.probe import check_all, summarise

        print()
        print("  checking connectivity (metadata endpoints only -- no tokens spent)")
        results = check_all(accts)
        mark = {"live": "ok  ", "limited": "!!  ", "no-credit": "$$  ",
                "rejected": "XX  ", "unreachable": "??  ",
                "skipped": "--  "}
        for r in results:
            print(f"  {mark[r.status]} {r.account.label:<15} {r.status:<12} {r.detail}")
        sm = summarise(results)
        print()
        print(f"  {sm['working']}/{sm['total']} credentials authenticate "
              f"across {sm['providers_working']} provider(s)")

        # Authenticating is not the same as being allowed to infer. One call
        # per provider settles it (docs/0034 section 6).
        from agentctl.control.probe import check_inference
        print()
        print("  can they actually infer?  (one completion per provider)")
        usable = 0
        for name in sorted({a.provider.name for a in accts}):
            r = check_inference(name, allow_paid=args.check_paid)
            if r is None:
                continue
            print(f"  {mark.get(r.status, '??  ')} {name:<15} {r.status:<12} "
                  f"{r.detail}")
            usable += 1 if r.status in ("live", "limited") else 0
        print()
        print(f"  {usable} provider(s) can serve a request right now")
        broken = [r for r in results if not r.ok]
        if broken:
            print(f"  {len(broken)} not usable -- check the console for those")
            print("  a CDN error is NOT a bad key; the request never reached the API")
        return 0 if not broken else 1

    print()
    print(f"  {len(accts)} account(s) across "
          f"{len({a.provider.name for a in accts})} provider(s).")
    if len(accts) <= 1:
        print()
        print("  ONE ACCOUNT is the thing that stops work. A free-tier cap is")
        print("  usually per account, so a second key -- even at the SAME")
        print("  provider -- buys a second quota:")
        print()
        print("    OPENROUTER_API_KEY_2=sk-or-v1-...    # in your keys file")
        print()
        print("  Different providers are better still; they survive an outage")
        print("  as well as a cap:")
        for p in missing():
            if p.free_tier:
                print(f"    {p.name:<11} {p.console}")
    return 0


def cmd_dash(args) -> int:
    """Providers, failover, effects, spend and policy on one screen."""
    from agentctl.control.dash import collect, render, to_html

    data = collect(ledger=args.ledger, cost_ledger=args.cost_ledger)
    if args.html:
        out = Path(args.html)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(to_html(data), encoding="utf-8")
        print(f"wrote {out}")
        return 0
    print(render(data))
    return 0


def _provider_of(env_var: str) -> str:
    from agentctl.control.providers import BY_KEY
    base = env_var.split("_API_KEY")[0] + "_API_KEY"
    return BY_KEY[base].name


def cmd_proxy(args) -> int:
    """Generate a proxy config from the keys you actually have."""
    from agentctl.control.proxy import accounts, available, write

    only = None
    if args.verify:
        from agentctl.control.proxy import verified_providers
        print("  verifying providers (one completion each; paid skipped)...")
        only, report = verified_providers()
        for name, r in sorted(report.items()):
            flag = "ok  " if name in only else "--  "
            print(f"    {flag} {name:<12} {r.status:<11} {r.detail[:54]}")
        print()

    entries = [e for e in available()
               if only is None or _provider_of(e[0]) in only]
    cfg, hook = write(args.out, only=only)
    n_acct = len(accounts(entries))

    print(f"wrote {cfg}")
    print(f"wrote {hook}")
    print()
    print(f"  {len(entries)} deployment(s) across {n_acct} account(s):")
    for env_var, model, short, is_free in entries:
        print(f"    {short:<18} {model}  [{'free' if is_free else 'PAID'}]")
    print()
    if n_acct == 1:
        print("  ! ONE ACCOUNT. A pool over one key survives a transient")
        print("    overload or a per-model limit, but NOT an account-wide")
        print("    daily cap -- every entry above shares the same quota.")
        print("    Export a second provider key and re-run this.")
        print()
    print("  start it:")
    print(f"    bash {args.out}/start.sh 4000        # or: {args.out}/start.ps1")
    print("    (the launcher forces UTF-8 -- the proxy banner otherwise")
    print("     kills startup on a redirected Windows console, docs/0034)")
    print()
    print("  then point runs at it (no key needed client-side):")
    print("    agentctl run \"...\" --workspace ./app \\")
    print("      --model openai/pool --base-url http://localhost:4000")
    return 0


def cmd_policy(args) -> int:
    """Compile a policy, or show what the compiled one says.

    Compiling is a separate, explicit step for the reason in `docs/0012` §5.2:
    every error a policy can contain should surface HERE, where a person is
    watching, and never in the middle of a run where the only safe response is
    to stop the work.
    """
    from agentctl.control.policy import PolicyError, compile_to
    from agentctl.kernel.policy import Policy

    if args.source:
        try:
            out = compile_to(args.source, args.out)
        except PolicyError as e:
            print(f"{args.source} does not compile:\n{e}", file=sys.stderr)
            return 2
        except FileNotFoundError:
            print(f"no such policy: {args.source}", file=sys.stderr)
            return 2
        print(f"compiled {args.source} -> {out}")

    try:
        pol = Policy.load(args.out)
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        return 2

    print()
    print(f"policy {args.out}")
    print(f"  source        {pol.source_sha256[:16] or '(inline)'}")
    print(f"  default pool  {pol.default_pool} "
          f"{pol.pool(pol.default_pool or '')}")
    esc = pol.escalation
    if esc:
        print(f"  escalate to   {esc.get('pool')} "
              f"({'confirm' if esc.get('require_confirmation') else 'SILENT'})")
    for scope in ("per_task", "daily"):
        if (lim := pol.limit(scope)) is not None:
            print(f"  {scope:<13} ${lim:.2f}")
    print(f"  on exceeded   {pol.on_exceeded}")
    print(f"  on unpriced   {pol.on_unpriced}"
          "   (litellm prices some endpoints at 0.0 -- docs/0021)")
    for cls in ("PURE_READ", "IDEMPOTENT_WRITE", "NON_IDEMPOTENT_WRITE",
                "EXTERNAL", "DESTRUCTIVE"):
        if (rule := pol.effect_rule(cls)):
            print(f"  {cls:<13} {rule}")
    return 0


# ── entry point ────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentctl", description="Inspect and resolve the effect ledger.")
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER,
                   help=f"path to the effect ledger (default: {DEFAULT_LEDGER})")
    p.add_argument("--cost-ledger", type=Path, default=DEFAULT_COST_LEDGER,
                   help=f"path to the cost ledger (default: {DEFAULT_COST_LEDGER})")

    # The same two options AFTER the subcommand, because that is where people
    # type them: `agentctl status --ledger X` used to be an error telling you
    # the argument was unrecognised, while `agentctl --ledger X status` worked.
    # SUPPRESS is what makes this safe -- without it the subparser's default
    # would overwrite a value given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ledger", type=Path, default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)
    common.add_argument("--cost-ledger", type=Path, default=argparse.SUPPRESS,
                        help=argparse.SUPPRESS)

    sub = p.add_subparsers(dest="command", required=True)
    _orig_add_parser = sub.add_parser

    def add_parser(name, **kw):
        kw.setdefault("parents", [common])
        return _orig_add_parser(name, **kw)

    sub.add_parser = add_parser                 # every subcommand gets them

    sub.add_parser("status", help="summary of the ledger").set_defaults(fn=cmd_status)

    b = sub.add_parser("blocked", help="effects awaiting a human decision")
    b.add_argument("--conversation", help="limit to one conversation")
    b.set_defaults(fn=cmd_blocked)

    sh = sub.add_parser("show", help="everything known about one effect")
    sh.add_argument("tool_call_id")
    sh.set_defaults(fn=cmd_show)

    r = sub.add_parser("resolve", help="decide a blocked effect")
    r.add_argument("tool_call_id")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--landed", action="store_true",
                   help="it DID happen; do not run it again")
    g.add_argument("--retry", dest="landed", action="store_false",
                   help="it did NOT happen; allow a retry")
    r.set_defaults(fn=cmd_resolve)

    rn = sub.add_parser("run", help="run an agent on a real workspace")
    rn.add_argument("task", help="what you want done")
    rn.add_argument("--workspace", type=Path, default=Path("."),
                    help="directory the agent works in (default: cwd)")
    rn.add_argument("--model", default="openrouter/nvidia/nemotron-3-super-120b-a12b:free")
    rn.add_argument("--base-url", help="an OpenAI-compatible endpoint, e.g. your proxy")
    rn.add_argument("--max-iterations", type=int, default=30)
    rn.add_argument("--max-budget", type=float, help="hard USD ceiling for the run")
    rn.add_argument("--resume", help="conversation id to continue")
    rn.add_argument("--policy", metavar="POLICY",
                    help="policy.yaml or a compiled policy. Budget caps and "
                         "effect rules are enforced before the run starts.")
    rn.add_argument("--record", metavar="CASSETTE",
                    help="write every completion to a cassette for later replay")
    rn.add_argument("--replay", metavar="CASSETTE",
                    help="serve completions from a cassette: no key, no "
                         "network, no tokens, no sampling")
    rn.add_argument("--allow-destructive", action="store_true",
                    help="do not ask before rm -rf, or before a write that "
                         "lands outside the workspace. Think first.")
    rn.set_defaults(fn=cmd_run)

    ky = sub.add_parser("keys", help="provider keys: what is set, where to get more")
    ky.add_argument("--init", action="store_true",
                    help="write a keys.env template listing every provider")
    ky.add_argument("--file", help="path to the keys file")
    ky.add_argument("--check-paid", action="store_true",
                    help="also send one tiny completion to PAID providers. "
                         "This costs money, so it is off by default.")
    ky.add_argument("--check", action="store_true",
                    help="test every key against the provider. Uses metadata "
                         "endpoints, so it costs no tokens and no quota.")
    ky.set_defaults(fn=cmd_keys)

    da = sub.add_parser("dash", help="one screen: providers, effects, spend, policy")
    da.add_argument("--html", metavar="OUT",
                    help="write a self-contained HTML page instead")
    da.set_defaults(fn=cmd_dash)

    px = sub.add_parser("proxy", help="generate a LiteLLM proxy config")
    px.add_argument("--out", default=".", help="where to write the config")
    px.add_argument("--verify", action="store_true",
                    help="test each provider first and leave out any that "
                         "cannot currently serve a request")
    px.set_defaults(fn=cmd_proxy)

    dr = sub.add_parser("doctor", help="check everything before you run")
    dr.add_argument("--workspace", help="also check this workspace")
    dr.add_argument("--offline", action="store_true",
                    help="skip the provider account probe")
    dr.set_defaults(fn=cmd_doctor)

    po = sub.add_parser("policy", help="compile and inspect the policy")
    po.add_argument("source", nargs="?",
                    help="policy.yaml to compile; omit to show the compiled one")
    po.add_argument("--out", type=Path,
                    default=Path("agentctl/control/policy/data/"
                                 "policy.compiled.json"),
                    help="where the compiled artifact lives")
    po.set_defaults(fn=cmd_policy)

    c = sub.add_parser("cost", help="what the work cost, and how much is known")
    c.add_argument("--today", action="store_true", help="last 24 hours only")
    c.add_argument("--conversation", help="one conversation")
    c.add_argument("--by-deployment", action="store_true")
    c.add_argument("--by-conversation", action="store_true")
    c.set_defaults(fn=cmd_cost)

    i = sub.add_parser("ingest", help="load Seam A telemetry into the cost ledger")
    i.add_argument("telemetry", type=Path)
    i.set_defaults(fn=cmd_ingest)
    return p


def main(argv: list[str] | None = None) -> int:
    _ascii_stdout()
    # Load keys.env before anything reads the environment. An already-exported
    # variable wins: something you set deliberately in a shell should not be
    # replaced by a file. Values are never printed (`docs/0032`).
    try:
        from agentctl.control.keys import load_quietly
        load_quietly()
    except Exception:                                   # noqa: BLE001
        pass                                            # never block the CLI
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
