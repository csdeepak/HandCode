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
| **Status** | OPEN |
| **Source** | `0006:U1` |
| **Blocks** | `0008` §6, build step 1 |
| **Impact if yes** | The core BUILD verdict in `0007` collapses. Effect ledger becomes a thin audit layer rather than the product. |
| **Method** | Read the full `_execute_action_event` body and `openhands-sdk/openhands/sdk/agent/parallel_executor.py`; look for a result cache keyed by `tool_call_id`. Then run the Part A experiment in `0006` §7 — kill the process mid-tool and count effects. |
| **Cost to resolve** | ~45 min |

### Q2 — Is `tool_call_id` stable across crash and resume?

| | |
|---|---|
| **Status** | OPEN |
| **Source** | New — introduced by `0008` §6.2 |
| **Blocks** | `0008` §6 data model |
| **Impact if no** | The effect ledger's primary key is invalid and the whole data model must be redesigned around a different stable identifier (`action_event_id`, or a content hash). |
| **Method** | Persist a conversation, crash it mid-tool, resume, and compare the `tool_call_id` on the replayed `ActionEvent` against the original in `events/`. |
| **Cost to resolve** | ~20 min, same experiment as Q1 |
| **Note** | **Highest-risk unverified assumption in `0008`.** It was asserted, not tested. |

### Q3 — Can the tool executor be wrapped without forking OpenHands?

| | |
|---|---|
| **Status** | OPEN |
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
| **Status** | OPEN |
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
| — | — | — | — |
