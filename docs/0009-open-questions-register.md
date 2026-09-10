---
Number:        0009
Title:         Open Questions & Risk Register
Type:          REGISTER
Status:        LIVING
Created:       2026-09-05
Supersedes:    —
Superseded-by: —
Depends-on:    0006, 0008
---

# 0009 — Open Questions & Risk Register

Living document. Update in place. Every question gets an id, an owner, a
resolution method, and an impact statement.

**Status values:** `OPEN` · `IN PROGRESS` · `RESOLVED` · `WONTFIX`

---

## Blocking questions

These block `0008` from moving DRAFT → ACCEPTED.

### Q1 — Does OpenHands have an executor-level dedup guard?

| | |
|---|---|
| **Status** | **RESOLVED** — see `0014` |
| **Source** | `0006:U1` |
| **Blocks** | `0008` §6, build step 1 |
| **Impact if yes** | The core BUILD verdict in `0007` collapses. Effect ledger becomes a thin audit layer rather than the product. |
| **Method** | Read the full `_execute_action_event` body and `openhands-sdk/openhands/sdk/agent/parallel_executor.py`; look for a result cache keyed by `tool_call_id`. Then run the Part A experiment in `0006` §7 — kill the process mid-tool and count effects. |
| **Cost to resolve** | ~45 min |

### Q2 — Is `tool_call_id` stable across crash and resume?

| | |
|---|---|
| **Status** | **CORRECTED** — `0014` was a mock artifact; see `0023` §4 |
| **Source** | New — introduced by `0008` §6.2 |
| **Blocks** | `0008` §6 data model |
| **Impact if no** | The effect ledger's primary key is invalid and the whole data model must be redesigned around a different stable identifier (`action_event_id`, or a content hash). |
| **Method** | Persist a conversation, crash it mid-tool, resume, and compare the `tool_call_id` on the replayed `ActionEvent` against the original in `events/`. |
| **Cost to resolve** | ~20 min, same experiment as Q1 |
| **Note** | **Highest-risk unverified assumption in `0008`.** It was asserted, not tested. |

### Q3 — Can the tool executor be wrapped without forking OpenHands?

| | |
|---|---|
| **Status** | **RESOLVED** — see `0014` |
| **Source** | New — introduced by `0008` §3 (Seam C) |
| **Blocks** | The entire Option 3 architecture |
| **Impact if no** | Seam C is unavailable, R1 becomes unsatisfiable, and the project falls back to Option 1 (detect-and-alarm only). That is a materially weaker product and would need a new architecture document. |
| **Method** | Inspect how executors are registered on `Agent` / tool definitions. Determine whether a custom executor can be injected via public API, or whether composition around the registered tool is possible. |
| **Cost to resolve** | ~1 hour |

### Q4 — Does `deployment_affinity` supersede `prompt_caching`?

| | |
|---|---|
| **Status** | OPEN |
| **Source** | `0006:U4` |
| **Blocks** | `0008` §7 scope |
| **Impact if yes** | Cache intelligence shrinks from BUILD to CONFIGURE. A welcome scope deletion. |
| **Method** | Read `litellm/router_utils/pre_call_checks/deployment_affinity_check.py`; confirm TTL configurability and introduction version (docs mention behavior changed at v1.97.0). |
| **Cost to resolve** | ~30 min |

### Q5 — Does OpenHands forward `x-litellm-trace-id` by default?

| | |
|---|---|
| **Status** | **RESOLVED** — see `0015` |
| **Source** | `0006:U2` |
| **Blocks** | `0008` §8 |
| **Impact if no** | One extra build step in the request hook. Low risk either way. |
| **Method** | Inspect completion kwargs assembled in `llm.py` for a `metadata` / `trace_id` field; run the proxy and read a `LiteLLM_SpendLogs` row. |
| **Cost to resolve** | ~30 min |

---

## Non-blocking questions

### Q6 — Default condenser configuration in the V1 SDK

| | |
|---|---|
| **Status** | OPEN |
| **Source** | `0006:U3` |
| **Impact** | Affects cache-invalidation modelling in `0008` §7. Sources conflict on whether the summarizing condenser is on by default. |
| **Method** | Read `openhands-sdk/openhands/sdk/context/condenser/` defaults and the default agent preset. |

