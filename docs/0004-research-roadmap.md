---
Number:        0004
Title:         Research & Build Roadmap
Type:          GUIDELINE
Status:        LIVING
Created:       2026-09-05
Supersedes:    —
Superseded-by: —
Depends-on:    0002, 0003
---

# 0004 — Research & Build Roadmap

Source: `research/raw/AI_Agent_Control_Plane_Research_Roadmap.pdf`.
Transcribed here so the numbered stream is self-contained.

## Revised problem statement

**Original:** manage many API keys, track limits, switch APIs, keep a local
session alive.

**Revised:** do not rebuild capabilities already supplied by the LLM data
plane. Build the intelligence around it — durable execution, cost
optimization, cache-aware routing, safe recovery, policy, and evaluation.

**Working framing:** Cost & Continuity Optimizer for Long-Running Agent Loops.

## Corrections to the original architecture

| Original assumption | Correction |
|---|---|
| API dashboard is the main product | It is an interface to a deeper control layer |
| LiteLLM is a dumb translator | Audit what the data plane already provides first |
| Session = context window | Separate durable state, event history, memory, active context, workspace, tool state |
| API switching is the hard problem | The hard cases are cache loss, partial tool execution, idempotency, replay, recovery |
| OpenHands needs another session manager | It already has ConversationState, EventLog, persistence, resume — find the actual gap |
| Rotate accounts to bypass limits | Prefer legitimate pools, BYOK/multi-tenant, cost-aware multi-provider routing |

## Research phases

| Phase | Topic | Status | Result doc |
|---|---|---|---|
| 0 | Existing-system reconnaissance | **COMPLETE** | `0006` |
| 1 | LLM request lifecycle | Not started | — |
| 2 | Context engineering | Not started | — |
| 3 | Agent execution state | Not started | — |
| 4 | Distributed systems foundations | Not started | — |
| 5 | Durable execution & workflow orchestration | Not started | — |
| 6 | Routing intelligence & cache economics | Not started | — |
| 7 | Correctness boundary | Not started | — |
| 8 | Evaluation without burning tokens | Not started | — |
| 9 | Production architecture | Not started | — |

Prompts for each phase: `0005`.

Ad-hoc feature research outside the phase sequence is recorded separately;
see `0010` (latency, switching, MCP/plugins).

## The five concepts to hold precisely

- **Session** — the durable logical identity of an agent task, independent of
  provider, key, and active context window.
- **Turn** — one logical transition in the agent loop: LLM response, tool call,
  observation.
- **Journal** — an append-oriented record enabling recovery, audit, and replay.
- **Context** — the model-visible slice selected for one request. Durable
  memory can be far larger.
- **Control plane vs data plane** — the data plane serves requests; the control
  plane owns policy and consumes telemetry.

## The five hard problems

1. Prompt-cache affinity
2. Mid-tool-call failure
3. Cross-model drift
4. Durable execution
5. Policy correctness

## Build order (post-research)

Request ledger → cache-affinity intelligence → turn journal / idempotency
boundary → capability matrix → record/replay evaluator → context optimization.

*Superseded by the sequence in `0008` §14, which reorders based on `0006`.*
