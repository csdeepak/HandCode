---
Number:        0013
Title:         Personal Use & Future Scope
Type:          GUIDELINE
Status:        LIVING
Created:       2026-09-05
Supersedes:    —
Superseded-by: —
Depends-on:    0012
---

# 0013 — Personal Use & Future Scope

`0012` plans the engine. This plans the thing you actually live with.

It also corrects a scope decision I made too early: **the dashboard is back.**
`0008` §11 excluded it as "a read view over the ledger, much later." That was
wrong for this project. The dashboard is how you experience the value, it is
where the ledger's data becomes legible, and it teaches a stack the kernel
never will.

---

## 1. The daily reality this must serve

Stated plainly, because every feature below follows from it:

- **Credits are scattered across free tiers** — OpenRouter, Google AI Studio,
  Cerebras, Mistral, plus occasional paid access. This is not rate-limit
  evasion; it is how you run agent loops on a student budget using accounts you
  legitimately hold across *different* providers.
- **Budget is the binding constraint**, not scale. A run that silently burns
  paid credits is a worse failure than a run that stops.
- **Work happens in sessions that get interrupted** — classes, laptop sleep,
  network drops, closing the lid.
- **You want to know where the money went**, at the granularity of "this task."
- **This is a learning vehicle.** A feature that teaches nothing is worth less
  than one that does, even if it is more convenient.

> **Correction to `0003:F4`.** I raised provider-terms concerns about
> multi-account routing. Using free tiers you legitimately hold across
> *different* providers is ordinary multi-provider routing and is not what
> those concerns were about. They apply only to creating multiple accounts on
> *one* provider to get past that provider's limits. The policy compiler should
> make the distinction expressible, not treat the whole idea as suspect.

---

## 2. The free-tier orchestrator — your actual killer feature

This is the thing you originally asked for, and it survives the reframe intact.
It is not "failover." It is **budget-aware routing across a heterogeneous pool
of free allowances.**

What makes it non-trivial, and therefore worth building:

| Problem | Why it is hard |
|---|---|
| Every free tier has different limits | RPM, TPM, daily tokens, monthly credits — no common unit |
| Most expose no quota signal | Reactive-only; you must model consumption yourself |
| Models differ in capability | A Cerebras Llama is not a drop-in for Claude on a hard refactor |
| Resets are on different clocks | Per-minute, daily UTC, calendar month |
| Cache affinity fights rotation | Rotating for quota destroys the warm cache (`0010` §6) |

**The design:** a local consumption model per endpoint, updated from Seam A
telemetry, predicting remaining allowance and next reset. Routing then becomes a
constrained choice — *cheapest endpoint that can do this task, has allowance
left, and preferably holds the warm cache.*

```yaml
# control/matrix/data/allowances.yaml
endpoints:
  google-ai-studio/flash:
    limits: { rpm: 15, tpd: 1_000_000 }
    resets: { rpd: "00:00 UTC" }
    tier: cheap
    capabilities: [tool_calling, long_context, vision]
  cerebras/llama-70b:
    limits: { rpm: 30, tpd: 1_000_000 }
    tier: cheap
    capabilities: [tool_calling]
    notes: "very fast; weak on multi-file refactors"
  openrouter/free-pool:
    limits: { rpd: 50 }
    tier: mid
```

Slots into `0012` M7 as the first real consumer of the policy compiler, and it
is the feature you would notice missing on day one.

---

## 3. The dashboard — restored

Not a monitoring wall. **A daily driver**, answering four questions you actually
ask.

### Panel 1 — "Can I work right now?"

Endpoint cards showing predicted remaining allowance, next reset, health, and
which one holds your warm cache. Green means go. This replaces the current
workflow of *try it and see what 429s*.

### Panel 2 — "What is my agent doing, and what has it cost?"

Live turn stream for the running session: model, tokens, cache hit or miss,
cost, latency, and each tool call with its **effect class as a coloured chip**.
A `DESTRUCTIVE` chip appearing is information you want immediately.

Running total against the daily budget.

### Panel 3 — "What happened while I was away?"

Session list with status, cost, duration, and — the one no other tool has —
**blocked effects awaiting your decision.** When the gate fails closed, this is
where you resolve it: what the agent intended, what the probe found, and
buttons for *it landed, skip it* / *it did not, run it* / *abandon the turn*.

That panel is the human half of `0008` §6.5, and without it the fail-closed
design is unusable in practice.

### Panel 4 — "Where did the money go this week?"

Cost per completed task, cost by model, cache hit ratio over time, and spend by
endpoint. This is where you learn whether your routing policy is any good.

**Stack:** FastAPI over the same Postgres the control plane uses, plus a small
React or HTMX front end. Read-only except for the blocked-effect resolution.
Never on the request path — if the dashboard is down, agents keep running.

**Milestone M8**, after M5 gives it data worth showing.

---

## 4. Daily-driver features

Small, personal, and the difference between a project and a tool you use.

