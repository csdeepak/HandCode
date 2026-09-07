---
Number:        0008
Title:         System Architecture v1
Type:          ARCHITECTURE
Status:        DRAFT
Created:       2026-09-05
Supersedes:    0002 (§2 architecture)
Superseded-by: —
Depends-on:    0006, 0007, 0010, 0014, 0015
---

# 0008 — System Architecture v1

**Status: DRAFT.** Eight of the nine open questions are now resolved by `0014`
(M0 execution) and `0015` (source reading). **Q4 is the last blocker.**
Corrections from `0010` §11, `0014` §3, and `0015` are folded in below and
marked inline.

---

## 1. The forces

Architecture is a response to forces. Ours, after `0006`:

**F1 — The agent harness already owns durable state, and owns it well.**
OpenHands is event-sourced with an append-only log as the single source of
truth (`0006:V3`). Any state store we build competes with a better one.

**F2 — The harness re-executes side effects on resume.** Confirmed in source
(`0006:V1`, `V2`). This is not a bug to report upstream; the write-ahead
ordering is deliberate and enables confirmation mode. It is a *missing layer*.

**F3 — The data plane exposes rich hooks but no tool-boundary visibility.**
LiteLLM's `CustomLogger` can inspect, rewrite, or reject any LLM request
(`0006:V11`), but it sits strictly below the tool boundary and can never see a
tool execute.

**F4 — Cache affinity exists but degrades under exactly our workload.**
`PromptCachingDeploymentCheck` works for stable prefixes; long agent contexts
with condensation mutate the prefix and defeat it (`0006:V6`, `V7`, `I1`).

**F5 — Nothing joins provider spend to a logical unit of agent work.**
Both halves of the data exist; the join does not (`0006:I4`).

**F6 — The control plane must not be able to stop the work.** Stated in
`0003:F5` and non-negotiable.

**F7 — We must not fork either OpenHands or LiteLLM.** Both move fast
(`0006` scope note: SDK pins observed from v1.18.0 to v1.44.0). A fork is a
maintenance death sentence for a solo developer.

---

## 2. Constraints

**Hard requirements**

| # | Requirement |
|---|---|
| R1 | No side effect executes twice as a result of crash, retry, or replay |
| R2 | The control plane may fail without stopping agent work |
| R3 | Integration is via published extension points only — no forks, no patches |
| R4 | Provider spend is attributable to a logical turn |
| R5 | Routing respects explicitly declared constraints and provider terms |
| R6 | Nothing structurally couples the design to OpenHands |

**Non-goals for v1**

- Context construction and summarization (`0007` — SKIP, condensers own this)
- A general session store (`0007` — CONFIGURE, the EventLog owns this)
- Generic routing, load balancing, retries, cooldowns (LiteLLM owns these)
- Multi-agent orchestration
- **Skills, subagents, slash commands, command palettes** (`0010` §9.1) — these
  are harness concerns, and OpenHands already has its own equivalents
  (microagents, condensers, repo instructions). Building a second set would
  create two competing systems with no clear owner.
- ~~A user-facing dashboard~~ — **reversed by `0013` §3.** Restored as milestone M8;
  the blocked-effect resolution panel is required to make fail-closed usable.

---

## 3. The central design question: where do we intercept?

This is the architecture. Everything else follows from it.

There are exactly three seams available, and they have **different powers**.

### Seam A — Below the agent, above the provider

**Mechanism:** LiteLLM `CustomLogger` — `async_pre_call_hook`,
`async_post_call_success_hook`, logging callbacks (`0006:V11`).

- **Sees:** model, messages, tools, params, tokens, cost, cache read/write
  tokens, latency, chosen deployment.
- **Can:** rewrite the request, force a deployment, reject before spend.
- **Cannot:** see or influence tool execution. It is structurally below the
  tool boundary.

### Seam B — Inside the agent, observing

**Mechanism:** OpenHands conversation callbacks over the event stream.

- **Sees:** every `ActionEvent` and `ObservationEvent`, turn structure, causal
  links, the full agent state machine.
- **Can:** mirror, attribute, measure, detect drift — **and block**, via the
  public `ConversationState.block_action(action_id, reason)`. `PRE_TOOL_USE`
  fires on `ActionEvent`, before execution (`0015` §2).
