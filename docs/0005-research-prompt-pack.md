# Research Agent Prompt Pack — AI Agent Control Plane

**How to use this file**

1. Paste **Part A (Master Brief)** once, at the start of a research session. It sets the role, source rules, and output contract.
2. Then paste **one phase prompt at a time** from Part B. Wait for the deliverable. Read it. Only then move on.
3. Keep every deliverable as `research/phase-N-<topic>.md` in one repo. By Phase 9 this is your engineering notebook, and it is more valuable than the code you'll write in the first month.
4. Phases 0 and 1 are prerequisites for everything else. Phases 4/5 (distributed systems, orchestration) can run in parallel with 2/3 if you want variety.

**Do not skip Phase 0.** Its only job is to tell you what not to build.

---

# PART A — MASTER BRIEF

> Paste this once per research session. Re-paste if the agent starts drifting or citing blog posts.

You are my research partner on a long-running systems engineering project. I am building an **AI Agent Control Plane**: a layer that makes long-running LLM agent loops recoverable, measurable, and cost-efficient, sitting beside (not inside) an existing LLM data plane.

I have two goals, equally weighted:
1. **Decide correctly** — avoid building things that already exist, and find the real gaps.
2. **Learn deeply** — I want to become a strong AI infrastructure engineer, not just assemble a project. Explain mechanisms, not just conclusions.

## Architecture I am working toward

```
CLIENT / AGENT (OpenHands, and later others)
      |
      v
LLM DATA PLANE (LiteLLM proxy or equivalent) ---> PROVIDERS
      |
      | telemetry / config
      v
MY CONTROL PLANE
  policy compiler | cost ledger | cache intelligence
  capability matrix | session/turn journal
  context/memory layer | record-replay evaluation
```

**Guiding principle:** the model/provider endpoint can change; the logical agent work must remain recoverable, measurable, and cost-efficient.

## The five problems I believe are actually hard

1. **Prompt-cache affinity** — switching endpoints discards a warm cache, spiking cost and latency on long agent contexts.
2. **Mid-tool-call failure** — a side-effecting tool executes, the enclosing LLM request fails, replay executes it twice.
3. **Cross-model drift** — identical durable state produces different plans across models.
4. **Durable execution** — agent work must survive process, network, and provider failure.
5. **Policy correctness** — routing must respect explicit constraints and legitimate provider usage terms.

## Rules of engagement — follow these on every response

**Source hierarchy.** Prefer sources in this order, and say which tier each claim came from:
- **T1** — source code, official API reference, official docs, provider changelogs, RFCs, peer-reviewed papers.
- **T2** — official engineering blogs, maintainer comments in GitHub issues/PRs, conference talks by maintainers.
- **T3** — third-party blogs, tutorials, Medium/Substack, forum posts.

**Never** let a T3 source be the sole basis for a claim that changes what I build. This ecosystem moves monthly and most tutorial content is stale.

**Date everything.** Every claim gets the publication or last-commit date of its source. If you cannot date it, mark it undated and downgrade confidence. Flag anything older than 12 months as possibly stale.

**Read code, not summaries.** When a question is about how OpenHands or LiteLLM behaves, find the actual file, function, or class and cite `path/to/file.py::ClassName.method` with a permalink to a specific commit or tag. Do not describe behavior you have only read about.

**Confidence tiering is mandatory.** Split every deliverable into:
- **VERIFIED** — traced to a T1 source I could check myself.
- **INFERRED** — reasoning from partial evidence. State the inference chain.
- **UNKNOWN** — could not determine. Say what would resolve it.

An honest UNKNOWN is more useful to me than a confident guess. Do not pad.

**Hunt for gaps, not features.** For every existing tool you examine, the most valuable output is: *what does this NOT do that my roadmap assumes I need to build?* End every deliverable with a "should I build this?" verdict.

**Contradict me.** If my architecture, my assumptions, or my problem framing are wrong, say so directly and show the evidence. I would rather be corrected in research than in production. Do not soften findings to be agreeable.

**Version-pin.** State the exact version, tag, or commit of any software you describe. "LiteLLM supports X" is useless; "LiteLLM v1.6x, `router.py::Router.async_function_with_fallbacks`, supports X" is useful.

## Output contract — every phase deliverable uses this structure

