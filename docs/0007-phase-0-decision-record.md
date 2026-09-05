---
Number:        0007
Title:         Phase 0 Decision Record — Scope After Reconnaissance
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-05
Supersedes:    —
Superseded-by: —
Depends-on:    0006
---

# 0007 — Phase 0 Decision Record

What the reconnaissance in `0006` changed. This document exists so the scope
deletions are explicit and hard to quietly undo later.

## The finding that reorders the project

`0006:V1` and `0006:V2`, both traced to OpenHands SDK source:

- `Agent._handle_tool_calls()` constructs the `ActionEvent` and persists it via
  `ConversationState.append_event` **before** `_execute_actions()` runs the tool.
- On resume, `Agent.step()` calls `get_unmatched_actions()` and re-drives any
  orphaned action **through the real tool executor**.
- Tool-level idempotency is explicitly the tool's responsibility.

**Therefore double-execution on crash-resume is a confirmed property of the
system, not a hypothetical risk.** This was risk #11 in `0002`, dropped as a
footnote. It is now the centre of the architecture.

The write-ahead ordering is deliberate and correct — it is what enables
confirmation mode and observability. The gap is not the ordering. The gap is
that nothing records *"this tool_call_id already produced a real-world effect."*

## Correction to `0003`

`0003` asserted LiteLLM had no cache-affinity routing. **It does.**
`PromptCachingDeploymentCheck`, enabled via
`optional_pre_call_checks: ["prompt_caching"]` (`0006:V6`).

The gap is narrower than claimed, but real. Three structural weaknesses under
long condensed agent contexts (`0006:V7`, `I1`):

1. Affinity TTL hardcoded to 300s, not overridable — cannot match a 1-hour
   ephemeral cache.
2. The prefix search walks back only 3 messages; an agent turn appending more
   than that misses affinity and re-routes.
3. The cache key hashes the *entire* message list rather than the
   `cache_control`-marked prefix, so any mid-prefix mutation invalidates it —
   and condensation is exactly a mid-prefix mutation.

Verdict moves from BUILD to **CONFIGURE + targeted BUILD**.

## Verdict table

| Component | Verdict | Basis |
|---|---|---|
| Effect ledger / idempotency boundary | **BUILD** | `0006:V1`, `V2`, `I2` — nothing at any layer records tool-effect completion |
| Policy compiler | **BUILD** | `0006:V11` — enforcement primitives exist, no declarative policy layer |
| Capability matrix / drift tooling | **BUILD** | `0006:V8`, `I3` — greenfield at both layers |
| Cache intelligence | **CONFIGURE + BUILD** | `0006:V6`, `V7`, `I1` — v1 exists and is weak for this workload |
| Cost ledger | **CONFIGURE + thin BUILD** | `0006:V10`, `V5`, `I4` — raw material exists, attribution to a logical turn does not |
| Record/replay evaluation | **BUILD** | `0006` §6 — OpenHands replay re-executes effects, unusable as a regression harness |
| Session/turn journal | **CONFIGURE** | `0006:V3` — the `EventLog` *is* the journal; subscribe, do not reinvent |
| Context/memory layer | **SKIP** | `0006:V13` — condensers exist and cut cost ~50%; revisit only for non-OpenHands clients |

## Scope deleted

Two components leave v1 entirely:

- **Context/memory layer** — `LLMSummarizingCondenser` and the condenser
  pipeline already do this. Building our own would be pure duplication.
- **Session/turn journal as a new store** — OpenHands' `EventLog` is
  append-only, event-sourced, with pluggable backends. We subscribe to it.

This is the point of Phase 0. Two of eight components deleted, two downgraded
from BUILD to CONFIGURE-plus.

## What is now the product

> An **effect-safety and cost-attribution layer** for agent loops, delivered as
> plugins into existing extension points, never as a fork.

Effect safety is the differentiator. Cache and cost are the economics. Policy
and capability are the control surface.

## Open questions blocking commitment

`0006:U1` is on the critical path — if an executor-level dedup guard already
exists in OpenHands, the core BUILD verdict weakens. **Resolve by experiment
before writing ledger code.** See `0009`.