- **Cannot:** **substitute** a stored observation. A blocked action makes the
  agent emit a *rejection*, not the recorded result.

> **Corrected 2026-09-08 (`0015` §2).** This section previously claimed Seam B
> "cannot prevent anything; callbacks are notification, not interception."
> That was wrong, and the correction improves the design — see §3.5.

### Seam B′ — the published hook system

**Mechanism:** `Conversation(hook_config=HookConfig(...))`, with
`PRE_TOOL_USE` / `POST_TOOL_USE` matchers.

Same powers as Seam B, but `HookType` is `AGENT | COMMAND | PROMPT` — all
external — so every tool call would spawn a subprocess. **We call
`block_action` directly instead.** Seam B′ stays interesting only as a future
distribution channel: shipping `agentctl` as a `COMMAND` hook for users who
don't want to embed the adapter.

### Seam C — At the tool boundary

**Mechanism:** wrapping the tool executor.

- **Sees:** each tool call immediately before and after execution.
- **Can:** refuse to execute, or substitute a stored result for a re-execution.
- **Cost:** couples to the harness's tool interface.

### The asymmetry that decides the design

> **Requirement R1 is satisfiable only at Seam C.**
> Everything else we want lives at Seams A and B.

Seam A cannot see effects. Seam B can see them but arrives too late — by the
time the callback fires, the tool has run. Only a wrapper *around* the executor
sits between the decision to act and the act itself.

This produces the defining property of the architecture: **it is a multi-seam
integration with different portability characteristics per seam.** Seams A and
B are stable, published, and harness-agnostic in spirit. Seam C is narrow,
harness-specific, and must be kept as thin as humanly possible — because it is
the one piece that must be re-implemented for every harness we support (R6).

### 3.5 The revised seam table

| Seam | Mechanism | Block | Substitute | Porting cost |
|---|---|---|---|---|
| **A** | LiteLLM `CustomLogger` | ✅ reject request | n/a | zero |
| **B** | Event callback + `block_action` | ✅ | ❌ | low |
| **B′** | `HookConfig` `PRE_TOOL_USE` | ✅ | ❌ | low, subprocess per call |
| **C** | `ToolDefinition.executor` wrap | ✅ | ✅ | the real cost |

**Split the gate across seams by verdict.** `BLOCK` and `ESCALATE` bind at
Seam B; only `SUBSTITUTE` needs Seam C.

The payoff is a failure mode this document originally did not have: **lose
Seam C and the system still fails closed correctly.** It loses clean resume —
the agent sees a rejection where it could have seen the recorded observation —
but it never double-executes. Build it that way deliberately.

---

## 4. Candidate architectures

### Option 1 — Sidecar Observer (fully out-of-band)

The control plane is a separate service. It subscribes to events, reads spend
logs, computes policy, and writes configuration. It never sits on any request
path.

- **For:** zero blast radius. Satisfies R2 perfectly. Simplest to operate.
- **Against:** occupies Seams A and B only. **Cannot satisfy R1.** It can
  detect a double execution after the fact and alarm, but not prevent it.
- **Verdict: rejected.** Fails the hard requirement that motivates the project.

### Option 2 — Inline Interceptor (fully in-band)

The control plane proxies LLM traffic *and* mediates tool execution. All
decisions are made by a live service call.

- **For:** total control. Trivially satisfies R1, R4, R5.
- **Against:** every agent turn now depends on control-plane availability,
  violating R2 and re-creating the SPOF that `0003:F5` corrected. Adds a
  network round-trip to the hot path per tool call. Contradicts the
  control/data plane separation the project is built on.
- **Verdict: rejected.**

### Option 3 — Split plane with a narrow enforcement kernel

Separate the system by *when a decision is needed*, not by what it decides.

- **Control plane (out-of-band, may fail):** policy compiler, cost ledger,
  capability matrix, cache intelligence, replay evaluator. Consumes telemetry.
  Produces compiled artifacts.
- **Enforcement kernel (in-band, must not fail):** two thin adapters at Seams
  A and C that read *local durable state* and *pre-compiled policy*. They make
  no network calls to the control plane on the hot path.