### Q7 — Do fallbacks preserve request state unchanged?

| | |
|---|---|
| **Status** | OPEN |
| **Source** | `0006:U5` |
| **Impact** | If `context_window_fallbacks` mutates messages, cache affinity assumptions in §7 need revision. |
| **Method** | Read `litellm/router.py::async_function_with_fallbacks`. |

### Q8 — Which MCP spec revision does the OpenHands SDK implement?

| | |
|---|---|
| **Status** | OPEN |
| **Source** | `0010:U1` |
| **Impact** | Determines whether MCP connection state can be deleted from the non-reconstructible list (`0010` §8.1). The 2026-07-28 revision made MCP stateless; a pre-RC client keeps the old behavior. |
| **Method** | Read the SDK's MCP client and its pinned protocol version string. |

### Q9 — What is the read/write ratio of tool calls by effect class?

| | |
|---|---|
| **Status** | OPEN |
| **Source** | `0010:U3` |
| **Impact** | Decides whether speculative tool execution (`0010` §6.4) is worth building at all. It pays off only if `PURE_READ` calls dominate. |
| **Method** | Instrument one real OpenHands session; count tool calls by effect class. |
| **Note** | **Cheapest high-value measurement in the project.** One session answers it. |

### Q10 — Is `tool_call_id` stable across *providers*, not just across resume?

| | |
|---|---|
| **Status** | OPEN |
| **Source** | New — `0010` §7.3 |
| **Impact** | If not, a mid-turn provider switch defeats the effect ledger's primary key and a committed effect becomes invisible — re-executing it. Mitigated by the proposed turn-atomic routing rule. |
| **Method** | Compare `tool_call_id` formats across Anthropic, OpenAI, and Gemini tool-call responses. Strict superset of Q2. |

### Q11 — Does any provider expose cache residency directly?

| | |
|---|---|
| **Status** | OPEN |
| **Source** | `0010:U2` |
| **Impact** | All current affinity schemes *infer* cache residency. Direct observation would simplify `0008` §7 considerably. |
| **Method** | `0005` Phase 6 provider cache research. |

### Q12 — Does the MCP registry expose policy-grade metadata?

| | |
|---|---|
| **Status** | OPEN |
| **Source** | `0010:U4` |
| **Impact** | Capability gating (`0010` §8.3) needs declared scopes, auth model, and side-effect hints. |
| **Method** | Read the registry OpenAPI spec at `registry.modelcontextprotocol.io`. |

### Q13 — Does OpenHands drive `/v1/chat/completions` or `/v1/messages`?

| | |
|---|---|
| **Status** | **RESOLVED** — see `0014` |
| **Source** | New — `0012` §0 |
| **Blocks** | **M1.** LiteLLM issue #27518: proxy-level `async_pre_call_hook` is bypassed on the Anthropic `/v1/messages` endpoint. |
| **Impact if `/v1/messages`** | Seam A silently does nothing — no policy, no affinity, no trace-id. The failure is invisible, which makes it worse than an error. |
| **Method** | Inspect the completion call assembled in `llm.py`; then assert live that the hook fires. |

### Q14 — Can the gate inject a git trailer into an agent-authored commit?

| | |
|---|---|
| **Status** | **WONTFIX** — moot; `0017` replaced trailer injection with world fingerprinting |
| **Source** | New — `0012` §3.3 |
| **Blocks** | M4 git reconciliation probe. |
| **Impact if no** | The git probe cannot identify its own effect, and `NON_IDEMPOTENT_WRITE` commits fall back to fail-closed on every ambiguous resume. Usable, but noisy. |
| **Method** | Attempt trailer injection by rewriting the bash command in the gate before execution; verify `git log --grep` finds it. |

### Q15 — Does `LocalConversation.prompt_cache_key` serve our affinity need?

| | |
|---|---|
| **Status** | **RESOLVED** — see `0015` |
| **Source** | `0014:F1` |
| **Impact** | May reduce `0008` §7 cache intelligence from BUILD to CONFIGURE. |
| **Method** | Read how the SDK threads `prompt_cache_key` into the LLM call. |

### Q16 — Is `Conversation.hook_config` a fourth seam?

