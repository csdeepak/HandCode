r"""Fan a read-only recon job out across sources, by scarcity.

`docs/0040` §6.1: **allocate work inversely to quota scarcity, not evenly.**
That single scheduling choice is the difference between ×1.55 and ×4.33 more
recon tasks per day on the owner's pool, with no extra quota bought. An even
split puts the same load on a leg with one allowance as on a leg with six, and
the one-allowance leg then decides the throughput of the whole job.

## Why this allocates by quota count and not by rate limit

The obvious allocator divides work by each source's requests-per-day. This one
cannot, and the reason is a rule rather than an oversight:
`control/providers.py` deliberately records no rate limits, because they go
stale within weeks and a confidently wrong number is worse than none.

So the allocator uses the one fact the registry *will* vouch for — how many
**independent quotas** a source has (`providers.quotas_for`) — and splits in
proportion to that. It is structural, it does not rot, and on the measured
pool it recovers most of the available gain:

    Gemini 1 quota : Mistral 6 quotas  ->  12 files split 2 / 10
                                           ×3.61 of the ×4.33 ceiling

Reaching the last 20% needs each source's real RPD, which is exactly the
number this project refuses to hardcode. `ratio=` accepts one if the caller
has measured it today.

## Sequential, deliberately

`docs/0039` §5 records that subagent concurrency is unproven: the two globals
that raced are fixed and three further candidates were refuted, but nothing
exercises the concurrent path. `research/phase-10-5`'s build order puts
sequential fan-out before concurrent for that reason. Concurrency is a change
to this file only, once something tests it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Leg:
    """One source's share of the job, and what came back."""
    source: str
    quotas: int
    items: list[str] = field(default_factory=list)
    report: str | None = None
    error: str | None = None

    @property
    def requests(self) -> int:
        """One request per item, plus the report it ends with."""
        return len(self.items) + 1 if self.items else 0


def weights(sources: list[str], ratio: dict[str, int] | None = None,
            env: dict | None = None) -> dict[str, int]:
    """How much work each source should carry, relatively.

    Defaults to its independent quota count. `ratio` overrides per source, for
    a caller who has measured real limits and wants to use them — pass the
    numbers, not a promise that they are current.
    """
    from agentctl.control.providers import BY_NAME, quotas_for

    out: dict[str, int] = {}
    for name in sources:
        if ratio and name in ratio:
            out[name] = max(int(ratio[name]), 0)
            continue
        p = BY_NAME.get(name)
        out[name] = quotas_for(p, env) if p is not None else 1
    return out


def allocate(items: list[str], sources: list[str],
             ratio: dict[str, int] | None = None,
             env: dict | None = None) -> list[Leg]:
    """Split `items` across `sources` in proportion to their quotas.

    Largest-remainder, so the split is exact rather than drifting by rounding,
    and deterministic — the same inputs always give the same plan, which is
    what makes a fan-out reproducible enough to compare two runs.

    A source with no quota gets no work. A source that *has* quota gets at
    least one item, because a leg with zero items still costs a report request
    and returns nothing: paying one request to learn nothing is strictly worse
    than not dispatching it, so it is dropped instead.
    """
    w = weights(sources, ratio, env)
    live = [s for s in sources if w.get(s, 0) > 0]
    if not items or not live:
        return [Leg(s, w.get(s, 0)) for s in sources]

    # More legs than items would leave some carrying nothing. Keep the
    # highest-weighted, so a scarce leg is dropped before a plentiful one.
    if len(live) > len(items):
        live = sorted(live, key=lambda s: (-w[s], s))[:len(items)]

    total = sum(w[s] for s in live)
    exact = {s: len(items) * w[s] / total for s in live}
    base = {s: max(int(exact[s]), 1) for s in live}

    # Largest remainder, then trim from the most plentiful leg if the
    # one-item floor overshot.
    short = len(items) - sum(base.values())
    order = sorted(live, key=lambda s: (-(exact[s] - int(exact[s])), s))
    i = 0
    while short > 0:
        base[order[i % len(order)]] += 1
        short -= 1
        i += 1
    while short < 0:
        victim = max((s for s in live if base[s] > 1),
                     key=lambda s: (w[s], s), default=None)
        if victim is None:
            break
        base[victim] -= 1
        short += 1

    legs, cut = [], 0
    for s in sources:
        n = base.get(s, 0)
        legs.append(Leg(s, w.get(s, 0), items[cut:cut + n]))
        cut += n
    return legs


def describe(legs: list[Leg]) -> str:
    """The plan, and why it is uneven. Printed before anything is spent."""
    live = [lg for lg in legs if lg.items]
    if not live:
        return "  nothing to dispatch"
    out = []
    for lg in legs:
        if not lg.items:
            why = "no quota" if not lg.quotas else "no share at this size"
            out.append(f"  --  {lg.source:<14} {why}")
            continue
        out.append(f"  ->  {lg.source:<14} {len(lg.items):>2} item(s), "
                   f"{lg.requests:>2} request(s)   "
                   f"{lg.quotas} quota(s)")
    scarce = min(live, key=lambda lg: lg.quotas)
    rich = max(live, key=lambda lg: lg.quotas)
    if scarce.quotas != rich.quotas:
        # ASCII only in printed output. Non-ASCII in a rendered string has
        # broken this project on a cp437 console five times; the dashboard
        # carries a test for exactly this.
        out.append(f"      {scarce.source} carries less because it has "
                   f"{scarce.quotas} quota(s) to {rich.source}'s {rich.quotas} "
                   f"-- an even split would let it set the pace for all of "
                   f"them (docs/0040 sec 6.1).")
    return "\n".join(out)


def fan_out(definition: Any, question: str, legs: list[Leg], *,
            workspace: str = ".", base_url: str | None = None,
            runner: Callable[..., str] | None = None,
            on_leg: Callable[[Leg], None] | None = None) -> list[Leg]:
    """Run each leg's scout in turn, filling in `report` or `error`.

    Sequential. One leg failing does not stop the others — a recon job that
    loses a scout should return what the rest found, clearly short, rather
    than nothing at all. The caller sees which legs are missing because
    `error` is set, not because the report is quietly thinner.
    """
    from agentctl.control.proxy import SOURCE_PREFIX

    from .subagent import run as run_subagent

    run = runner or run_subagent
    for leg in legs:
        if not leg.items:
            continue
        task = (f"{question}\n\nLook only at these, and report on them:\n"
                + "\n".join(f"  - {i}" for i in leg.items))
        try:
            leg.report = run(
                definition, task, workspace=workspace,
                model=f"openai/{SOURCE_PREFIX}{leg.source}" if base_url else None,
                base_url=base_url)
        except Exception as e:                          # noqa: BLE001
            leg.error = f"{type(e).__name__}: {e}"
        if on_leg is not None:
            on_leg(leg)
    return legs