The kernel is deliberately small and stupid: a lookup and a branch. All
intelligence is computed ahead of time by the control plane and handed to the
kernel as data.

- **For:** satisfies R1 (kernel at Seam C), R2 (control plane is off the path;
  the kernel keeps working from local state), R3, R4, R5, R6.
- **Against:** two deployment units instead of one. Policy is eventually
  consistent — a compiled policy can be seconds stale. Acceptable: routing
  policy is not a security boundary.

**Verdict: chosen.** This is the Envoy/xDS shape `0004` asked for, with one
addition xDS does not need — an enforcement point at the effect boundary.

### Comparison

| | Opt 1 Observer | Opt 2 Inline | Opt 3 Split + kernel |
|---|---|---|---|
| R1 no double effects | ✗ | ✓ | ✓ |
| R2 control plane may fail | ✓ | ✗ | ✓ |
| R3 no forks | ✓ | ✓ | ✓ |
| R4 spend attribution | ✓ | ✓ | ✓ |
| R6 portable | ✓ | ✗ | partial (Seam C per harness) |
| Hot-path latency added | none | network RTT | local disk read |
| Operational complexity | low | high | medium |

---

## 5. The chosen architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  AGENT HARNESS  (OpenHands SDK — unmodified)                    │
│                                                                 │
│   Agent.step ──▶ ActionEvent ──▶ [ SEAM C ] ──▶ Tool Executor   │
│        ▲                          effect gate         │         │
│        └────────── ObservationEvent ◀─────────────────┘         │
│                          │                                      │
│                     [ SEAM B ] event callback (observe only)    │
└──────────────────────────┼──────────────────────────────────────┘
                           │
              ┌────────────▼─────────────┐
              │   ENFORCEMENT KERNEL     │  in-band · must not fail
              │                          │
              │   Effect Gate  (Seam C)  │
              │   Request Hook (Seam A)  │
              │                          │
              │   reads: Effect Ledger   │
              │          compiled policy │
              └──────┬────────────┬──────┘
                     │            │
   ┌─────────────────▼──┐    ┌────▼──────────────────────────────┐
   │  EFFECT LEDGER     │    │  LLM DATA PLANE (LiteLLM)         │
   │  local · durable   │    │  routing · fallback · cooldown    │
   │  fsynced · append  │    │  budgets · cache affinity v1      │
   └─────────┬──────────┘    └────┬──────────────────────┬───────┘
             │                    │ [SEAM A] CustomLogger│
             │                    │                      ▼
             │ journal + telemetry│                  PROVIDERS
             ▼                    ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  CONTROL PLANE   out-of-band · may fail · no hot-path role   │
   │                                                              │
   │  Policy Compiler ──────▶ compiled policy ──▶ kernel          │
   │  Cost Ledger & Attribution                                   │
   │  Cache Intelligence ───▶ affinity hints ───▶ kernel          │
   │  Capability Matrix                                           │
   │  Record/Replay Evaluator                                     │
   └──────────────────────────────────────────────────────────────┘
