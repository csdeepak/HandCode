---
Number:        0003
Title:         Critique of the Original Architecture
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-05
Supersedes:    —
Superseded-by: —
Depends-on:    0002
---

# 0003 — Critique of the Original Architecture

Review of `0002`. Frozen as a record of why the project was reframed.

## Assessment

**Architectural thinking: strong.** Three calls in `0002` were correct and
non-obvious:

- Session as a first-class object, endpoint as an attribute of it (§8, §23).
- Persistent memory is not the context window (§10).
- Policy-bounded routing rather than autonomous switching (§5).

**Differentiation as framed: weak.** Roughly 60% of the scoped work already
existed, and the component labelled "the hard problem" was the easy part.

## Findings

### F1 — LiteLLM is not a translation layer

`0002` treated LiteLLM as a dumb adapter. It is a full router: multiple
deployments per model name, cooldowns, layered fallbacks, several routing
strategies, per-key/team/user budgets, spend tracking, Prometheus metrics.
Phases 2, 3, and 6 of the original plan were largely a re-implementation of it.

*Confirmed by `0006`.* See `0006:V8`, `V9`, `V10`, `V12`.

### F2 — Session continuity across an API switch is nearly free

Chat completions are stateless. There is no server-side session to lose; the
full history is resent on every request. Switching accounts mid-task is a retry
against a different key, which the data plane already does. The original
Phase 1 proof-of-concept would have succeeded trivially and proved that the
product was not failover.

### F3 — The real costs of switching were absent from `0002`

- **Prompt-cache invalidation.** Caches are scoped per account/org. Switching
  on a large context forces a full-price cache miss plus latency.
- **Mid-tool-call failure.** A tool commits a side effect, the response is
  lost, replay re-executes it. Listed as risk #11 in `0002` and then dropped.
- **Cross-model drift.** Real, but rarer and lower value to solve first.

*Both of the first two confirmed by `0006`.* See `0006:V1`, `V2`, `V6`, `V7`.

### F4 — Multi-account rotation to evade rate limits is a terms problem

`0002` flagged this as risk #5 and moved on. The legitimate framings are
stronger anyway and address a larger market: multi-tenant BYOK, separate orgs
legitimately held, and multi-*provider* routing.

### F5 — The control plane was drawn in the wrong place

`0002` placed the control plane *below* LiteLLM, on the request path. Real
control planes sit beside the data plane (the Envoy/xDS model): they own
configuration and consume telemetry, while the data plane keeps serving if the
control plane dies. This correction is why risk #14 (SPOF) largely dissolves.

## Consequences

The project was reframed from **"a failover product"** to **"a cost and
continuity optimizer for long-running agent loops,"** in which failover is one
feature rather than the thesis. This reframing survives the
"LiteLLM already does that" objection; the original did not.

Recorded in `0004` as a research roadmap, and validated by `0006`.

## Where this critique was itself wrong

`0003` predicted that LiteLLM had no prompt-cache-affinity routing. **It does**
— `PromptCachingDeploymentCheck` (`0006:V6`). The gap is real but narrower than
claimed: the existing implementation is structurally weak for long, condensed
agent contexts, not absent. See `0007` for the corrected verdict.
