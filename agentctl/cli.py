"""agentctl — inspect and resolve the effect ledger.

The human interface to fail-closed. When the gate cannot tell whether an effect
landed it blocks and waits; without a way to see and answer those, the design
is correct and unusable (`docs/0013` §3, Panel 3).

    agentctl status                  what is in the ledger
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
from datetime import datetime, timezone
from pathlib import Path

from agentctl.kernel.ledger.models import EffectState
from agentctl.kernel.ledger.store import LedgerStore

DEFAULT_LEDGER = Path("ledger.db")


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


# ── entry point ────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentctl", description="Inspect and resolve the effect ledger.")
    p.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER,
                   help=f"path to the ledger (default: {DEFAULT_LEDGER})")
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
    return p


def main(argv: list[str] | None = None) -> int:
    _ascii_stdout()
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