```

### Component responsibilities

| Component | Plane | Responsibility | Verdict |
|---|---|---|---|
| **Effect Gate** | kernel | Consult the ledger before a tool executes; substitute or refuse | BUILD |
| **Request Hook** | kernel | Apply compiled policy and affinity hints; emit telemetry | BUILD |
| **Effect Ledger** | kernel-local | Durable record of tool intent and completion | BUILD |
| **Policy Compiler** | control | Compile declarative policy into kernel-readable artifacts | BUILD |
| **Cost Ledger** | control | Join LiteLLM spend to journal turns | CONFIGURE + thin BUILD |
| **Cache Intelligence** | control | Compute affinity decisions the v1 check cannot | CONFIGURE + BUILD |
| **Capability Matrix** | control | Model equivalence, capability, effect classes | BUILD |
| **Replay Evaluator** | control | Deterministic offline evaluation with stubbed effects | BUILD |
| **Capability Broker** | control | MCP registry federation, capability gating, credential brokerage, provenance | BUILD — **Layer 2** (`0010` §8.3) |
| Journal | *harness* | Append-only event history | CONFIGURE — subscribe |
| Context builder | *harness* | Condensation and context construction | SKIP |
| Routing, fallback, cooldown | *data plane* | Deployment selection and failover | CONFIGURE |

**Nine components in `0002`. Six built here — and only three of those sit on
the hot path.**

---

## 6. The Effect Ledger — the core mechanism

Everything above exists to make this work.

### 6.1 The problem restated mechanically

OpenHands persists `ActionEvent` → runs the tool → persists `ObservationEvent`.
A crash between step 1 and step 3 leaves an orphan. On resume,
`get_unmatched_actions()` finds it and re-executes it (`0006:V1`, `V2`).

The log records **intent** and **outcome**. It has no record of
**commitment** — that the effect actually reached the world. That third state
is the entire gap.

### 6.2 Data model

```
EffectRecord
  tool_call_id      TEXT PRIMARY KEY   -- from the LLM tool call; stable across replay
  conversation_id   TEXT
  action_event_id   TEXT
  tool_name         TEXT
  intent_hash       TEXT               -- sha256(tool_name + canonicalized args)
  effect_class      ENUM
  state             ENUM               -- INTENT | COMMITTED | OBSERVED | FAILED
  started_at        TIMESTAMP
  committed_at      TIMESTAMP NULL
  observation       BLOB NULL          -- stored result, for replay substitution
  fence_token       INTEGER            -- monotonic; rejects writes from a stale worker
```

`tool_call_id` as the primary key is the load-bearing choice: it is generated
by the model, carried in the `ActionEvent`, and *stable across replay* — the
same logical call presents the same key on resume. `intent_hash` is the
integrity check that the replayed call is genuinely the same call.

**This stability assumption is unverified. It is open question 4 in §15, and if
it is false this data model breaks.**

### 6.3 Effect classification

| Class | Examples | Replay policy | Speculation |
|---|---|---|---|
| `PURE_READ` | file read, grep, list | Re-execute freely | ✅ safe |
| `IDEMPOTENT_WRITE` | write full file content, `mkdir -p` | Re-execute freely | ❌ |
| `NON_IDEMPOTENT_WRITE` | append to file, `git commit` | Never re-execute on INTENT | ❌ |
| `EXTERNAL` | HTTP POST, email, webhook | Never re-execute; reconcile | ❌ |
| `DESTRUCTIVE` | `rm -rf`, force push, DROP | Never re-execute; escalate | ❌ |

**Speculation is strictly stricter than replay safety** (`0010` §6.4). An
idempotent write is safe to *repeat* but not safe to perform *speculatively*,
because a speculative write that is later discarded has still mutated the
world. Same classifier, higher threshold — which is how this safety layer
becomes the precondition for the project's largest latency win.

Classification is a function of tool name plus argument inspection, declared in
the capability matrix. **Unclassified tools default to `EXTERNAL`** — the safe
direction. An unknown tool is assumed dangerous.

### 6.4 The write-ahead protocol

```
1. Gate receives (tool_call_id, tool_name, args)
2. Look up tool_call_id in the ledger
   ├─ COMMITTED / OBSERVED → return stored observation. DO NOT EXECUTE.
   ├─ INTENT               → ambiguous. Resolve per §6.5.
   ├─ FAILED               → re-execute (the effect provably did not land)
   └─ absent               → continue
