---
Number:        0037
Title:         Harness Pivot — Research Brief
Type:          GUIDELINE
Status:        LIVING
Created:       2026-09-20
Supersedes:    —
Superseded-by: —
Depends-on:    0005, 0006, 0010, 0013
---

# 0037 — Harness Pivot: Research Brief

This is a **Phase 10 prompt** in the format of `0005`. Paste `0005` Part A
(Master Brief) first, unchanged — source tiers, dating, version pinning,
confidence tiering, and "contradict me" all still apply. Then paste one part of
Part B below at a time and wait for the deliverable before moving on.

## Why this brief exists

The request that produced it: *a harness that looks like Claude Code, runs on
many APIs through a LiteLLM proxy with a dashboard over the keys, and supports
multi-agent execution.*

Three of those four things exist in this repository already (`0032`, `0033`,
`0034`, and `agentctl run`). The fourth — harness features and multi-agent — is
**explicitly excluded by `0010` §9.1 and deferred to Layer 3 by `0013` §7**,
and the charter (`0001`) says in as many words that this is not a dashboard and
not a key manager.

So this is a **scope reversal**, not a gap. The research below exists to make
that reversal on evidence rather than by drift. Its most valuable possible
output is still the `0005` one: *what should I not build?*

## Standing constraint for every part

Answer for **this** workload, not in general: one developer, free tiers across
several providers, a student budget, Windows plus CI on Linux, and a
correctness core (ledger, gate, Seams B and C) that already works and must not
be lost. An answer that would be right for a funded team is the wrong answer
here, and should say so.

---

# PART B — PHASE PROMPTS

## Phase 10.1 — Harness survey

Decide what the agent loop should be. The incumbent is `openhands-sdk>=1.45.0`
(pinned in `pyproject.toml`); the question is whether it stays.

**Do not compare feature lists.** Compare the five seams this project actually
binds to. For each candidate, answer with `path/to/file::symbol` and a
permalink to a specific commit or tag:

1. **Library or application?** Can it be imported and driven from my own
   process, or does it assume its own server, UI, and container runtime? Name
   the import path that starts an agent loop, or say there isn't one.
2. **Model configuration.** Does it accept an arbitrary OpenAI-compatible
   `base_url` plus key per conversation — at runtime, not only from a config
   file? This decides whether the existing LiteLLM proxy plugs in with zero
   code. Show the code path from user config to the HTTP request.
3. **Seam B (observe and block).** Is there an event callback fired *before* a
   tool executes, and can it refuse the action? Quote the mechanism.
4. **Seam C (substitute).** Can a tool's executor be wrapped so a recorded
   result is returned *instead of* execution? This is the one that makes clean
   resume possible; a harness without it degrades to fail-closed only
   (`0008`, README "How it works").
5. **Persistence.** Is the event log append-only, is an action durable before
   it executes, and does resume re-drive unmatched actions? `0006` answers this
   for OpenHands — answer it the same way for each candidate, because the
   double-execution bug is a property of that ordering.

**Candidates.** OpenHands SDK (incumbent) and the OpenHands application as two
separate entries; Aider; Cline; Roo Code; Goose; OpenCode; Crush; SWE-agent;
Continue; LangGraph; OpenAI Agents SDK; Claude Agent SDK; Codex CLI. Add any
you find that scores better on the five seams, and drop any that is abandoned —
state the last-commit date for each.

**Deliverable.** A five-column scoring table over those seams, plus, for the
top two, an estimated port cost in lines of adapter code measured against the
existing `agentctl/adapters/openhands/` (137 + 112 + 236 + 203 lines). `0013`
§5 estimates ~150 lines per harness; test that estimate.

**Verdict required:** STAY / PORT / DUAL-TARGET, with the losing option's
strongest argument stated fairly.

## Phase 10.2 — Multi-agent, costed before it is designed

The ask is multi-agent execution. Before any design, establish whether it is
affordable and whether it is safe here.

- **The token arithmetic.** N concurrent agents means N contexts. For a
  realistic coding task, quantify total tokens for one agent versus a
  supervisor plus three workers, including the supervisor's context growth as
  it absorbs worker reports. Then put that against a free-tier daily cap from
  the real pool (`proxy/proxy_config.yaml` currently generates 42 deployments
  across 18 accounts). **Does multi-agent fit in the budget at all?** Show the
  arithmetic; this question can kill the feature on its own.
