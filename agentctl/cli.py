"""agentctl — inspect and resolve the effect ledger.

The human interface to fail-closed. When the gate cannot tell whether an effect
landed it blocks and waits; without a way to see and answer those, the design
is correct and unusable (`docs/0013` §3, Panel 3).

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
        resume=args.resume,
    )
    print()
    print(f"  conversation  {result['conversation_id']}")
    print(f"  ledger        {result['ledger']}")
    verdicts = {}
    for d in result["decisions"]:
        verdicts[d["verdict"]] = verdicts.get(d["verdict"], 0) + 1
    print(f"  decisions     {verdicts or 'none'}")
    if result["blocked"]:
        print(f"  BLOCKED       {len(result['blocked'])} effect(s) need you:")
        print(f"                agentctl --ledger {result['ledger']} blocked")
        return 1
    print()
    print(f"  resume with:  agentctl run '' "
          f"--workspace {result['workspace']} "
          f"--resume {result['conversation_id']}")
    return 0


# ── entry point ────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentctl", description="Inspect and resolve the effect ledger.")
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER,
                   help=f"path to the effect ledger (default: {DEFAULT_LEDGER})")
    p.add_argument("--cost-ledger", type=Path, default=DEFAULT_COST_LEDGER,
                   help=f"path to the cost ledger (default: {DEFAULT_COST_LEDGER})")
    sub = p.add_subparsers(dest="command", required=True)

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
    rn.add_argument("--allow-destructive", action="store_true",
                    help="do not ask before rm -rf, or before a write that "
                         "lands outside the workspace. Think first.")
    rn.set_defaults(fn=cmd_run)

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
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