3. Write INTENT, fsync                      ◀── as late as possible
4. Execute the tool                         ◀── the window is between 3 and 5
5. Write COMMITTED + observation, fsync
6. Return observation to the harness
```

Steps 3–5 are the classic write-ahead pattern: **record intent before acting,
record completion after.** The `INTENT` row converts an invisible "did it run?"
into an answerable question.

### 6.5 The ambiguous state — and why it cannot be eliminated

If we crash between step 3 and step 5, the ledger says `INTENT` and we
genuinely do not know whether the effect landed. **This is unavoidable.** It is
the dual-write problem: the ledger and the outside world are two stores, and
there is no atomic commit across them. Any design claiming to remove this
window is lying about physics.

Three things can be done instead:

**(a) Narrow the window.** Write `INTENT` as close to execution as possible.
The exposure is the duration of one tool call, not one turn.

**(b) Decide by class rather than by guess.** `PURE_READ` and
`IDEMPOTENT_WRITE` re-execute — the window does not matter for them, and in
practice they are the large majority of a coding agent's calls. Only the
minority classes reach the hard path.

**(c) Reconcile where the world is queryable.** For many effects the outside
world can answer the question directly:

| Effect | Reconciliation probe |
|---|---|
| `git commit` | Search `git log` for the intent hash in a commit trailer |
| File append | Compare file hash against the pre-recorded hash |
| HTTP POST | Re-send with the same idempotency key; a compliant API dedupes |
| Unknown | No probe — escalate to a human |

Reconciliation is best-effort by design. When it cannot answer, we **fail
closed**: refuse to execute, mark the conversation blocked, surface the
decision to a person. A stalled agent is a recoverable problem. A duplicated
`git push` or a double payment is not.

> **Design rule: the turn is the atomic unit of routing** (`0010` §7.3).
> An endpoint may change between turns and never within one. A turn with
> unresolved tool calls must complete against the endpoint that opened it, or
> be abandoned and replanned as a whole.
>
> Why it matters here: model families mint `tool_call_id` differently, and the
> ledger in §6.2 is keyed on that id. A mid-turn provider switch could make a
> committed effect *invisible* and re-execute it — failover defeating the very
> guard built to prevent double execution. Cheap to enforce at Seam A, which
> already sees whether the outgoing message list ends in unresolved tool calls.

> **Design rule: cost and routing decisions fail open. Effect decisions fail
> closed.** If the cost ledger is unreachable, keep serving and reconcile the
> books later. If the effect ledger is unreachable, stop — because an
> unanswerable "did this already happen?" is the one question we must never
> guess at.

This asymmetry is the most important rule in the architecture.

---

## 7. Cache intelligence — extension, not rebuild

`0007` corrected the verdict: `PromptCachingDeploymentCheck` exists and works
for stable prefixes. We extend rather than replace.

| Known failure (`0006:V7`, `I1`) | Our response |
|---|---|
| Hardcoded 300s affinity TTL | Kernel maintains its own affinity map with a TTL matched to the `cache_control` TTL actually in use |
| 3-message lookback limit | Key affinity on the `cache_control`-marked *prefix*, not the full message list — turn-count-independent |
| Whole-message hashing | Hash only the stable prefix, so appended turns do not invalidate |

The insight the existing implementation misses: **a prompt cache is keyed by a
prefix, so affinity should be keyed by that prefix too.** Hashing the full
message list means the key changes on every turn — which is precisely why
`0006` reports every request landing on a different deployment.

**Use the key the SDK already sends** (`0015` §3). `LocalConversation` threads
`prompt_cache_key` — defaulting to the conversation id — into every call as
OpenAI's provider-side cache-shard hint. A stable per-conversation cache
identity therefore already exists, is visible to the provider, and survives
condensation. Key our affinity map on it rather than hashing prefixes
ourselves: simpler, and consistent with what the provider sees.

Cross-account routing — deciding *which* of our deployments holds the warm
cache — remains entirely ours.

**Justification is cost, not latency** (`0010` §6.3). This section originally
leaned on vendor latency figures. Independent measurement in agentic settings
(`0010:V1`) puts time-to-first-token improvement at **13–31%**, not 85%, while
cost reduction holds at **41–80%**. The cost case is strong; the latency case
is not. Sequence accordingly.

**Try the free win first.** `0010:V1` found that placing volatile content at
the *end* of the system prompt and keeping dynamic tool results out of the
cached prefix beat naive full-context caching. That is a configuration change.
Measure it before writing any cache-intelligence code.

**Sequenced deliberately after the effect ledger.** This is an optimization;
effect safety is a correctness property. Also `0006:U4` may resolve part of it
for free — evaluate `deployment_affinity` before writing any of this.

---

## 8. Cost attribution

The data exists on both sides and does not meet in the middle (`0006:I4`).

```
LiteLLM_SpendLogs.session_id  ◀── from x-litellm-trace-id
                              ▲
                              │  the bridge that does not exist by default
                              ▼
