---
Number:        0021
Title:         M1 Results — Seam A Fires
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0012, 0015, 0020
---

# 0021 — M1 Results

The skipped milestone. Seam A now exists and is proven to fire inside a real
LiteLLM proxy.

**Run:** 2026-09-08 · `litellm 1.100.0` proxy · zero cost.
Code: `agentctl/kernel/hook.py`. Acceptance: `experiments/0005-m1-seam-a/`.
**156 tests passing.**

---

## 1. The result

```
hook_fired              True
hook_calls              6          inside a real proxy, not a stub
mid_turn_detected       1
failover_statuses       [200, 200, 200, 200]
acct_a                  served 1, refused 3       <- 429s
acct_b                  served 5, refused 0       <- picked up the load
telemetry_records       6
records_with_trace_id   6/6
deployments_seen        ['acct-a', 'acct-b']
records_with_cost       0          <- Q18, confirmed
```

Two accounts, a real proxy, a real 429, real failover. And critically: the hook
**actually fired**, which `docs/0012` §0 insisted be proven rather than assumed
— LiteLLM silently bypasses `async_pre_call_hook` on the Anthropic endpoint
(#27518) and for MCP calls (#25011), and a Seam A that does nothing looks
exactly like one that works.

## 2. Why this was worth correcting course for

`docs/0013` §5 makes the strongest claim in the project: because the kernel
binds at the LiteLLM layer, **anything speaking the OpenAI-compatible format
passes through Seam A** — Claude Code, Aider, Cline, Continue. One integration,
every tool.

Until today that claim rested on nothing. It now rests on six requests through
a real proxy.

## 3. What Seam A does

| | |
|---|---|
| **Turn-atomic routing** | A message list ending in unresolved tool calls is pinned to the deployment that opened the turn (`docs/0010` §7.3). |
| **Attribution** | Stamps `conversation:turn`. The SDK supplies the conversation half already (`docs/0015` §5). |
| **Telemetry** | Cost, tokens, cache reads, chosen deployment — the raw material for M5. |

It decides nothing about effects. That stays with the gate at Seams B and C,
and Seam A never touches the ledger.

## 4. The finding M5 depends on

Telemetry initially came back with **`trace_id: None` on every record**, which
would have left the cost ledger with nothing to join on.

The cause is not obvious:

> **Anything the pre-call hook writes into `data["metadata"]` arrives on the
> logging callback under `litellm_params.metadata` — not `kwargs["metadata"]`,
> which is empty.**

Reading only the obvious place yields `None` and silently breaks attribution.
Nothing errors; the numbers simply never join. Now read from both, with the
nested path preferred, and asserted by
`test_trace_id_is_read_from_litellm_params_metadata`.

This is exactly the class of bug `docs/0012` §0 predicted for Seam A: it fails
by doing nothing rather than by failing.

## 5. Q18 — confirmed, and worse than expected

`records_with_cost: 0`. LiteLLM could not price the mock endpoint, so
`response_cost` came back as **`0.0`**.

Not `None`. **Zero.**

An unpriced call and a genuinely free one are indistinguishable, so
`max_budget_per_run` (`docs/0015` §4) does not merely miss them — it counts
them as free and keeps going. The failure is silent and biased toward
overspending, and it lands precisely on the custom and self-hosted endpoints
that dominate the free-tier pool in `docs/0013` §2.

**Consequence for M5:** the cost ledger must track *pricing coverage* as a
first-class signal, not just cost. "I spent $0.00" and "I do not know what I
spent" have to be different numbers.

`docs/0009` Q18 → **RESOLVED (confirmed as a real hazard).**

## 6. A fourth cp1252 bug

The proxy would not start at all under a redirected pipe: LiteLLM's startup
banner is non-ASCII and `click.echo` raised `UnicodeEncodeError` inside the
FastAPI lifespan, killing the app with `Application startup failed`.

Fixed with `PYTHONIOENCODING=utf-8` and `PYTHONUTF8=1` in the child
environment. This is the **fourth** encoding failure in this project — M0's
probes, M0's subprocess pipes, M4's CRLF appends, and now the proxy itself.

Worth promoting from anecdote to rule: **on Windows, any subprocess whose
output is redirected needs UTF-8 forced in its environment.** Assume it, do not
wait to be surprised.

## 7. Two things the project's own guardrails caught

**The boundary test caught an architectural violation I introduced.**
`docs/0012` §1 specifies `kernel/hook.py`, so that is where Seam A went — and
it imports `litellm`. `tests/test_boundaries.py` failed immediately: the kernel
may not import a data plane any more than it may import a harness
(`docs/0008` R6).

Split accordingly. The kernel keeps the decision logic (`RequestHook`,
`TurnAffinity`, mid-turn detection); `agentctl/adapters/litellm/hook.py` holds
the ~40 lines that know about LiteLLM. `docs/0012` §1 should be corrected — the
*binding* was never a kernel concern.

`docs/0012` §1 called that test "what keeps the architecture from rotting". It
just proved it.

**A silent dependency downgrade.** Installing `litellm[proxy]` pulled `mcp`
from 2.2.0 down to 1.30.0, which breaks `fastmcp` and therefore every OpenHands
import. `pip check` reported **no broken requirements**. Pinning `mcp>=2.2.0`
alongside the proxy extra resolves it, and both now import cleanly.

Recorded as a `proxy` extra in `pyproject.toml` so it cannot regress quietly.
This is `docs/0009` R1 (upstream velocity) arriving in a form the risk register
did not anticipate: not a version drifting under a claim, but one dependency
silently breaking another.

## 8. What M1 does not include

- **No policy enforcement.** The hook reads no compiled policy yet; that is M7.
- **No cache affinity.** Turn pinning is not the same thing as prefix affinity
  (`docs/0008` §7).
- **No OpenHands-through-proxy run.** Seam A is proven with direct requests.
  Wiring OpenHands to the proxy is `base_url` configuration, but it is untested
  here and the claim should not be stretched.
- **Single proxy worker.** `TurnAffinity` is per-process, so multi-worker
  deployments would lose pins. Correctness is unaffected — a lost pin costs a
  pinning opportunity, never safety.

## 9. Consequences

- `docs/0009` Q18 → RESOLVED. Q5 already resolved; this exercises it live.
- `docs/0012` §3.4 → record where LiteLLM actually puts metadata.
- `docs/0012` §6 → add the UTF-8 subprocess rule.
- `docs/0012` §1 → Seam A's binding belongs in `adapters/`, not the kernel.
- `docs/0013` §5 → the multi-tool claim now has evidence.
- Next: **M5**, with pricing coverage as a first-class signal.
