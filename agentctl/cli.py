"""agentctl — inspect and resolve the effect ledger.

The human interface to fail-closed. When the gate cannot tell whether an effect
landed it blocks and waits; without a way to see and answer those, the design
is correct and unusable (`docs/0013` §3, Panel 3).

    agentctl keys                    provider keys: what is set, where to get more
    agentctl dash                    one screen: providers, effects, spend, policy
    agentctl doctor                  is everything ready? check before running
    agentctl models                  sources you can route to, and what each costs
    agentctl run "<task>"            run an agent on a real workspace
    agentctl subagent <name> "<q>"   delegate a READ to a read-only subagent
    agentctl plugins <dir>           what a plugin would contribute, and what is not
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
from agentctl.kernel.ledger.store import (
    SHORT_ID,
    AmbiguousPrefix,
    LedgerStore,
    short_id,
)

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



def _resolve_id(store: LedgerStore, given: str) -> str | None:
    """An id the user typed -- exact, or an unambiguous prefix.

    Gemini's `tool_call_id` carries a thought signature and runs past 300
    characters (`research/phase-10-3` V4), so nobody is retyping one. An
    ambiguous prefix is refused with the candidates rather than guessed at:
    this is the path that records an effect as having happened.
    """
    try:
        return store.resolve_id(given)
    except AmbiguousPrefix as e:
        print(f"{given!r} matches {len(e.matches)} effects:", file=sys.stderr)
        for m in e.matches:
            print(f"  {short_id(m)}   ({m[:40]}...)", file=sys.stderr)
        print("  give more characters.", file=sys.stderr)
        raise SystemExit(2) from None


# ── commands ───────────────────────────────────────────────────────────
def _row_cost(r: dict) -> str:
    """One row's cost, in the ledger's three states (docs/0042 I-10)."""
    if r["priced_calls"]:
        extra = " +free" if r["free_calls"] else ""
        return f"${r['cost']:.4f}{extra}" + ("" if r["priced_calls"] + r["free_calls"]
                                              == r["calls"] else " +?")
    if r["free_calls"] == r["calls"]:
        return "free"
    return "unknown"


def cmd_init(args) -> int:
    from agentctl.runtime.init import run_init
    return run_init(provider=args.provider, model=args.model,
                    verify=args.verify, key_stdin=args.key_stdin,
                    check_paid=args.check_paid)


def _status_runs() -> int:
    """What happened while you were away (`docs/0013` §3, Panel 3)."""
    from agentctl.runtime import runs
    rows = runs.recent(15)
    if not rows:
        print("no runs recorded yet. Start one:  agentctl run \"<task>\"")
        return 0
    print(f"  {'RUN':<9} {'STARTED (UTC)':<20} {'STATE':<13} {'OUTCOME':<12} "
          f"{'REQ':>4}  WORKSPACE")
    for r in rows:
        print(f"  {r.conversation_id[:8]:<9} {_ts(r.started):<20} {r.state:<13} "
              f"{(r.outcome or '-'):<12} {(r.requests if r.requests is not None else '-'):>4}"
              f"  {r.workspace}")
    waiting = 0
    for path in runs.ledgers():
        with LedgerStore(path, holder="cli") as s:
            waiting += len(s.blocked())
    print()
    if waiting:
        print(f"  {waiting} action(s) need you -> agentctl blocked")
    died = [r for r in rows if r.state in ("died", "interrupted", "rate_limited")]
    if died:
        print(f"  continue the latest unfinished one:  agentctl resume "
              f"{died[0].conversation_id[:8]}")
    if not waiting and not died:
        print("  nothing waiting")
    return 0


def cmd_status(args) -> int:
    if args.ledger == DEFAULT_LEDGER and not args.ledger.exists():
        return _status_runs()
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
    from agentctl.runtime.runner import AWAITING
    recs = []
    for path in _ledgers(args):
        with LedgerStore(path, holder="cli") as s:
            recs += s.blocked(args.conversation)
    if not recs:
        print("nothing blocked")
        return 0
    approvals = [r for r in recs if (r.error or "").startswith(AWAITING)]
    for r in approvals:
        print(f"  {short_id(r.tool_call_id)}  waiting for your approval")
        print(f"    {(r.error or '').split('): ', 1)[-1][:120]}")
        print(f"    agentctl approve {r.tool_call_id[:SHORT_ID]}   |   "
              f"agentctl deny {r.tool_call_id[:SHORT_ID]}")
        print()
    recs = [r for r in recs if r not in approvals]
    if not recs:
        return 0

    print(f"{len(recs)} effect(s) awaiting a decision:\n")
    for r in recs:
        print(f"  {short_id(r.tool_call_id)}")
        print(f"    tool      {r.tool_name}  [{r.effect_class.value}]")
        print(f"    started   {_ts(r.started_at)}   attempt {r.attempt}")
        print(f"    reason    {r.error or '-'}")
        if r.probe_verdict:
            print(f"    probe     {r.probe_verdict}")
        # The bare prefix, NOT short_id(): the `...` marks a truncation for a
        # reader and is not part of the id, so a command carrying it cannot be
        # pasted. A hint you have to edit before it works is worse than none.
        print(f"    resolve   agentctl resolve {r.tool_call_id[:SHORT_ID]} "
              f"--landed | --retry")
        print()
    return 0


def cmd_show(args) -> int:
    if (found := _find_effect(args, args.tool_call_id)) is None:
        return 2
    path, full = found
    with LedgerStore(path, holder="cli") as s:
        r = s.lookup(full) if full else None
    if r is None:
        print(f"no such effect: {args.tool_call_id}", file=sys.stderr)
        return 2

    print(f"{short_id(r.tool_call_id)}")
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
    if (found := _find_effect(args, args.tool_call_id)) is None:
        return 2
    path, full = found
    with LedgerStore(path, holder="cli") as s:
        r = s.lookup(full) if full else None
        if r is None:
            print(f"no such effect: {args.tool_call_id}", file=sys.stderr)
            return 2
        if r.state is not EffectState.BLOCKED:
            print(f"effect is {r.state.value}, not BLOCKED - nothing to resolve",
                  file=sys.stderr)
            return 2

        # The CLI holds no lease, so adopt the record's fence to write.
        s._fences[r.conversation_id] = r.fence_token
        s.reconcile(full, "HUMAN", landed=args.landed)

    if args.landed:
        print(f"{short_id(full)} -> COMMITTED (recorded as having happened)")
        print("  it will not be re-run.")
    else:
        print(f"{short_id(full)} -> FAILED (recorded as not having happened)")
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
                  f"({t.known_calls}/{t.calls} calls known)")
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
                    priced = f"{r['priced_calls'] + r['free_calls']}/{r['calls']}"
                    cost = _row_cost(r)
                    print(f"  {(r['deployment'] or '-'):<18} {r['calls']:>6} "
                          f"{priced:>7} {cost:>10}")

        if args.by_conversation:
            rows = c.by_conversation()
            if rows:
                print(f"\n  {'CONVERSATION':<38} {'CALLS':>6} {'COST':>10}")
                for r in rows:
                    cost = _row_cost(r)
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
    from agentctl.runtime import config
    from agentctl.runtime.runner import run
    print("agentctl run")

    cfg = config.load()
    base_url = config.resolve("base_url", args.base_url, cfg).value
    m = config.resolve("model", args.model, cfg)
    model = m.value
    if args.pool:
        # One flag instead of three commands and two flags (docs/0044 F3).
        from agentctl.control import proxyenv
        from agentctl.control.proxy import POOL
        s = proxyenv.status()
        if s["state"] != "running":
            proxyenv.up()
            s = proxyenv.status()
        base_url = proxyenv.url(s["port"])
        if not args.source:
            model = f"openai/{POOL}"
            m = config.Setting(model, "--pool")
        print(f"  pool          {base_url}")
    if args.source:
        # A source group only exists inside the proxy's config, so asking for
        # one without a proxy would resolve to nothing. Refuse rather than
        # silently fall back to the default model, which would run the task on
        # a provider the user just said not to use.
        if not base_url:
            print("  --source needs a proxy to route through.")
            print("    agentctl proxy --out ./proxy")
            print("    bash ./proxy/start.sh 4000")
            print("    ... then add --base-url http://localhost:4000")
            return 2
        from agentctl.control.proxy import SOURCE_PREFIX, sources
        known = {r["source"] for r in sources()}
        if args.source not in known:
            print(f"  no source called {args.source!r}. "
                  f"You have: {', '.join(sorted(known)) or 'none'}")
            print("  `agentctl models` lists them and what each one gives up.")
            return 2
        model = f"openai/{SOURCE_PREFIX}{args.source}"
        print(f"  source        {args.source} (narrower than the full pool)")
    elif model is None and not args.replay:
        print("  no model: no flag, no AGENTCTL_MODEL, no config, and no key to")
        print("  derive one from. One command sets all of that up:")
        print("    agentctl init")
        return 2
    elif model:
        print(f"  model from    {m.source}")
    from agentctl.runtime.runner import RateLimited

    # `--wait`: a rate limit is waited out and the SAME conversation resumed,
    # bounded in time and attempts (`docs/0042` I-05, wait-only half). Without
    # it the run ends with the one command that continues it.
    limit = _duration_s(getattr(args, "wait", None))
    resume, waited, attempt = args.resume, 0.0, 0
    while True:
        try:
            result = run(
                task=args.task if not resume else "",
                workspace=args.workspace, model=model or "replay",
                base_url=base_url,
                ledger=args.ledger if args.ledger != DEFAULT_LEDGER else None,
                confirm_destructive=not args.allow_destructive,
                max_iterations=args.max_iterations, max_budget_usd=args.max_budget,
                resume=resume, record=args.record, replay=args.replay,
                policy=args.policy, takeover=args.takeover, accept=args.accept,
            )
            break
        except RateLimited as rl:
            print(f"\n  {rl.text}")
            pause = _rate_limit_pause(rl, limit, waited, attempt)
            short = rl.conversation_id[:8]
            if pause is None:
                print(f"\n  continue later:  agentctl resume {short}"
                      + ("" if limit else "   (or add --wait 30m to wait it out)"))
                return 1
            print(f"\n  waiting {_fmt_s(pause)} for the limit to reset, then "
                  f"resuming {short} (--wait {args.wait}) ...")
            time.sleep(pause)
            waited, attempt, resume = waited + pause, attempt + 1, rl.conversation_id

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

    # One report in place of `decisions {'EXECUTE': 9}` (docs/0044 F6, F10).
    # Exit 0 means: nothing failed a check and nothing waits on you. It used
    # to be 1 for any blocked effect, including after a fully successful task.
    report = result.get("report")
    if report is None:                          # an embedder's stub, say
        return 1 if result["blocked"] else 0
    for line in report.lines():
        print(line)
    return 0 if report.ok else 1


def _duration_s(text: str | None) -> float:
    """`90s`, `30m`, `2h`, or bare seconds. 0 when not given."""
    if not text:
        return 0.0
    text = str(text).strip().lower()
    mult = {"s": 1, "m": 60, "h": 3600}.get(text[-1:], None)
    try:
        return float(text[:-1]) * mult if mult else float(text)
    except ValueError:
        raise SystemExit(f"--wait wants a duration like 90s, 30m or 2h, not {text!r}")


def _fmt_s(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def _rate_limit_pause(rl, limit: float, waited: float, attempt: int) -> float | None:
    """How long to wait before resuming, or None to stop and say so.

    The provider's reset time when it gave one; otherwise a doubling backoff
    from a minute (per-minute limits give no header). Never past `--wait`,
    and never more than five attempts: an auto-resume loop that cannot end
    is a way to spend a day of quota on one failure.
    """
    if not limit or attempt >= 5:
        return None
    if rl.reset_at:
        pause = max(5.0, rl.reset_at - time.time() + 5)
    else:
        pause = 60.0 * (2 ** attempt)
    if waited + pause > limit:
        print(f"  the limit resets in {_fmt_s(pause)}, which is past --wait "
              f"({_fmt_s(limit - waited)} left)")
        return None
    return pause


def _ledgers(args) -> list[Path]:
    """The ledgers a follow-up command should read.

    An explicit `--ledger`, or `./ledger.db` when there is one; otherwise
    every ledger a recorded run wrote (`~/.agentctl/runs.db`). Phase 0 found
    `status` saying "no ledger at ledger.db" from inside a workspace that had
    one (`docs/0044` F4).
    """
    if args.ledger != DEFAULT_LEDGER or args.ledger.exists():
        return [args.ledger]
    from agentctl.runtime import runs
    found = runs.ledgers()
    if not found:
        print("no runs recorded yet, and no ledger here. Start one:  "
              "agentctl run \"<task>\"", file=sys.stderr)
        raise SystemExit(2)
    return found


def _find_effect(args, given: str) -> tuple[Path, str] | None:
    """(ledger, full tool_call_id) for an id prefix, across every ledger.

    Refuses rather than guesses when the prefix is in more than one ledger:
    this is the path that records an effect as having happened."""
    hits: list[tuple[Path, str]] = []
    for path in _ledgers(args):
        with LedgerStore(path, holder="cli") as s:
            if (full := _resolve_id(s, given)):
                hits.append((path, full))
    if not hits:
        print(f"no such effect: {given}", file=sys.stderr)
        return None
    if len(hits) > 1:
        print(f"{given!r} matches effects in {len(hits)} ledgers:", file=sys.stderr)
        for path, full in hits:
            print(f"  {short_id(full)}   in {path}", file=sys.stderr)
        print("  give more characters, or --ledger <path>.", file=sys.stderr)
        raise SystemExit(2)
    return hits[0]


def cmd_resume(args) -> int:
    """Continue a run: the last one here, or one named by an id prefix."""
    import argparse as _ap

    from agentctl.runtime import runs
    r = runs.find(args.id, workspace=Path.cwd())
    print(f"resuming {r.conversation_id[:8]}  ({r.state}, started "
          f"{_ts(r.started)})")
    print(f"  in        {r.workspace}")
    if r.task:
        print(f"  task      {r.task[:90]}")
    pool = bool(r.model and r.model.startswith("openai/pool"))
    ns = _ap.Namespace(
        task="", workspace=Path(r.workspace), model=args.model or r.model,
        base_url=None if pool else r.base_url, pool=pool and not args.model,
        source=None, resume=r.conversation_id, takeover=args.takeover,
        accept=args.accept, wait=args.wait, ledger=args.ledger,
        cost_ledger=getattr(args, "cost_ledger", DEFAULT_COST_LEDGER),
        allow_destructive=False, max_iterations=args.max_iterations,
        max_budget=None, record=None, replay=None, policy=None)
    return cmd_run(ns)


def _decide(args, decision: str) -> int:
    from agentctl.runtime.runner import AWAITING
    if (found := _find_effect(args, args.tool_call_id)) is None:
        return 2
    path, full = found
    with LedgerStore(path, holder="cli") as s:
        rec = s.lookup(full)
        if rec is None or rec.state is not EffectState.BLOCKED or \
                not (rec.error or "").startswith(AWAITING):
            what = rec.state.value if rec else "missing"
            print(f"{short_id(full)} is not waiting for approval ({what}). "
                  f"An effect whose OUTCOME is unknown is answered with "
                  f"`agentctl resolve`.", file=sys.stderr)
            return 2
        summary = (rec.error or "").split("): ", 1)[-1]
        s._fences[rec.conversation_id] = rec.fence_token   # the CLI holds no lease
        s.decide(rec, decision, summary)
    verb = "approved" if decision == "approve" else "denied"
    print(f"{short_id(full)} {verb}: {summary}")
    print(f"  continue the run, and the agent is told:  agentctl resume "
          f"{rec.conversation_id[:8]}")
    return 0


def cmd_approve(args) -> int:
    return _decide(args, "approve")


def cmd_deny(args) -> int:
    return _decide(args, "deny")


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

    if args.install_hook:
        from agentctl.control.keys import install_hook
        h = install_hook(".")
        print(f"installed {h}")
        print("  any commit containing one of YOUR keys is now refused.")
        print("  it compares against the keys you hold, not against a shape --")
        print("  a check that flags every placeholder gets ignored.")
        print()

    if args.init:
        from agentctl.control.keys import enclosing_repo
        p, created = write_template(path)
        print(f"{'wrote' if created else 'kept existing'} {p}")
        if (repo := enclosing_repo(p)):
            print(f"  added ignore rules to {repo / '.gitignore'} "
                  f"BEFORE writing it")
        else:
            print("  it is in no git repository, so nothing can commit it")
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
        # docs/0044 N9: this used to lead with a second key at the SAME
        # provider. Whether that is a second quota is unverified, and whether
        # it is allowed is unchecked (docs/0042 §4.C), so it is not advice.
        print()
        print("  One account is fine to start with. A daily cap on it stops")
        print("  work until it resets; a key at a second provider survives")
        print("  that, and an outage too:")
        for p in missing():
            if p.free_tier:
                print(f"    {p.name:<11} {p.console}")
        print()
        print("  Extra keys at the same provider (_2, _WORK ...) are accepted,")
        print("  but whether they add quota is unverified and may be against")
        print("  that provider's terms. Check them first (docs/0042 §4.C).")
    return 0


EXAMPLE_SUBAGENT = """---
name: reviewer
description: Reads code and reports what it finds. Cannot change anything.
model: inherit
tools:
  - read_file