```markdown
# Phase N — <topic>

## 1. Executive answer
Three to six sentences. What did I learn that changes what I build?

## 2. VERIFIED
Claims traced to T1 sources. Each with: claim, source link, exact
location (file::symbol, or doc section), source date.

## 3. INFERRED
Claim, evidence, inference chain, and what would confirm or falsify it.

## 4. UNKNOWN
Open questions, and the specific experiment or source that would close them.

## 5. Mechanism explanation
Teach me how this actually works, at the level of a systems engineer who
will implement it. Include the data structures and the failure modes.
Assume I know Python and basic backend engineering; do not assume I know
this subsystem.

## 6. Gap analysis — what I should NOT build
Which parts of my roadmap does existing software already cover?
Which parts are genuinely unserved?
Verdict per component: BUILD / CONFIGURE / SKIP / UNRESOLVED.

## 7. Hands-on exercise
One concrete, runnable exercise (under ~2 hours) that makes me understand
this by doing it. Include what to observe and what would surprise me.

## 8. Sources
Full list, tiered and dated.
```

Confirm you understand this brief, then wait for my first phase prompt. Do not begin researching yet.

---

# PART B — PHASE PROMPTS

Run these in order. One at a time.

---

## Phase 0 — Existing-system reconnaissance

> **The most important phase.** Its purpose is to shrink the project.

Research what **OpenHands** and **LiteLLM** already do, so I can delete duplicated work from my roadmap. Read the source, not the marketing.

**OpenHands** (github.com/All-Hands-AI/OpenHands — pin the version you read):
- How is conversation/agent state represented and persisted? Find the actual state class, the event stream/event log, and the storage backends.
- Is the event log append-only? Can agent state be fully reconstructed by replaying it, or is there hidden in-memory state that is lost on crash?
- **Critical:** in the agent loop, is a tool action persisted to the event log *before* or *after* the tool executes? Trace the exact ordering. This single fact determines whether replay can double-execute side effects.
- What happens when an LLM call raises mid-loop — rate limit, timeout, connection error? Where is that handled, what is retried, and what state survives?
- How does pause/resume work? What exactly is restored?
- How does it configure LLM calls — does it call LiteLLM directly, and how are model strings, base URLs, and keys threaded through?
- What context management exists (condensers, summarization, truncation, repo/microagent context)? Which condenser is the default?
- What metrics does it already record per request (tokens, cost, latency, cache tokens)?

**LiteLLM** (github.com/BerriAI/litellm — pin the version):
- Router: what routing strategies exist, and how does each actually pick a deployment? Read the selection code.
- Fallbacks: model-level, context-window, content-policy. What triggers each? Is state preserved across a fallback?
- Cooldowns: how is a failing deployment removed from rotation, and how does it return?
- Budgets and rate limits: what can be enforced per key, team, user, and deployment? Where is that state stored?
- Telemetry: what response headers does the proxy return, what does the spend-log schema contain, and what Prometheus metrics exist?
- **Extension points:** what callback/hook interfaces exist for injecting custom logic pre- and post-call? This determines whether my control plane can be a plugin rather than a fork.
- **The decisive question:** does any routing strategy account for *prompt-cache affinity* — i.e. does it prefer the deployment holding a warm cache for this prefix? Show me the code that would do it, or confirm it does not exist.

**Deliverable:** a component-by-component table of my roadmap (§2 of my architecture: policy compiler, cost ledger, cache intelligence, capability matrix, session/turn journal, context/memory layer, record-replay evaluation) with a verdict of BUILD / CONFIGURE / SKIP / UNRESOLVED and the evidence for each.

---

## Phase 1 — LLM request lifecycle

Teach me the request lifecycle at the level of someone who will write the client, handle every failure, and be responsible for correctness.

- The stateless request model: what the server retains between calls (and what it does not), and why this makes "session continuity" mostly a client-side problem.
- Streaming: SSE mechanics, chunk shapes, how tool calls arrive incrementally, and what a *partial* stream leaves you holding. What is the correct behavior when a stream dies after some tool-call arguments have arrived but before the message completes?
- Tool/function calling across providers: request schema, response schema, multi-tool-call turns, parallel tool calls, and how the tool result must be fed back. Where do Anthropic, OpenAI, and Gemini differ structurally, not just cosmetically?
- The full error taxonomy: 429 vs 400 vs 500 vs 529, connection resets, read timeouts, mid-stream aborts. Which are safely retryable and which are not — and crucially, which errors leave *ambiguity* about whether the request was actually processed and billed?
- Reasoning/extended-thinking models: what extra state do they return, and does it need to be preserved across turns for correctness?
- Token accounting: where usage appears in streaming vs non-streaming responses, and how to get usage when a request fails partway.

