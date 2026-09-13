r"""Compile `policy.yaml` into the flat artifact the kernel reads. M7.

The point is not the file format. It is **where the errors happen**.

`docs/0008` R2 says the kernel must keep working when the control plane is
dead, and `docs/0012` §5.2 says policy compiles to a flat lookup artifact with
no evaluation in-band. Together those mean every question a policy could raise
-- is that pool defined? is that effect class real? is a daily cap smaller than
a per-task cap? -- has to be answered **here**, out of band, where a person is
watching, and never in the middle of a run where the only available response is
to fail closed and stop the work.

A compiler that merely reformats YAML would be pointless. This one refuses:

    pool "paid" is not defined (escalate_to.pool)
    daily_usd 0.50 is below per_task_usd 2.00 -- the daily cap can never bind
    unknown effect class "DESCTRUCTIVE" -- did you mean DESTRUCTIVE?

The third is the one that matters most. A typo in an effect class is not a
syntax error and would compile cleanly into an artifact where `DESTRUCTIVE`
simply has no rule -- so the most dangerous class silently stops requiring
approval. Policy that fails **open** on a typo is worse than no policy, because
it reads like protection. So unknown keys are errors, never warnings.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import yaml

from agentctl.kernel.ledger.models import EffectClass

# What an effect rule is allowed to say. Extending this means teaching the
# enforcement layer the new verb first -- a rule nothing implements would
# compile and then do nothing, which is the failure mode this file exists to
# prevent.
EFFECT_RULES = {"require_human_approval", "reconcile_or_block", "allow", "block"}
ON_EXCEEDED = {"block", "warn"}
ON_UNPRICED = {"block", "warn", "ignore"}
BUDGET_SCOPES = {"daily_usd", "per_task_usd"}


class PolicyError(ValueError):
    """A policy that cannot be compiled. Carries every problem, not the first."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(f"  - {p}" for p in problems))


def compile_policy(source: str | Path | dict) -> dict:
    """Validate and flatten. Raises `PolicyError` listing every problem."""
    if isinstance(source, dict):
        raw, digest = source, ""
    else:
        text = Path(source).read_text(encoding="utf-8")
        raw = yaml.safe_load(text) or {}
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    if not isinstance(raw, dict):
        raise PolicyError(["the policy file is not a mapping"])

    problems: list[str] = []
    out: dict[str, Any] = {
        "version": raw.get("version", 1),
        "compiled_at": time.time(),
        "source_sha256": digest,
    }

    pools = _pools(raw, problems)
    out["routing"] = _routing(raw, pools, problems)
    out["budget"] = _budget(raw, problems)
    out["effects"] = _effects(raw, problems)
    out["tiering"] = _tiering(raw, problems)

    if problems:
        raise PolicyError(problems)
    return out


# ── sections ───────────────────────────────────────────────────────────
def _pools(raw: dict, problems: list[str]) -> dict[str, list[str]]:
    pools = raw.get("pools") or {}
    if not isinstance(pools, dict):
        problems.append("`pools` must be a mapping of name -> [deployments]")
        return {}
    out = {}
    for name, members in pools.items():
        if not isinstance(members, list) or not members:
            problems.append(f"pool {name!r} must be a non-empty list")
            continue
        if len(set(members)) != len(members):
            problems.append(f"pool {name!r} lists the same deployment twice")
        out[str(name)] = [str(m) for m in members]
    return out


def _routing(raw: dict, pools: dict, problems: list[str]) -> dict:
    routing = raw.get("routing") or {}
    if not isinstance(routing, dict):
        problems.append("`routing` must be a mapping")
        return {}

    default = routing.get("default_pool")
    if default is not None and str(default) not in pools:
        problems.append(f"pool {str(default)!r} is not defined "
                        f"(routing.default_pool)")

    escalation: dict[str, Any] = {}
    esc = routing.get("escalate_to") or {}
    if esc:
        target = esc.get("pool")
        if target is None:
            problems.append("routing.escalate_to needs a `pool`")
        elif str(target) not in pools:
            problems.append(f"pool {str(target)!r} is not defined "
                            f"(routing.escalate_to.pool)")
        if str(target) == str(default):
            problems.append("routing.escalate_to.pool is the default pool, "
                            "so escalation would change nothing")
        when = esc.get("when") or {}
        after = when.get("or_after_failures")
        if after is not None and (not isinstance(after, int) or after < 1):
            problems.append("routing.escalate_to.when.or_after_failures must "
                            "be a positive integer")
        escalation = {
            "pool": str(target) if target else None,
            "requires_capability": [str(c) for c in
                                    (when.get("requires_capability") or [])],
            "after_failures": after,
            # `docs/0002` §5: never silently spend. The DEFAULT is to confirm,
            # so omitting the key cannot accidentally authorise paid traffic.
            "require_confirmation": bool(esc.get("require_confirmation", True)),
        }

    return {"default_pool": str(default) if default else None,
            "pools": pools, "escalation": escalation}