| | |
|---|---|
| **Status** | **RESOLVED** — read in `0015`, **executed in `0016`** |
| **Source** | `0014:F2` |
| **Impact** | `0008` §3 considered three seams. If `HookConfig` can intercept rather than observe, the adapter may shrink. |
| **Method** | Read `openhands.sdk.hooks.config.HookConfig` and its call sites. |

### Q17 — Does `max_budget_per_run` cover the budget guard?

| | |
|---|---|
| **Status** | **RESOLVED** — see `0015` |
| **Source** | `0014:F3` |
| **Impact** | Could satisfy part of `0013` §4 by configuration rather than code. |
| **Method** | Test it against the mock provider with a low cap. |

### Q18 — Does litellm price every endpoint in the free-tier pool?

| | |
|---|---|
| **Status** | **RESOLVED** — confirmed as a real hazard in `0021` §5 |
| **Source** | `0015` §4 |
| **Impact** | `max_budget_per_run` relies on litellm cost calculation. M0 showed it fails for unmapped models. Any endpoint litellm cannot price is **invisible to the budget cap** — precisely the custom and self-hosted endpoints common in the free-tier pool (`0013` §2). |
| **Method** | For each endpoint in the pool, make one call and check whether `accumulated_cost` moves. |

---

## Risks

### R1 — Upstream velocity

Both dependencies move fast; `0006` observed SDK pins from v1.18.0 to v1.44.0.
Source-derived claims decay.

**Mitigation:** pin an exact SDK version in `experiments/`. Re-verify every
source-derived claim against that pin before building on it. Never build
against `main`.

### R2 — Seam C is the whole architecture

If Q3 resolves badly, Option 3 is dead. This is concentrated risk in a single
unverified assumption.

**Mitigation:** resolve Q3 in step 0, before any other work. Option 1 is the
documented fallback.

### R3 — Scope regrowth

`0007` deleted two components and downgraded two more. The natural drift is to
quietly add them back.

**Mitigation:** `0008` §11 is the explicit exclusion list. Any addition
requires a new numbered DECISION document that supersedes it.

### R4 — Provider terms

Multi-account routing must stay within provider terms (`0003:F4`).

**Mitigation:** Phase 6 research includes a terms review. The policy compiler
must be able to express and enforce the resulting constraints.

### R5 — Research decay

Phase 0 was completed 2026-09-05. Claims older than ~6 months in this domain
should be treated as suspect.

**Mitigation:** the "What has changed since your sources?" follow-up in `0005`
Part C, run before each build step.

---

## Resolution log

| Date | Question | Resolution | Recorded in |
|---|---|---|---|
| 2026-09-08 | Q1 | **CONFIRMED** — effect ran twice (1 before crash, 2 after resume) | `0014` |
| 2026-09-08 | Q2 | **CONFIRMED** — `tool_call_id` byte-identical across resume | `0014` |
| 2026-09-08 | Q3 | **CONFIRMED** — Seam C binds by replacing `ToolDefinition.executor` | `0014` |
| 2026-09-08 | Q13 | **CONFIRMED** — SDK drives `/v1/chat/completions` | `0014` |
| 2026-09-08 | Q5 | **RESOLVED** — SDK already sends `x-litellm-session-id` = conversation id | `0015` |
| 2026-09-08 | Q15 | **PARTIAL** — provider-side cache shard key exists; cross-account affinity still ours | `0015` |
| 2026-09-08 | Q16 | **PARTIAL** — `block_action` makes Seam B able to BLOCK (corrects `0008` §3); cannot SUBSTITUTE | `0015` |
| 2026-09-08 | Q17 | **PARTIAL** — per-run USD cap is free; per-day is not | `0015` |
| 2026-09-08 | Q16 | **CONFIRMED empirically** — `block_action` prevents execution; duplicate eliminated | `0016` |
| 2026-09-08 | Q14 | **WONTFIX** — trailer injection unnecessary; fingerprinting works at Seam B | `0017` |
| 2026-09-08 | Q18 | **CONFIRMED hazard** — litellm reports cost `0.0` for unpriced endpoints, indistinguishable from free | `0021` |
| 2026-09-08 | Q2 | **CORRECTED** — `tool_call_id` is model-minted and NOT stable across a pool. M0's CONFIRMED was an artifact of a fixed mock id. Ledger now falls back to `intent_hash`. | `0023` |