**Then build:** specify a minimal agent loop — LLM call, tool dispatch, observation, repeat — in about 200 lines of Python with no framework. Give me the code skeleton and a list of every failure point in it. This becomes my laboratory for the rest of the project.

---

## Phase 2 — Context engineering

This is a core skill I want to own, independent of this project.

- The distinction between the model's context window, durable memory, and retrieval — and the standard architecture that connects them.
- **Context degradation:** what does the current evidence actually say about model performance as context grows? Cover long-context benchmarks, "lost in the middle," and recent work on context rot. Where is the empirical knee in the curve for current frontier models? Be specific about which models and which benchmarks, and be honest about how contested this is.
- History selection strategies for agent loops: full history, sliding window, summarization/condensing, hierarchical summary, structured scratchpad, tool-result truncation. What are the failure modes of each in a *coding* agent specifically?
- **Cache-aware context construction:** how does prompt-prefix caching constrain the way you order and mutate context? Why does mutating anything early in the prompt destroy the cache for everything after it, and what layout rules follow from that? This is the most important part of this phase for my project.
- Compression: extractive vs abstractive summarization, LLMLingua-style token compression, what each costs in fidelity, and when it is worth it.
- Structured project memory for coding agents specifically: decision logs, file-level summaries, repo maps, agent-authored notes-in-repo. What does the evidence say about whether vector retrieval beats grep + structure for code? Give me the honest answer, including the case against RAG here.
- How Claude Code, Aider, and Cline each handle context and compaction. Compare their actual approaches.

**Deliverable:** design a **context builder** interface — given durable session state, a target model, and a token budget, produce a request. Specify the data structures, the ordering rules that preserve cache prefixes, and the eviction policy.

---

## Phase 3 — Agent execution state

- Formalize the agent loop as a state machine. What are the states, what are the legal transitions, and where exactly are the interruption points?
- Define a **turn** precisely enough to implement: what belongs inside one turn boundary, and what makes a turn complete vs partially complete? When an LLM response contains three tool calls and the second one fails, what is the state?
- What state must be durable for a resume to be *correct*, versus merely to look correct? Enumerate: conversation events, tool results, workspace/filesystem, git state, terminal/process state, MCP connections, open handles, in-flight approvals.
- **Non-reconstructible state:** what genuinely cannot be recovered by replaying a log — running processes, network connections, external side effects already committed — and what are the standard strategies for each?
- Workspace and git consistency: how do you snapshot and restore an agent's working tree so that the journal and the filesystem agree? Compare git-based approaches, container snapshots, and copy-on-write filesystems.
- How do existing agent frameworks checkpoint? Study **LangGraph checkpointers** in depth (threads, checkpoint namespaces, interrupt/resume, the pending-writes mechanism) — it is the closest existing analog to what I want. Also look at OpenAI Agents SDK sessions and Claude Agent SDK state handling.

**Deliverable:** a concrete schema for my session/turn journal. Tables or event types, fields, indices, and the invariants that must hold after a crash at any point.

---

## Phase 4 — Distributed systems foundations

Teach me only the subset I actually need, grounded in this project. No general survey.

- Durability and write-ahead logging: why "write intent before acting" is the foundation of every recovery system, and how it maps onto my turn journal.
- Delivery semantics: at-most-once, at-least-once, effectively-once. Why exactly-once *delivery* is impossible and exactly-once *effects* is achievable. This distinction is the heart of my correctness problem — make sure I understand it precisely.
- **Idempotency keys done properly.** Study Stripe's design as the canonical practical reference: key generation, request fingerprinting, storing the response, handling concurrent duplicate requests, expiry. Then map it onto agent tool calls.
- The dual-write problem and the outbox pattern. Where does this appear in my system? (Hint: journal + filesystem, journal + provider call.)
- Retries and backoff: exponential backoff with jitter, retry budgets, circuit breakers, and why naive retries amplify outages.
- Leases and fencing tokens: how to stop two workers from resuming the same session simultaneously, and why a lease alone is not sufficient without fencing.
- Failure detection: the fundamental ambiguity between slow and dead, and what timeouts can and cannot tell you.

