---
Number:        0022
Title:         Integration Complete — Full Stack and the Cost Ledger
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0018, 0019, 0020, 0021
---

# 0022 — Integration Complete

Two things closed: the full stack has now run together, and spend is
attributable to work.

**170 tests · 8 verification checks · zero cost.**

---

## 1. The gap this closes

Every seam was proven **alone**. Seam A with direct HTTP to a proxy
(`docs/0021`); Seams B and C with OpenHands talking straight to a mock
(`docs/0016`–`0018`). `docs/0021` §8 admitted it: *"No OpenHands-through-proxy
run."*

That was the integration, and it had never happened.

```
OpenHands agent
    -> LiteLLM proxy          Seam A: hook, turn-pinning, telemetry
        -> two mock accounts
    + agentctl gate           Seams B and C: ledger, probes, substitution
```

`experiments/0006-full-stack/` runs all of it, crashes the agent mid-commit,
and resumes through the same proxy. It passed on the first attempt:

```
commits_before          1
commits_after_crash     2
commits_after_resume    2      <- no duplicate
hook_calls              3      <- Seam A fired through the whole run
records_with_trace_id   3/3
ledger                  commit COMMITTED probe=LANDED
resume decision         SUBSTITUTE
blocked                 0
```

Passing first time is worth noting rather than celebrating: each component had
already been driven to green independently, and the value of this test is
**regression** — it is the only one that would notice the seams drifting apart.

## 2. M5 — the cost ledger

`agentctl/control/cost/`. Control plane, so it may fail; it consumes Seam A
telemetry after the fact and never sits on a request.

```bash
agentctl ingest hook_telemetry.json
agentctl cost --by-deployment
agentctl cost --conversation <id>     # cost per completed task
```

### Pricing coverage is a column, not a footnote

`docs/0021` §5 found that LiteLLM reports `response_cost: 0.0` for an endpoint
it cannot price — not `None`, **zero**. Raw data cannot distinguish "this was
free" from "I have no idea what this cost", and a budget built on it
under-counts silently, biased toward overspending, precisely on the free-tier
endpoints `docs/0013` §2 is built around.

So `priced` is stored separately from `cost_usd`, and no total renders without
its coverage:

```
cost (all time)
  spend           $0.0042 + unknown (1/3 priced)
  calls           3
  cache hits      800 (36% of input)

  ! PRICING COVERAGE 33% (1/3 calls)
    ...The real total is HIGHER than the figure above.
    unpriced: free-tier
```

`Totals.describe_cost()` will never print a bare number it cannot stand behind.
`test_a_mixed_total_says_so_rather_than_understating` is the test that matters:
*a partial total must never render as though it were complete.*

## 3. Where the project actually stands

**Complete and verified**

| | |
|---|---|
| Effect safety | five classes, nine crash points, real process death |
| Recovery | git, filesystem and idempotency-key probes |
| Seam A | proven live in a real proxy; failover across two accounts |
| **Full stack** | **agent → proxy → backends with the gate** |
| Cost attribution | per conversation, per deployment, with honest coverage |
| Human interface | `agentctl status / blocked / show / resolve / cost / ingest` |
| Verification | `python verify.py` — 8 checks, ~4 min, no API key |

**Not built, and not claimed**

- **No policy compiler** (M7). Pools, budgets and routing rules are still
  LiteLLM config, not a declarative policy the kernel enforces.
- **No cache-affinity intelligence** (`docs/0008` §7). Turn-pinning is not
  prefix affinity.
- **No dashboard** (`docs/0013` §3). The CLI is the only surface.
- **No record/replay evaluator** (M6).
- **Single machine.** Fencing is tested; multi-host is not exercised.
- **Never run against a real provider.** Everything is proven against local
  mocks. That is deliberate and it is a real limit: the first live API key will
  find something.

## 4. What the numbers do and do not prove

The suite proves the *mechanism* on this machine, against pinned versions, with
mock providers. It does not prove:

- that a real provider honours idempotency keys the way the test server does,
- that pricing coverage on a real free-tier pool resembles the mock's,
- that the SDK will behave the same after its next release.

`docs/0009` R1 exists for exactly that, and `verify.py` is cheap so it can be
re-run on every upgrade.

## 5. Consequences

- `docs/0021` §8 → the "no OpenHands-through-proxy run" gap is closed.
- `docs/0008` §8 → attribution is implemented, with coverage added to the
  design as a first-class signal.
- `docs/0013` §4 → `agentctl cost` exists; `agentctl why` and `resume` do not.
- Next: **M7** (policy compiler — turns the free-tier pool into a declared
  thing rather than YAML), or a first run against a real key.