def _budget(raw: dict, problems: list[str]) -> dict:
    if "budget" not in raw:
        return {}                   # no budget is a valid choice, not an error
    budget = raw.get("budget") or {}
    if not isinstance(budget, dict):
        problems.append("`budget` must be a mapping")
        return {}

    out: dict[str, Any] = {}
    for key in budget:
        if key not in BUDGET_SCOPES | {"on_exceeded", "on_unpriced"}:
            problems.append(f"unknown budget key {key!r} "
                            f"(allowed: {', '.join(sorted(BUDGET_SCOPES))}, "
                            f"on_exceeded, on_unpriced)")

    for scope in BUDGET_SCOPES:
        if (v := budget.get(scope)) is not None:
            try:
                amount = float(v)
            except (TypeError, ValueError):
                problems.append(f"budget.{scope} must be a number, got {v!r}")
                continue
            if amount <= 0:
                problems.append(f"budget.{scope} must be positive, got {amount}")
            out[scope] = amount

    daily, per_task = out.get("daily_usd"), out.get("per_task_usd")
    if daily is not None and per_task is not None and daily < per_task:
        # Compiles fine and is incoherent: one task may exceed the whole day.
        problems.append(f"budget.daily_usd {daily} is below per_task_usd "
                        f"{per_task} -- the daily cap can never bind")

    on_exceeded = str(budget.get("on_exceeded", "block"))
    if on_exceeded not in ON_EXCEEDED:
        problems.append(f"budget.on_exceeded must be one of "
                        f"{sorted(ON_EXCEEDED)}, got {on_exceeded!r}")
    out["on_exceeded"] = on_exceeded

    on_unpriced = str(budget.get("on_unpriced", "warn"))
    if on_unpriced not in ON_UNPRICED:
        problems.append(f"budget.on_unpriced must be one of "
                        f"{sorted(ON_UNPRICED)}, got {on_unpriced!r}")
    out["on_unpriced"] = on_unpriced

    if not (daily or per_task):
        problems.append("`budget` is present but sets no cap; remove it or "
                        "add daily_usd / per_task_usd")
    return out


def _effects(raw: dict, problems: list[str]) -> dict[str, str]:
    effects = raw.get("effects") or {}
    if not isinstance(effects, dict):
        problems.append("`effects` must be a mapping of class -> rule")
        return {}

    known = {e.value for e in EffectClass}
    out = {}
    for key, rule in effects.items():
        name = str(key).upper()
        if name not in known:
            # NOT a warning. A typo here fails OPEN -- the real class keeps no
            # rule and silently stops requiring approval.
            hint = _nearest(name, known)
            problems.append(f"unknown effect class {str(key)!r}"
                            + (f" -- did you mean {hint}?" if hint else "")
                            + f" (known: {', '.join(sorted(known))})")
            continue
        if str(rule) not in EFFECT_RULES:
            problems.append(f"unknown rule {str(rule)!r} for {name} "
                            f"(known: {', '.join(sorted(EFFECT_RULES))})")
            continue
        out[name] = str(rule)
    return out


def _tiering(raw: dict, problems: list[str]) -> dict[str, str]:
    tiering = raw.get("tiering") or {}
    if not isinstance(tiering, dict):
        problems.append("`tiering` must be a mapping")
        return {}
    out = {}
    for activity, spec in tiering.items():
        tier = spec.get("min_tier") if isinstance(spec, dict) else spec
        if not tier:
            problems.append(f"tiering.{activity} needs a `min_tier`")
            continue
        out[str(activity)] = str(tier)
    return out


def _nearest(word: str, candidates: set[str]) -> str | None:
    """A cheap did-you-mean. A typo should cost a second, not an afternoon."""
    import difflib
    hits = difflib.get_close_matches(word, sorted(candidates), n=1, cutoff=0.6)
    return hits[0] if hits else None


# ── writing ────────────────────────────────────────────────────────────
def compile_to(source: str | Path, out_path: str | Path) -> Path:
    compiled = compile_policy(source)
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(compiled, indent=2, sort_keys=True) + "\n",
                 encoding="utf-8")
    return p