**Anchor every concept to a specific scenario in my system.** Abstract explanations are not useful to me here.

---

## Phase 5 — Durable execution and workflow orchestration

- **Study Temporal deeply.** Its model — deterministic workflow code, non-deterministic work isolated in activities, event-history replay, workflow versioning — is the most mature solution to my exact class of problem. Explain how replay-based recovery works mechanically, why determinism is required, and how activity results are recorded so they are not re-executed.
- Then compare: Restate, DBOS, Inngest, Cloudflare Workflows, AWS Step Functions. What is each one's core abstraction and what does it buy?
- **Vercel Workflow (WDK)** — evaluate it specifically, since it targets long-running agentic work and step-based durable execution.
- **The critical mapping question:** an LLM call is a non-deterministic activity. A tool execution is a side-effecting activity. Does the durable-execution model map cleanly onto an agent loop, or does it break down? Where and why? Be skeptical here — several teams have tried this and I want to know what went wrong.
- Human-in-the-loop: how do these systems model an indefinite pause for approval, and how does that interact with leases and timeouts?
- Workflow versioning: what happens when I change agent logic while sessions are mid-flight? This is the problem everyone discovers too late.
- Compensation and sagas: when a rollback is impossible (the agent already pushed a commit), what are the real options?

**Deliverable:** a direct recommendation — should I adopt an existing durable-execution engine, or build the turn journal myself? Argue both sides with evidence, then commit to one.

---

## Phase 6 — Routing intelligence and cache economics

The commercial and intellectual core of the project.

**Provider cache semantics — get this exactly right, with citations:**
- Anthropic: explicit `cache_control` breakpoints, breakpoint limits, minimum cacheable prefix length per model, default and extended TTLs, write vs read pricing multipliers, the usage fields that report cache creation and cache reads, and the **scope** of the cache (which key/org/region shares it).
- OpenAI: automatic prefix caching, minimum length, TTL, the usage field reporting cached tokens, and any routing-affinity mechanism for improving hit rate.
- Google Gemini: implicit vs explicit context caching, the cached-content resource lifecycle, minimums and TTL.
- DeepSeek and other cost-sensitive providers: cache mechanics and reported hit metrics.
- **OpenRouter specifically:** does it pass cache-control through to upstream providers, and does its own provider-selection behavior destroy cache affinity? Determine this carefully — it directly decides whether OpenRouter can be in a cache-affinity pool at all.
- Bedrock and Vertex: cache support and how scoping differs from first-party APIs.

**Then:** build me a cost model. For a realistic long agent loop — say 60 turns, a context growing from 20K to 150K tokens — quantify the cost and latency difference between staying on a warm-cache endpoint and switching accounts each time quota tightens. Show the arithmetic. I want to know the real size of this prize before I build for it.

**Rate-limit and quota signals:**
- Exactly which headers or endpoints each major provider exposes for remaining requests, remaining tokens, reset times, and credit balance. Which providers expose nothing, forcing purely reactive handling?

**Routing prior art:**
- Read the **FrugalGPT** and **RouteLLM** papers. What do they actually demonstrate about cascades and quality-preserving cost reduction, and what are the limits of their results?
- Survey the commercial layer: Vercel AI Gateway, Portkey, Helicone, OpenRouter's own routing, Martian, Not Diamond, Requesty. For each: what routing signals does it use, and does *any* of them route on cache affinity?
- Task-aware model tiering for coding agents: what evidence exists on which sub-tasks (file reading, search, lint fixes, planning, complex edits) can be safely downgraded to cheaper models, and what breaks when you do?

**Policy and terms:** summarize what major providers' terms actually say about multiple accounts, key sharing, and rate-limit circumvention. I want to design within legitimate patterns — separate orgs I genuinely hold, BYOK multi-tenant, and multi-provider pools — not around the rules. Quote the relevant terms sections and link them.

**Deliverable:** a routing decision function. Inputs, scoring, hard constraints vs soft preferences, and explicitly how cache affinity is weighted against cost and availability.

---

## Phase 7 — The correctness boundary

The part that must be right or the whole project is worthless.