max_iteration_per_run: 15
---

You are a careful reader. You can open files and nothing else -- no shell, no
writes. Answer the question you were asked, cite `path:line` for every claim,
and say plainly when you could not determine something rather than guessing.
"""


def cmd_subagent(args) -> int:
    """List or run read-only subagents.

    Read-only is the whole design, not a starter limitation. A subagent that
    cannot produce an effect needs none of the lease, ledger, probe and
    handoff work that multi-agent was priced at (`docs/0038` §4.2), which is
    why this one exists and a writing one does not.
    """
    from agentctl.runtime.subagent import (
        AGENTS_DIR, READ_ONLY_TOOLS, discover, rejection,
    )

    ws = Path(args.workspace)
    if args.init:
        d = ws / AGENTS_DIR
        d.mkdir(parents=True, exist_ok=True)
        f = d / "reviewer.md"
        if f.exists():
            print(f"{f} already exists; leaving it alone")
            return 0
        f.write_text(EXAMPLE_SUBAGENT, encoding="utf-8")
        print(f"wrote {f}")
        print(f"  run it:  agentctl subagent reviewer \"what does the gate do?\"")
        return 0

    defns = discover(ws)
    if not defns:
        print(f"no subagents in {ws / AGENTS_DIR}")
        print("  agentctl subagent --init   writes an example")
        return 0

    if not args.name:
        print(f"read-only subagents in {ws / AGENTS_DIR}\n")
        for d in defns:
            why = rejection(d)
            print(f"  {'--' if why else 'ok'}  {d.name:<18} "
                  f"{(d.description or '')[:46]}")
            if why:
                print(f"      REFUSED: {why.splitlines()[0]}")
        print(f"\n  They may hold only {sorted(READ_ONLY_TOOLS)} — no shell, no")
        print("  writes, no MCP. That is what lets them run outside the effect")
        print("  ledger: there is no effect to record.")
        return 0

    match = next((d for d in defns if d.name == args.name), None)
    if match is None:
        print(f"no subagent called {args.name!r}. "
              f"Have: {', '.join(d.name for d in defns)}", file=sys.stderr)
        return 2
    if (why := rejection(match)):
        print(why, file=sys.stderr)
        return 2
    if not args.task:
        print("give it something to do: agentctl subagent "
              f"{args.name} \"<question>\"", file=sys.stderr)
        return 2

    model = args.model
    if args.source:
        if not args.base_url:
            print("  --source needs a proxy to route through. "
                  "`agentctl models` explains the trade.", file=sys.stderr)
            return 2
        from agentctl.control.proxy import SOURCE_PREFIX, sources
        known = {r["source"] for r in sources()}
        if args.source not in known:
            print(f"  no source called {args.source!r}. "
                  f"You have: {', '.join(sorted(known)) or 'none'}",
                  file=sys.stderr)
            return 2
        model = f"openai/{SOURCE_PREFIX}{args.source}"

    from agentctl.runtime.subagent import run as run_subagent
    print(f"agentctl subagent {match.name}")
    out = run_subagent(match, args.task, workspace=ws, model=model,
                       base_url=args.base_url)
    print()
    print(out)
    return 0


def cmd_recon(args) -> int:
    """Fan a read-only question out across sources, split by scarcity.

    The split is the feature. An even one lets a source with a single quota
    set the pace for sources with six, which on this pool is the difference
    between x1.55 and x4.33 recon jobs per day (`docs/0040` sec 6.1). The plan
    is printed before anything is spent.
    """
    from agentctl.runtime.orchestrate import allocate, describe, fan_out
    from agentctl.runtime.subagent import discover, rejection

    ws = Path(args.workspace)
    defns = [d for d in discover(ws) if rejection(d) is None]
    match = next((d for d in defns if d.name == args.name), None)
    if match is None:
        have = ", ".join(d.name for d in defns) or "none"
        print(f"no read-only subagent called {args.name!r}. Have: {have}",
              file=sys.stderr)
        return 2

    items = [i for i in args.items if i.strip()]
    if not items:
        print("give it something to look at", file=sys.stderr)
        return 2

    sources = args.source or []
    if not sources:
        print("--source is required, at least twice -- a fan-out over one "
              "source is just a subagent.\n  `agentctl models` lists them.",
              file=sys.stderr)
        return 2
    if not args.base_url:
        print("--base-url is required: source groups live in the proxy's "
              "config.", file=sys.stderr)
        return 2

    legs = allocate(items, sources, ratio=_parse_ratio(args.ratio))
    print(f"agentctl recon {match.name}  ({len(items)} item(s))\n")
    print(describe(legs))
    total = sum(lg.requests for lg in legs)
    print(f"\n  {total} request(s) total, none of them effects.\n")
    if args.dry_run:
        print("  --dry-run: nothing dispatched.")
        return 0

    def announce(leg):
        mark = "!!" if leg.error else "ok"
        print(f"  {mark}  {leg.source:<14} "
              f"{leg.error or 'reported ' + str(len(leg.report or '')) + ' chars'}")

    fan_out(match, args.question, legs, workspace=str(ws),
            base_url=args.base_url, on_leg=announce)

    print()
    from agentctl.runtime.citations import describe as describe_cites
    from agentctl.runtime.citations import verify as verify_cites

    for leg in legs:
        if leg.report:
            print(f"---- {leg.source} ({len(leg.items)} item(s)) ----")
            print(leg.report)
            # A scout's report is a claim, not a finding. The first live run
            # returned a confident, cited, wrong answer (`docs/0039` §7), so
            # every citation is resolved against the workspace before the
            # report is presented as anything.
            print()
            print(describe_cites(verify_cites(leg.report, ws)))
            print()
    missing = [lg.source for lg in legs if lg.items and not lg.report]
    if missing:
        print(f"  INCOMPLETE: no report from {', '.join(missing)}. "
              f"The findings above cover only what the other legs read.")
    return 0


def _parse_ratio(raw: list[str] | None) -> dict[str, int] | None:
    """`--ratio gemini=1 --ratio mistral=6`, for a caller who measured."""
    if not raw:
        return None
    out = {}
    for pair in raw:
        name, _, n = pair.partition("=")
        if n.isdigit():
            out[name.strip()] = int(n)
    return out or None


def cmd_plugins(args) -> int:
    """What a Claude Code plugin would contribute, and what is refused.

    Default-deny with an itemised receipt (`docs/0010` §9.2). Read-only agent
    definitions are admitted; hooks, commands, skills and MCP servers are not,
    and are counted rather than silently dropped — a broker that quietly
    discarded half a plugin would leave you believing you had installed
    something you had not.
    """
    from agentctl.runtime.plugins import load

    info = load(args.path)
    if (err := info.get("error")):
        print(err, file=sys.stderr)
        return 2

    print(f"{info['name']} {info['version']}")
    if info["description"]:
        print(f"  {info['description']}")
    print(f"  {info['path']}\n")

    if info["admitted"]:
        print(f"  ADMITTED  {len(info['admitted'])} read-only agent(s)")
        for d in info["admitted"]:
            print(f"    ok  {d.name:<18} {(d.description or '')[:44]}")
    else:
        print("  ADMITTED  nothing")

    if info["rejected"]:
        print(f"\n  REJECTED  {len(info['rejected'])} agent(s) that could "
              f"change the world")
        for name, why in info["rejected"]:
            print(f"    --  {name:<18} {why.splitlines()[0][:60]}")

    if info["refused"]:
        print("\n  REFUSED   capabilities this project does not run")
        for cap, n, why in info["refused"]:
            print(f"    --  {cap:<18} {n} declared")
            for line in _wrap_plain(why, 58):
                print(f"          {line}")

    print("\n  Nothing here has been installed or run. This is the audit.")
    return 0


def _wrap_plain(text: str, width: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines


def cmd_models(args) -> int:
    """Choose a source. Every row says what choosing it gives up.

    `pool` is the default and the widest thing you can ask for. A source group
    is narrower on purpose, and narrower means an account-wide daily cap has
    less to fail over to -- which is the failure the multi-account design
    exists to escape (`docs/0033`). So the cost is printed beside every choice
    rather than left for you to discover at the cap.

    Without `--verify` this reports what is CONFIGURED, not what can serve. It
    says so, because six Cerebras keys authenticate happily and every
    completion returns "Payment required" (`docs/0034` §7).
    """
    from agentctl.control.proxy import POOL, sources

    rows = sources()
    if not rows:
        print("no provider keys in the environment. `agentctl keys --init`")
        return 1

    live: set[str] | None = None
    if args.verify:
        from agentctl.control.proxy import verified_providers
        print("  checking which sources can actually serve "
              "(one completion per model id)...\n")
        live, _ = verified_providers()

    total = sum(r["deployments"] for r in rows)
    accts = sum(r["accounts"] for r in rows)
    print(f"  {POOL:<22} {total:>3} deployments  {accts:>2} accounts   "
          f"the default: every free source at once")
    print(f"  {'':<22} {'':>3}              {'':>2}            "
          f"use this unless you have a reason not to\n")

    for r in rows:
        mark = "  "
        note = ""
        if live is not None:
            if r["source"] in live:
                mark = "ok"
            else:
                mark, note = "$$", "   cannot serve a request right now"
        acct = f"{r['accounts']:>2} accounts"
        if r.get("quotas", r["accounts"]) != r["accounts"]:
            acct = f"{r['accounts']:>2} keys/{r['quotas']} quota"
        print(f"  {mark} {r['group']:<22} {r['deployments']:>3} deployments  "
              f"{acct}   gives up {r['gives_up']}"
              f" of {total}{note}")
        for m in r["models"][:3]:
            print(f"       {m}")
        if len(r["models"]) > 3:
            print(f"       ... and {len(r['models']) - 3} more")

    if live is None:
        print("\n  These are the sources you hold KEYS for, not the ones that")
        print("  can serve. `agentctl models --verify` sends one completion")
        print("  each and marks the difference.")

    print(f"\n  Use one:  agentctl run \"...\" --source <name> "
          f"--base-url http://localhost:4000")
    print(f"  Or ask for the group directly:  --model openai/{POOL}-<name>")
    return 0


def cmd_dash(args) -> int:
    """Providers, failover, effects, spend and policy on one screen."""
    from agentctl.control.dash import collect, render, to_html

    data = collect(ledger=args.ledger, cost_ledger=args.cost_ledger,
                   refresh_quota=args.refresh_quota)
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
    """Run the managed proxy (up/down/status), or generate a config (no action)."""
    if args.action:
        from agentctl.control import proxyenv
        if args.action == "up":
            s = proxyenv.up(port=args.port, verify=args.verify)
            print(f"\n  route a run through it:  agentctl run \"...\" --pool")
            return 0 if s["answers"] else 1
        if args.action == "down":
            proxyenv.down()
            return 0
        s = proxyenv.status()
        print(f"  state     {s['state']}")
        print(f"  url       {proxyenv.url(s['port'])}  "
              f"({'answers' if s['answers'] else 'no answer'})")
        if s["pid"]:
            print(f"  pid       {s['pid']}")
        print(f"  log       {s['log']}")
        print(f"  env       {s['env']}")
        return 0 if s["state"] in ("running", "stopped") else 1

    from agentctl.control.proxy import accounts, available, write

    only = None
    drop: set[str] = set()
    if not args.verify:
        print("  --no-verify: this pool is built from credentials, not from "
              "what can serve.")
        print("    a deployment that 402s or 404s will end a run rather than "
              "failing over.\n")
    if args.verify:
        from agentctl.control.proxy import verified_providers
        print("  verifying providers (one completion per model id; paid skipped)...")
        only, report = verified_providers()
        for name, r in sorted(report.items()):
            flag = "ok  " if name in only else "--  "
            print(f"    {flag} {name:<12} {r.status:<11} {r.detail[:54]}")
        from agentctl.control.providers import BY_NAME
        drop = {f"{BY_NAME[n].prefix}{m}"
                for n, r in report.items() for m in r.gone}
        for m in sorted(drop):
            print(f"    left out     {m}  (the provider no longer serves it)")
        print()

    entries = [e for e in available()
               if (only is None or _provider_of(e[0]) in only)
               and e[1] not in drop]
    cfg, hook = write(args.out, only=only, drop_models=drop)
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
def _version() -> str:
    """The installed distribution's version. A bug report needs it.

    The distribution is `handcode`; the import package is `agentctl`
    (docs/0051 Stage 1). An install from before the rename is `agentctl`.
    """
    from importlib.metadata import PackageNotFoundError, version
    for dist in ("handcode", "agentctl"):
        try:
            return version(dist)
        except PackageNotFoundError:
            continue
    return "unknown"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="agentctl",
        description="Run a coding agent whose work survives crashes, restarts "
                    "and provider switches. New here: agentctl demo")
    p.add_argument("--version", action="version",
                   version=f"handcode {_version()} (the agentctl command; python "
                           f"{sys.version.split()[0]}, {sys.platform})")
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

    dm = sub.add_parser("demo", help="see a crash duplicate a commit, and agentctl "
                                     "prevent it. No key, no network, $0")
    dm.add_argument("--keep", action="store_true",
                    help="keep the demo's repos and logs, and print where")
    dm.set_defaults(fn=lambda a: __import__("agentctl.demo", fromlist=["run_demo"])
                    .run_demo(keep=a.keep))

    it = sub.add_parser("init", help="set up a key and a default model, once")
    it.add_argument("--provider", metavar="NAME",
                    help="the provider to use (default: the first you hold a "
                         "key for, free tiers first; asks if you hold none)")
    it.add_argument("--model", help="record this model instead of checking one")
    it.add_argument("--no-verify", dest="verify", action="store_false",
                    help="do not send the one checking completion")
    it.add_argument("--key-stdin", action="store_true",
                    help="read the key from stdin (for scripts), never echoed")
    it.add_argument("--check-paid", action="store_true",
                    help="allow the check to call a PAID provider (a few tokens)")
    it.set_defaults(fn=cmd_init)

    sub.add_parser("status", help="recent runs, and what needs you").set_defaults(fn=cmd_status)

    rs = sub.add_parser("resume", help="continue the last run here, or one by id")
    rs.add_argument("id", nargs="?", help="a conversation id or its first "
                                         "characters (default: the latest run "
                                         "in this directory, else anywhere)")
    rs.add_argument("--takeover", action="store_true",
                    help="take it from a run that may still be alive")
    rs.add_argument("--accept", metavar="CMD", help="check the result, as for run")
    rs.add_argument("--wait", metavar="DURATION", help="as for run")
    rs.add_argument("--model", help="continue on a different model")
    rs.add_argument("--max-iterations", type=int, default=30)
    rs.set_defaults(fn=cmd_resume)

    for name, fn, what in (("approve", cmd_approve, "let a queued action run"),
                           ("deny", cmd_deny, "refuse a queued action")):
        ap_ = sub.add_parser(name, help=f"{what} (the agent is told on resume)")
        ap_.add_argument("tool_call_id", help="its id, or the first characters")
        ap_.set_defaults(fn=fn)

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
    rn.add_argument("--model", help="litellm model id. Default: AGENTCTL_MODEL, "
                                    "then ~/.agentctl/config.toml (`agentctl "
                                    "init`), then your first provider's default")
    rn.add_argument("--base-url", help="an OpenAI-compatible endpoint, e.g. your "
                                       "proxy. Default: AGENTCTL_BASE_URL, then "
                                       "config.toml")
    rn.add_argument("--pool", action="store_true",
                    help="route through the managed proxy pool, starting it "
                         "if it is not running (`agentctl proxy up`)")
    rn.add_argument("--source", metavar="NAME",
                    help="route this run to ONE provider (see `agentctl "
                         "models`). Narrower than the default pool, so a "
                         "daily cap has less to fail over to. Needs "
                         "--base-url.")
    rn.add_argument("--accept", metavar="CMD",
                    help="a command agentctl runs itself when the agent is "
                         "done, e.g. \"python -m pytest -q\". Exit 0 = PASS. "
                         "Without it the outcome is reported as not checked")
    rn.add_argument("--wait", metavar="DURATION",
                    help="if a provider rate-limits the run, wait up to this "
                         "long (90s, 30m, 2h) for the limit to reset and "
                         "resume automatically")
    rn.add_argument("--max-iterations", type=int, default=30)
    rn.add_argument("--max-budget", type=float, help="hard USD ceiling for the run")
    rn.add_argument("--resume", help="conversation id to continue")
    rn.add_argument("--takeover", action="store_true",
                    help="with --resume: take the conversation from a run "
                         "that may still be alive. Not needed after a crash "
                         "on this machine -- a dead holder is detected.")
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
    ky.add_argument("--install-hook", action="store_true",
                    help="install a git pre-commit hook that refuses any "
                         "commit containing one of your keys")
    ky.add_argument("--check-paid", action="store_true",
                    help="also send one tiny completion to PAID providers. "
                         "This costs money, so it is off by default.")
    ky.add_argument("--check", action="store_true",
                    help="test every key against the provider. Uses metadata "
                         "endpoints, so it costs no tokens and no quota.")
    ky.set_defaults(fn=cmd_keys)

    rc = sub.add_parser("recon", help="fan a read-only question across "
                                     "sources, split by quota scarcity")
    rc.add_argument("name", help="which read-only subagent")
    rc.add_argument("question", help="what to find out")
    rc.add_argument("items", nargs="*", help="files or areas to divide up")
    rc.add_argument("--source", action="append", metavar="NAME",
                    help="a source to use. Repeat it; see `agentctl models`.")
    rc.add_argument("--ratio", action="append", metavar="NAME=N",
                    help="override a source's share, if you have measured "
                         "its real limits today")
    rc.add_argument("--workspace", type=Path, default=Path("."))
    rc.add_argument("--base-url", help="the proxy. Required: source groups "
                                       "live in its config.")
    rc.add_argument("--dry-run", action="store_true",
                    help="print the plan and dispatch nothing")
    rc.set_defaults(fn=cmd_recon)

    pl = sub.add_parser("plugins", help="what a Claude Code plugin would "
                                       "contribute, and what is refused")
    pl.add_argument("path", help="the plugin directory")
    pl.set_defaults(fn=cmd_plugins)

    sa = sub.add_parser("subagent", help="read-only subagents: list one, run one")
    sa.add_argument("name", nargs="?", help="which one (omit to list)")
    sa.add_argument("task", nargs="?", help="what to ask it")
    sa.add_argument("--workspace", type=Path, default=Path("."),
                    help="directory it reads from (default: cwd)")
    sa.add_argument("--init", action="store_true",
                    help="write an example definition and exit")
    sa.add_argument("--model", help="model for a definition saying `inherit`")
    sa.add_argument("--base-url", help="an OpenAI-compatible endpoint")
    sa.add_argument("--source", metavar="NAME",
                    help="route it to ONE provider through the proxy, with "
                         "failover across that provider's accounts. Needs "
                         "--base-url. See `agentctl models`.")
    sa.set_defaults(fn=cmd_subagent)

    mo = sub.add_parser("models", help="sources you can route to, and what "
                                       "choosing one gives up")
    mo.add_argument("--verify", action="store_true",
                    help="send one completion per source to find out which "
                         "can actually serve. Costs a request each.")
    mo.set_defaults(fn=cmd_models)

    da = sub.add_parser("dash", help="one screen: providers, effects, spend, policy")
    da.add_argument("--html", metavar="OUT",
                    help="write a self-contained HTML page instead")
    da.add_argument("--refresh-quota", action="store_true",
                    help="also call openrouter.ai for each OpenRouter "
                         "account's remaining free-tier quota. One metadata "
                         "request per account, zero tokens -- never done "
                         "automatically, only on this flag.")
    da.set_defaults(fn=cmd_dash)

    px = sub.add_parser("proxy", help="run the managed LiteLLM pool (up / down "
                                      "/ status), or generate a config")
    px.add_argument("action", nargs="?", choices=("up", "down", "status"),
                    help="manage the proxy agentctl runs in its own environment "
                         "(~/.agentctl/proxy-env). Omit to only write a config")
    px.add_argument("--port", type=int, default=4000)
    px.add_argument("--out", default=".", help="where to write the config "
                                               "(generate-only mode)")
    # Verification is ON by default. `docs/0034` §7 measured what an
    # unverified pool costs: six Cerebras keys authenticate and return 402 on
    # every completion, litellm does not treat 402 as retryable, and a live
    # run died on one. Generating a config known to contain deployments that
    # cannot serve is not a default worth having -- the flag now buys speed,
    # not correctness, and says so.
    px.add_argument("--no-verify", dest="verify", action="store_false",
                    default=True,
                    help="skip the one-completion-per-provider check. Faster, "
                         "and the pool may contain deployments that cannot "
                         "serve -- a 402 from one of them is not retryable "
                         "and will end a run.")
    px.set_defaults(fn=cmd_proxy)

    dr = sub.add_parser("doctor", help="check everything before you run")
    dr.add_argument("--workspace", help="also check this workspace")
    dr.add_argument("--offline", action="store_true",
                    help="skip the provider account probe")
    dr.set_defaults(fn=cmd_doctor)

    po = sub.add_parser("policy", help="compile and inspect the policy")
    po.add_argument("source", nargs="?",
                    help="policy.yaml to compile; omit to show the compiled one")
    # The package's own copy, not a cwd-relative path: that only resolved from
    # the root of a clone (docs/0044 N14).
    from agentctl.kernel.policy import DEFAULT_POLICY
    po.add_argument("--out", type=Path, default=DEFAULT_POLICY,
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
    # The SDK prints a ten-line banner on import, on every command -- `doctor`,
    # `keys`, `dash` -- ending "Report a bug: github.com/OpenHands/...", which
    # is the wrong place for an agentctl bug (docs/0031, 0044 N10). Set before
    # anything imports it; an explicit value in the shell still wins.
    import os
    os.environ.setdefault("OPENHANDS_SUPPRESS_BANNER", "1")
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
