r"""Read a compiled policy. Lookups only — no evaluation in-band.

`docs/0012` §5.2: *"compiles to a flat lookup artifact the kernel reads from
disk -- no evaluation logic in-band."* That sentence is the whole design, and
it is the same trick as the capability matrix: the control plane does the
thinking, writes an artifact, and the kernel reads it. A malformed policy fails
where a human is watching, not in the middle of a run.

So there is no YAML here, no schema, no merge, no defaults resolution, and no
`if` on a pool name. Those live in `control/policy/compile.py`. If this module
ever needs to *decide* something, the compiler should have decided it.

## Budget, and why a cap can lie

`docs/0021` §5 found litellm reports cost `0.0` for endpoints it cannot price,
indistinguishable from a call that was genuinely free. A cap compared against
measured spend therefore **under-blocks**: the real figure is higher than the
one being checked, always in the direction of spending more than intended.

The guard refuses to hide that. Every verdict carries the pricing coverage it
was computed from, and what to do about incomplete coverage is a decision the
policy states out loud (`on_unpriced`) rather than one this module makes
quietly. The default is `warn`, which is fail-open — consistent with
`docs/0008` §6.5, where cost and routing fail open and only effect decisions
fail closed. Choosing `block` is available and is a real trade: it stops work
when measurement is incomplete, which on a free-tier pool is most of the time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_POLICY = (
    Path(__file__).resolve().parent.parent
    / "control" / "policy" / "data" / "policy.compiled.json"
)


@dataclass(frozen=True)
class BudgetVerdict:
    """What the budget says, and how much to trust it."""
    allowed: bool
    reason: str
    scope: str = ""                 # "per_task" | "daily"
    spent_usd: float = 0.0
    limit_usd: float | None = None
    coverage: float = 1.0           # share of calls that could be priced

    @property
    def trustworthy(self) -> bool:
        return self.coverage >= 1.0

    def describe(self) -> str:
        if self.limit_usd is None:
            return "no budget configured"
        base = f"${self.spent_usd:.4f} of ${self.limit_usd:.2f} ({self.scope})"
        if not self.trustworthy:
            # Never print a spend figure without saying what it omits.
            return (f"{base} — but only {self.coverage:.0%} of calls could be "
                    f"priced, so the real spend is HIGHER")
        return base


class Policy:
    """A compiled policy artifact. Every method is a lookup."""

    def __init__(self, data: dict | None = None):
        self._d: dict = data or {}

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Policy":
        p = Path(path or DEFAULT_POLICY)
        if not p.exists():
            raise FileNotFoundError(
                f"no compiled policy at {p}\n"
                f"  compile one:  agentctl policy compile <policy.yaml>")
        return cls(json.loads(p.read_text(encoding="utf-8")))

    @classmethod
    def empty(cls) -> "Policy":
        """No policy. Every lookup returns nothing, and nothing is enforced."""
        return cls({})

    def __bool__(self) -> bool:
        return bool(self._d)

    # ── effects ────────────────────────────────────────────────────────
    def effect_rule(self, effect_class: str) -> str | None:
        """e.g. DESTRUCTIVE -> "require_human_approval"."""
        return (self._d.get("effects") or {}).get(str(effect_class))

    def requires_approval(self, effect_class: str) -> bool:
        return self.effect_rule(effect_class) == "require_human_approval"

    # ── budget ─────────────────────────────────────────────────────────
    def limit(self, scope: str) -> float | None:
        return (self._d.get("budget") or {}).get(f"{scope}_usd")

    @property
    def on_exceeded(self) -> str:
        return (self._d.get("budget") or {}).get("on_exceeded", "block")

    @property
    def on_unpriced(self) -> str:
        return (self._d.get("budget") or {}).get("on_unpriced", "warn")

    def check_budget(self, spent_usd: float, scope: str = "per_task",
                     coverage: float = 1.0) -> BudgetVerdict:
        """Is there room left? The spend is SUPPLIED, never fetched.

        The cost ledger lives in the control plane and the kernel may not
        import it (`docs/0008` R2), which is not an inconvenience here but the
        right shape: a guard that queried a database in-band would fail when
        the control plane is down, and this must not.
        """
        limit = self.limit(scope)
        if limit is None:
            return BudgetVerdict(True, "no budget configured", scope,
                                 spent_usd, None, coverage)

        v = BudgetVerdict(spent_usd < limit, "", scope, spent_usd, limit, coverage)

        if spent_usd >= limit:
            if self.on_exceeded == "warn":
                return BudgetVerdict(True, f"over budget ({v.describe()}), "
                                     f"policy says warn", scope, spent_usd,
                                     limit, coverage)
            return BudgetVerdict(False, f"budget exceeded: {v.describe()}",
                                 scope, spent_usd, limit, coverage)

        # Under the cap on paper. If the measurement is incomplete the real
        # figure is higher, and saying nothing would be the wrong silence.
        if coverage < 1.0 and self.on_unpriced == "block":
            return BudgetVerdict(
                False,
                f"only {coverage:.0%} of calls could be priced and policy says "
                f"block; measured {v.describe()}",
                scope, spent_usd, limit, coverage)

        return BudgetVerdict(True, v.describe(), scope, spent_usd, limit,
                             coverage)

    # ── routing (read-only; the compiler resolved it) ───────────────────
    @property
    def default_pool(self) -> str | None:
        return (self._d.get("routing") or {}).get("default_pool")

    def pool(self, name: str) -> list[str]:
        return list(((self._d.get("routing") or {}).get("pools") or {}).get(name, []))

    @property
    def escalation(self) -> dict[str, Any]:
        return dict((self._d.get("routing") or {}).get("escalation") or {})

    @property
    def source_sha256(self) -> str:
        """Which policy.yaml this was compiled from. For `agentctl policy show`."""
        return self._d.get("source_sha256", "")