OpenHands ActionEvent.id / conversation_id
```

**Half of this is already free** (`0015` §5). The SDK sends
`x-litellm-session-id` set to the conversation id on every call, and LiteLLM
populates `LiteLLM_SpendLogs.session_id` from that header (`0006:V10`). So
**conversation-level cost attribution works today with zero code.**

The remaining gap is granularity: the metric that matters is cost per
*completed task*, which needs turn resolution. The Request Hook adds the turn
component to the id the SDK already supplies — a smaller job than this section
originally described.

`0006:U2` / `0009` Q5 — **resolved**.

---

## 9. Policy compiler and capability matrix

The **policy compiler** turns declarative intent into a kernel-readable
artifact evaluated by local lookup:

```yaml
pools:
  primary: [openrouter/acct-a, openrouter/acct-b]
constraints:
  - never_route: anthropic-direct
    unless: explicitly_enabled
  - max_cost_per_task_usd: 5.00
  - require_capability: [tool_calling, prompt_cache]
effect_policy:
  destructive: require_human_approval
  external:    reconcile_or_block
```

Compilation happens out-of-band; the kernel only evaluates. This is what keeps
R2 satisfiable.

The **capability matrix** is the reference data both the compiler and the
effect classifier read: per-model context limits, tool-call dialect, cache
support and minimum cacheable prefix, vision, reasoning tokens — and per-tool
effect classes. Unglamorous, and every other component depends on it.

---

## 10. Failure analysis

Walking every crash point. This is how the design is validated.

| # | Crash point | Ledger state | Behavior on resume |
|---|---|---|---|
| 1 | Before `ActionEvent` persisted | absent | Harness replans. No effect occurred. Safe. |
| 2 | After `ActionEvent`, before gate | absent | Gate sees no record → executes once. Safe. |
| 3 | After `INTENT`, before tool ran | `INTENT` | **Ambiguous.** Class-based resolution (§6.5). |
| 4 | Mid tool execution | `INTENT` | **Ambiguous.** Same path. |
| 5 | After tool, before `COMMITTED` | `INTENT` | **Ambiguous.** Worst case — the effect *did* land. |
| 6 | After `COMMITTED`, before observation returned | `COMMITTED` | Gate substitutes stored observation. Safe. |
| 7 | After `ObservationEvent` persisted | `OBSERVED` | Harness sees a matched action. Nothing to do. Safe. |
| 8 | Control plane down | any | Kernel runs on last compiled policy + local ledger. Work continues. |
| 9 | Effect ledger unreadable | unknown | **Fail closed.** Block before any non-idempotent tool. |
| 10 | Two workers resume the same conversation | any | Fence token rejects the stale writer. |

Rows 3–5 are the irreducible ambiguity. Everything else is deterministic.

The architecture's honest claim: **we convert an unbounded double-execution
risk spanning every crash into a bounded one spanning a single tool-call
window, with class-based and reconciliation-based mitigation inside that
window.**

That is a real and defensible guarantee. "Exactly-once effects, always" would
not be.

---

## 11. What we are deliberately not building

Recorded so it is hard to drift back in:

- Context construction and summarization → condensers (`0007`)
- A session/event store → OpenHands `EventLog` (`0007`)
- Routing strategies, load balancing, cooldowns, retries, budgets → LiteLLM
- A durable-execution engine → deferred to Phase 5; the effect ledger is the
  cheap 80% and does not require rewriting the agent loop as workflow code
- Multi-agent orchestration
- A dashboard

---

## 12. Portability

R6 says no structural coupling to OpenHands. The seam analysis makes the cost
of portability explicit and *bounded*:

| Seam | Coupling | Porting cost per new harness |
|---|---|---|
| A — Request Hook | LiteLLM `CustomLogger` | **Zero.** Harness-independent. |
| B — Journal + `block_action` | Harness event API | Low — a normalization adapter. Carries `BLOCK`/`ESCALATE`. |
| C — Effect Gate | Harness tool interface | **The real cost.** Carries `SUBSTITUTE` only. |

Because the verdict split (§3.5) puts only `SUBSTITUTE` behind Seam C, a new
harness gets correct fail-closed behaviour from Seam B alone. Full resume
quality then follows when its executor wrap is written. **Portability degrades
gracefully rather than all-or-nothing.**

So the portability strategy is: **keep Seam C minimal.** The gate should
contain no policy, no classification logic, and no I/O beyond the ledger — a
lookup, a branch, and two writes. Everything else lives behind a
harness-neutral interface.

If the gate is 150 lines, supporting a second harness is a weekend. If it is
1500, it never happens.

---

## 13. Technology positioning

Deliberately boring, and deferred where possible.

| Concern | v1 choice | Rationale |
|---|---|---|
| Effect ledger store | SQLite, WAL mode, fsync on commit | Single-writer, local, durable, zero ops. Correct until multi-host. |
| Control plane store | Postgres (shared with LiteLLM spend logs) | The join in §8 wants one database. |
| Compiled policy transport | File on disk, watched | No network dependency on the hot path (R2). |
| Kernel language | Python | Must run in-process with both LiteLLM hooks and the OpenHands executor. |
| Kernel hot-path cost | **Negligible — measured concern closed** |
| Redis | **Not in v1** | `0004` Phase 9 asks where it is justified. Nothing here needs cross-host live coordination yet, and adding it would put a network hop on the effect path — precisely wrong. |

On kernel cost: `0010:V3` measures LLM generation at up to **96% of
end-to-end agent-loop latency**, with tool execution roughly constant. A local
SQLite read at Seam C is invisible against a multi-second generation, so
**the in-band kernel is latency-safe by construction.** That was an open worry
in the original draft; it is now closed.

Note the Redis position, because it inverts a common instinct: **the effect
ledger is the last thing that should live in a cache.**

---

## 14. Build sequence

Revised from `0004`, reordered by what `0006` found.

| Step | Deliverable | Gate to pass |
|---|---|---|
| 0 | **Falsification experiment** — reproduce double-execution | `0006:U1` resolved either way |
| 1 | Effect ledger + gate, `PURE_READ` / `IDEMPOTENT_WRITE` only | Crash at every point in §10; no duplicates |
| 2 | Effect classification + capability matrix seed | Unknown tools default to `EXTERNAL` |
| 3 | Reconciliation probes for git and filesystem | Rows 3–5 resolve without human input for git |
| 4 | Request hook + trace-id bridge + cost attribution | Cost per completed task is queryable |
| 5 | Record/replay evaluator | Policy changes testable without spend |
| 6 | Cache intelligence | Measured improvement over the built-in check |
| 7 | Policy compiler | Declarative policy enforced by the kernel |

**Step 0 is not optional and is not a build.** If `U1` resolves to "a dedup
guard already exists," step 1 largely disappears and this document needs a
successor.

---

## 15. Open decisions blocking ACCEPTED status

| # | Question | Status |
|---|---|---|
| 1 | Does an executor-level dedup guard already exist? | ✅ **No** — double execution reproduced (`0014`) |
| 2 | Is `tool_call_id` stable across resume? | ✅ **Yes** — byte-identical (`0014`) |
| 3 | Can a tool executor be wrapped without forking? | ✅ **Yes** — via `ToolDefinition.executor` (`0014`) |
| 4 | Does OpenHands drive `/v1/chat/completions`? | ✅ **Yes** (`0014`) |
| 5 | Does OpenHands forward a trace id? | ✅ **Yes** — `x-litellm-session-id` (`0015`) |
| 6 | Does `prompt_cache_key` serve our affinity need? | ✅ **Partially** — reuse as the key (`0015`) |
| 7 | Is `hook_config` a fourth seam? | ✅ **Partially** — corrects §3 (`0015`) |
| 8 | Does `max_budget_per_run` cover the budget guard? | ✅ **Partially** — per-run yes, per-day no (`0015`) |
| **9** | **Does `deployment_affinity` supersede `prompt_caching`?** | ⏳ **OPEN** (`0009` Q4) — §7 may shrink to configuration |

**Q4 in `0009` is the last blocker.** It is a ~30-minute source read, and it can
only *reduce* scope — so this document is safe to build against now, with §7
provisional.

One caveat on confidence: everything from `0015` is read from source but **not
executed**. `0014`'s findings were executed. Confirm the `block_action`
behaviour empirically in M2 before relying on the §3.5 verdict split.