- **Side-effect classification.** Build me a taxonomy of agent tool calls by replay-safety: pure reads, idempotent writes, non-idempotent writes, externally-visible effects (git push, HTTP POST, email, payment), and irreversible destructive operations. What is the correct handling policy for each class under replay?
- The core scenario, in full mechanical detail: the model emits a tool call, the tool executes and commits a side effect, the response is lost before the observation is journaled. Walk through every strategy for making this safe — write-ahead intent logging, idempotency keys on tool calls, effect fingerprinting, two-phase execution, post-hoc detection and reconciliation. Give me the trade-offs, not a single answer.
- How do you *detect* that a side effect already happened, when the tool itself gives you no idempotency support? What can be reconstructed from the filesystem and git, and what cannot?
- Transactional boundaries: what should be atomic in my system, and where is atomicity genuinely impossible?
- Audit trail design: what must be recorded to reconstruct after the fact exactly what an agent did, why, on which model, at what cost — and what belongs in it for a security review.
- Secrets: how do you keep provider keys out of the journal, the logs, and the replay traces, while keeping the traces useful? Cover envelope encryption and redaction-at-write.

**Deliverable:** the safety rules for my turn journal, written as explicit invariants — statements that must hold after a crash at any instruction.

---

## Phase 8 — Evaluation without burning tokens

I cannot iterate on routing if every test run costs money and takes minutes.

- **Record/replay for LLM traffic:** how do you capture real provider interactions and replay them deterministically? Study VCR-style HTTP cassettes (`vcrpy`, `pytest-recording`), transport-layer interception with httpx, and LiteLLM's own caching. What breaks with streaming responses, and how do you record and replay an SSE stream faithfully?
- **Failure injection:** how do I deterministically produce 429s, timeouts, mid-stream aborts, and partial tool executions in tests? Cover proxy-level tools (toxiproxy) and in-process transport stubs. Which layer gives better fidelity?
- **Router benchmarking:** how do I evaluate a routing policy offline against recorded traces? What is the methodology — replay the same trace under different policies and compare cost, latency, and cache hit rate? What are the validity threats when the trace was recorded under a different policy?
- **Agent task benchmarks:** how do SWE-bench and SWE-bench Verified actually work, what does OpenHands' own evaluation harness provide, and can I reuse it as my end-to-end test bed?
- **Metrics that matter:** define precisely how to measure cost per completed task, useful cache-hit ratio, recovery success rate, duplicate side-effect rate, and turn-level latency. Include the counting pitfalls in each.

**Deliverable:** a test architecture — what runs in unit tests with stubs, what runs against cassettes, what needs live API calls, and what my chaos suite looks like.

---

## Phase 9 — Production architecture

- Storage: what belongs in a durable event store or relational database versus an ephemeral cache. Argue specifically about Redis — where is it genuinely justified for live coordination, and where would using it lose data I cannot afford to lose?
- Event store design: append-only log, snapshots to bound replay cost, retention and compaction. How large does an agent session's history get in practice, and when do snapshots become necessary?
- Worker architecture: how agent sessions are assigned to workers, what happens on worker death, and how leases and fencing prevent double-execution.
- Backpressure: what happens when demand exceeds provider capacity — queue, shed, degrade to a cheaper model, or block? What is the right policy for agent workloads specifically?
- Observability: the OpenTelemetry semantic conventions for GenAI, what a useful trace of an agent turn looks like, and how to correlate a trace with a journal entry and a cost-ledger row.
- **Control-plane failure behavior.** My architecture deliberately puts the control plane off the request path. Study how real control planes do this — the Envoy/xDS model of config distribution, and what "fail static" means. What must my data plane keep doing when my control plane is completely down?
- Secrets management for provider keys at rest and in transit, including rotation.

**Deliverable:** a deployment architecture for a single-developer setup that can grow, with the specific technology choices named and justified — and an explicit list of what I am deliberately *not* building yet.

---

# PART C — STANDING FOLLOW-UPS

Useful at any point.

- **"Steelman the case that I should not build this at all."** Who has already solved this, what would I use instead, and what is the honest argument that my differentiation is too thin? Give me the strongest version.
- **"What did you get wrong?"** Re-examine your last deliverable specifically for claims you marked VERIFIED that were actually inferred, and for anything based on a source older than 12 months that may have changed.
- **"What has changed since your sources?"** Check for releases, deprecations, and pricing changes in the last 90 days affecting anything you told me.
- **"Design review."** Here is my implementation of X. Attack it: correctness under crash, cost under load, behavior under provider failure, and what a reviewer would flag.
- **"Teach the prerequisite."** I did not follow the explanation of X. Go back one level and teach the foundation first, then rebuild the explanation.