| Feature | Why it matters to you |
|---|---|
| `agentctl resume <session>` | Lid closed, train arrived, laptop slept. Pick up exactly where it stopped. |
| `agentctl cost today` | One line: spent, remaining, tasks completed. |
| `agentctl why <turn>` | Why did routing pick that endpoint? Prints the decision inputs. Invaluable for debugging your own policy. |
| `agentctl blocked` | List effects awaiting a decision; resolve from the terminal. |
| Budget guard | Hard stop at the daily cap, with an explicit confirm to exceed. Never a surprise bill. |
| Push notification on block or completion | Long runs shouldn't need babysitting. |
| Session journal export | One markdown file: what the agent did, decided, changed, and cost. Genuinely useful for a report or a portfolio. |

`agentctl why` deserves emphasis: a routing system you cannot interrogate is one
you cannot improve. Build it early, and it makes M7 tractable.

---

## 5. Integrating multiple systems

You asked how to connect things together. There are five surfaces, and they
have very different costs.

| Surface | Mechanism | Cost | When |
|---|---|---|---|
| **LLM providers** | LiteLLM proxy, OpenAI-format endpoint | Config only | M1 |
| **Agent harness** | Seam C executor wrap + Seam B events | ~150 lines per harness | M2 |
| **Tools & MCP** | Capability Broker at Seam C | Moderate | Layer 2 |
| **Editors / CLI** | Anything speaking OpenAI-compatible | Free | Falls out of M1 |
| **Notification / mobile** | Webhook out of the control plane | Trivial | Any time |

### The integration principle

**Integrate at the narrowest interface that carries the semantics you need.**

- Providers speak one wire format — LiteLLM already normalises it, so integrate
  by *configuration* and write nothing.
- Harnesses differ structurally — so integrate by a *small adapter* and accept
  that cost knowingly.
- Everything else should reach you through an interface you already expose.

The payoff of that last point: because the kernel binds at the LiteLLM layer,
**Claude Code, Aider, Cline, and Continue all work through it with no extra
code** — they already speak OpenAI-compatible. You get budget control and cost
attribution across every AI tool you use, from one integration. OpenHands is
just the one that also gets effect safety, because that needs Seam C.

That is the strongest argument for this architecture that isn't in `0008`.

### Multi-machine

If you work across a laptop and a desktop: the effect ledger stays **local and
single-writer** (SQLite, per `0012` §13), while the control plane's Postgres is
shared. Never put the ledger behind a network — the lease and fence-token
design (`0012` §2.1) exists precisely so two machines cannot resume the same
conversation and both act.

---

## 6. The learning ladder

Each milestone maps to a skill that transfers well beyond this project.

| M | You will genuinely learn |
|---|---|
| M0 | Reading unfamiliar source to answer a specific question — the core research skill |
| M1 | Gateway and proxy architecture; why endpoint format silently changes behaviour |
| M2 | Write-ahead logging, fsync, durability — the foundation of every database |
| M3 | Policy as data; why the classification table is reviewable and code is not |
| M4 | Idempotency and reconciliation; exactly-once effects vs exactly-once delivery |
| M5 | Distributed tracing and telemetry joins |
| M6 | Deterministic testing of nondeterministic systems |
| M7 | DSL design; control/data plane separation |
| M8 | Full-stack: API, real-time updates, information design |
| L2 | Context engineering, speculative execution, protocol integration |

M2 and M4 are the ones that make you a systems engineer rather than someone who
wires APIs together. They are also the least glamorous. Do them properly.

---

## 7. Future scope, honestly tiered

**Layer 2 — after the core works**

- Capability Broker and multi-source MCP (`0010` §8.3)
- Speculative execution, gated on Q9 (`0010` §6.4)
- Cache-aware context layout — likely the cheapest real win available
- Cross-model drift measurement

**Layer 3 — speculative**

- Multi-agent, only once single-agent state is genuinely solid
- Effect-safety as a standalone library — plausibly the most reusable thing
  here, and worth extracting once M4 proves it
- Public multi-tenant BYOK service — a real product, and a completely different
  project with security and compliance obligations. Do not drift into it
  accidentally.

**Explicitly not planned**

Skills, subagents, command palettes, a context/memory layer (`0010` §9.1,
`0007`). The harness owns these and does them better.

---

## 8. If I were building this for myself

The honest version, in order:

1. **Run M0 this week.** Two hours. It either validates the thesis or saves you
   months. Nothing else matters until it is done.
2. **Get to M2 and then actually use it daily.** A crash-safe agent is
   independently valuable. Using your own tool is what surfaces the real
   requirements, and no amount of design substitutes for it.
3. **Build M5 before M4.** `0012` orders them the other way, and I would swap
   them in practice — seeing cost per task changes your behaviour immediately
   and keeps you motivated, whereas M4 is invisible until something crashes.
4. **Build the dashboard earlier than the plan says.** M8 is where it sits
   logically, but you will want Panel 1 from week two, and it is the piece
   you can show people.
5. **Keep the chaos suite green.** It is the one thing that makes this
   engineering rather than scripting.
6. **Write down what breaks.** Every failure is a numbered document. In a year
   that record is worth more than the code.

The trap to avoid: this design is interesting enough to keep designing
indefinitely. Eleven documents and no code is currently correct — you asked not
to rush, and the research genuinely reshaped the project. But `0012` M0 is now
the only thing standing between plan and evidence.

**Go run it.**