- **Effect safety under concurrency.** The ledger is single-writer SQLite with
  leases and fencing (`0012` §2.1, `0019`). The README states plainly: single
  process; multi-host is not exercised. Two agents editing one workspace is
  exactly the case fencing was designed for and never tested against. What
  breaks? Specify the chaos tests that would prove it, in the style of the
  nine-point suite.
- **Workspace isolation.** Separate git worktrees, separate containers, or one
  shared tree with locking? Compare on cost, on crash recovery, and on whether
  the git reconciliation probe (`0017`) still works when another agent is
  committing concurrently.
- **Evidence for the benefit.** What do the literature and real harnesses
  actually demonstrate about multi-agent coding agents beating one agent per
  token spent — not per wall-clock second? Be adversarial. `0013` §7 deferred
  this for a reason; either overturn that reasoning or confirm it.
- **Cache affinity.** `0010` §6 says rotation destroys a warm cache. N agents
  across a rotating pool multiply that. Quantify.
- **The journal prerequisite, already identified.** `0006`:76 gave the
  session/turn journal a split verdict: *CONFIGURE for OpenHands / BUILD for
  multi-agent*. Single-agent work escaped that BUILD by subscribing to
  OpenHands' own `EventLog`; multi-agent does not. Scope it — the
  client-agnostic journal, the idempotency markers OpenHands lacks (I2), and
  the normalization layer — and price it before anything else in this phase.

**Verdict required:** BUILD NOW / BUILD AFTER <named prerequisite> / SKIP, with
the budget arithmetic as the deciding evidence.

## Phase 10.3 — Model selection as a user surface

The ask names Wispr and OpenCode as the interaction model: a models section
where a source is chosen, and switching to another API of the same source.

- **How do they actually do it?** For OpenCode, Cline, Continue, and Aider:
  where does the model list come from (a static file, a provider `/models`
  endpoint, a registry), how is a provider's key attached, and can the model be
  changed *mid-conversation*? Cite the code.
- **The hard part: switching mid-conversation.** When the model changes between
  turns, what happens to tool-call history recorded in the previous provider's
  schema? Where do Anthropic, OpenAI and Gemini differ structurally
  (`0005` Phase 1 asks this; answer it concretely here). What must be
  rewritten, and what is simply unsafe to carry across?
- **Does the proxy already answer this?** LiteLLM exposes `/v1/models` and
  `/model/info`. Could `agentctl dash` read the live pool from the running
  proxy instead of deriving it from environment variables? What does the proxy
  expose about per-deployment health and cooldown state, and is any of it
  enough to answer Panel 1's question — *can I work right now?* (`0013` §3).
- **Free-tier reality.** `0034` found four ways a key check can lie, and
  `providers.py` deliberately records no rate limits because they go stale in
  weeks. Any model-picker design that displays quota must say where that number
  came from and when it was true, or it repeats the `$0.00` mistake of
  `0021` §5.

**Deliverable.** An interface specification for model selection: the data it
needs, its source of truth, its refresh policy, and what it shows when it does
not know.

## Phase 10.4 — What to delete

`0007` deleted two components and downgraded two more, and that was the point
of running Phase 0. Do the same here.

Given the verdicts above, produce a component table over everything now in
`agentctl/` — kernel (ledger, gate, classifier, reconcile), control (keys,
dash, proxy, policy, cost, replay, probe), adapters, runtime — with one of:
**KEEP** / **KEEP BUT UNUSED** / **DELETE** / **EXTRACT AS LIBRARY**.

State explicitly what the pivot costs in already-verified work. 502 tests and
four end-to-end crash experiments currently stand behind the correctness core;
name which of them stop being meaningful if the harness changes.

---

## Output contract

Use the `0005` output contract verbatim (§1 Executive answer … §8 Sources),
with one addition: a final **§9 — Decision I am asking you to make**, stating
the single decision the deliverable forces and the evidence that decides it.

## How the results land here

Each part becomes the next free numbered document as a frozen `RESEARCH` file,
followed by a `DECISION` document recording what it changed — per
`CONVENTIONS.md`. Nothing in `agentctl/` changes before the DECISION exists.
