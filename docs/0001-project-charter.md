---
Number:        0001
Title:         Project Charter
Type:          ARCHITECTURE
Status:        LIVING
Created:       2026-09-05
Supersedes:    —
Superseded-by: —
Depends-on:    —
---

# 0001 — Project Charter

## What this project is

A **control plane for long-running LLM agent loops**: a layer that makes agent
work recoverable, measurable, and cost-efficient across changes of provider,
account, and model.

## What it is not

It is not an API key manager. It is not a dashboard. It is not a competitor to
the LLM data plane (LiteLLM) on generic routing, load balancing, or failover —
those are solved, and re-implementing them is waste.

## Guiding principle

> The model/provider endpoint can change; the logical agent work must remain
> recoverable, measurable, and cost-efficient.

## The problem, stated precisely

A coding agent runs for hours across hundreds of turns. During that time:

- The provider endpoint may change (quota, rate limit, outage, cost policy).
- The process may crash, be killed, or lose the network.
- Context grows past what is economical to resend uncached.
- Tools execute real, irreversible side effects on a filesystem and a git repo.

The naive assumption is that surviving this requires preserving a "session."
It does not — chat completions are stateless and the full history is resent on
every request. What actually breaks is narrower and harder:

1. **Effect safety.** A side-effecting tool can execute while the enclosing
   request or process fails, and replay can execute it a second time.
2. **Cache economics.** Switching endpoints discards a warm prompt cache,
   which on a large context is the dominant cost of switching.
3. **Attribution.** Nothing joins provider spend to a logical unit of agent work.
4. **Policy.** Routing must respect explicit constraints and provider terms.

## Success criteria

| Dimension | Measure |
|---|---|
| Correctness | Zero duplicate side effects across crash and replay |
| Continuity | The correct logical turn is recoverable after infrastructure failure |
| Cost | Lower cost per completed task than baseline routing |
| Cache efficiency | Higher useful cache-hit ratio; lower switching cost |
| Routing | Better decisions under cost, capability, and availability constraints |
| Resilience | Recoverable after process, provider, and network failure |
| Portability | Not structurally tied to one agent harness |

## Method

**Research before building. Falsify before committing.**

Every component gets a verdict — BUILD / CONFIGURE / SKIP — backed by evidence
from primary sources, before any code is written for it. The default verdict
is SKIP until proven otherwise.

## Scope discipline

The project is deliberately narrow at v1. Anything that can be configured
rather than built, is configured. Anything already solved by OpenHands or
LiteLLM is not rebuilt. See `0007` for the current verdict table.
