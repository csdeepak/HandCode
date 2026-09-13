r"""M7 acceptance: the budget cap actually blocks, and escalation asks first.

`docs/0012` §7 set exactly that bar. A policy that parses is not a policy that
binds, so this exercises the enforcement path rather than the compiler:

    1. a policy over its daily cap STOPS the run before anything happens
    2. the same policy under its cap does not
    3. a model outside the default pool ASKS before spending, and "no" stops it
    4. a policy that does not compile stops the run, naming every problem
    5. an unpriced ledger makes the spend figure a lower bound, and says so

Zero cost: no run here ever reaches a provider. The check is that policy
refuses BEFORE the agent starts, which is the only place a budget cap can be
worth anything -- a check that runs after the work is an audit, not a cap.

    python run_policy.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

RESULTS = HERE / "results" / "policy.json"

POLICY = """
version: 1
pools:
  free_tier: [openrouter/free-model]
  paid: [anthropic/sonnet]
routing:
  default_pool: free_tier
  escalate_to:
    pool: paid
    require_confirmation: true
budget:
  daily_usd: 1.00
  per_task_usd: 0.50
  on_exceeded: block
  on_unpriced: warn
effects:
  destructive: require_human_approval
"""


def _cost_ledger(path: Path, cost: float, priced: bool = True) -> Path:
    """A cost ledger with one recorded call, so the daily total is known."""
    from agentctl.control.cost import CostLedger

    with CostLedger(path) as c:
        c.ingest_record({
            "model": "openrouter/free-model", "deployment": "d1",
            "trace_id": "t1", "conversation_id": "c1",
            "prompt_tokens": 100, "completion_tokens": 10,
            "cost": cost if priced else 0.0,
            "ts": time.time(),
        })
    return path


def main() -> int:
    from agentctl.control.policy import PolicyError, compile_policy
    from agentctl.kernel.policy import Policy
    from agentctl.runtime.runner import _enforce_before_spending, _load_policy

    root = Path(tempfile.mkdtemp(prefix="m7_policy_"))
    src = root / "policy.yaml"
    src.write_text(POLICY, encoding="utf-8")
    pol = Policy(compile_policy(src))

    checks: dict[str, bool] = {}
    ev: dict = {}

    # 1. over the daily cap -> the run never starts
    over = _cost_ledger(root / "over.db", cost=1.50)
    try:
        _enforce_before_spending(pol, "openrouter/free-model", over,
                                 None, False, verbose=False)
        checks["over budget stops the run"] = False
    except SystemExit as e:
        ev["refusal"] = str(e)
        checks["over budget stops the run"] = "budget exceeded" in str(e)

    # 2. under the cap -> it proceeds
    under = _cost_ledger(root / "under.db", cost=0.10)
    try:
        _enforce_before_spending(pol, "openrouter/free-model", under,
                                 None, False, verbose=False)
        checks["under budget proceeds"] = True
    except SystemExit as e:
        ev["unexpected_refusal"] = str(e)
        checks["under budget proceeds"] = False

    # 3. a model outside the default pool asks, and "no" stops it
    import builtins
    asked: list[str] = []
    real_input = builtins.input
    builtins.input = lambda prompt="": (asked.append(prompt) or "n")
    try:
        _enforce_before_spending(pol, "anthropic/sonnet", under,
                                 None, False, verbose=False)
        checks["escalation asks first"] = False
    except SystemExit as e:
        checks["escalation asks first"] = bool(asked) and "refused" in str(e)
        ev["escalation_refusal"] = str(e)
    finally:
        builtins.input = real_input

    # 4. a policy that does not compile stops the run, listing every problem
    bad = root / "bad.yaml"
    bad.write_text("pools: {free: [a]}\n"
                   "routing: {default_pool: nope}\n"
                   "effects: {desctructive: require_human_approval}\n",
                   encoding="utf-8")
    try:
        _load_policy(bad)
        checks["a broken policy stops the run"] = False
    except SystemExit as e:
        msg = str(e)
        ev["compile_refusal"] = msg
        checks["a broken policy stops the run"] = (
            "not defined" in msg and "did you mean DESTRUCTIVE" in msg)

    # 5. an unpriced call makes the figure a lower bound, and says so
    blind = _cost_ledger(root / "blind.db", cost=0.0, priced=False)
    from agentctl.control.cost import CostLedger
    with CostLedger(blind) as c:
        t = c.totals(since=time.time() - 86400)
    v = pol.check_budget(t.cost_usd, "daily", t.coverage)
    ev["unpriced_verdict"] = v.describe()
    checks["an unpriced spend is reported as a lower bound"] = (
        not v.trustworthy and "HIGHER" in v.describe())

    # 6. the policy turns the destructive confirmation on by itself
    checks["policy requires approval for DESTRUCTIVE"] = \
        pol.requires_approval("DESTRUCTIVE")

    out = {"experiment": "0009-m7-policy", "ts": time.time(),
           "verdict": "PASS" if all(checks.values()) else "FAIL",
           "evidence": {**ev, "checks": checks}}
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(out, indent=2), encoding="utf-8")

    for name, ok in checks.items():
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    print(f"\n  refusal: {ev.get('refusal', '')[:90]}")
    print(f"  VERDICT: {out['verdict']}")
    return 0 if out["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
