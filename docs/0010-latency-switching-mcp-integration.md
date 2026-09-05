---
Number:        0010
Title:         Latency, Model Switching, and MCP/Plugin Integration
Type:          RESEARCH
Status:        ACCEPTED (frozen)
Created:       2026-09-05
Supersedes:    —
Superseded-by: —
Depends-on:    0006, 0008
Researched-by: Claude Opus 5 (web research, primary sources)
---

# 0010 — Latency, Model Switching, and MCP/Plugin Integration

Requested features: reduce latency, seamless switching between models/providers,
integrate MCP and plugins from multiple sources, and approach the feature set of
Claude / Claude Code with ChatGPT-style shortcuts.

---

## 1. Executive answer

**Four asks, three different answers.**

**Latency is not a new feature — it is the feature `0008` §7 already describes,
and the research forces a correction downward.** Anthropic documents up to 85%
latency reduction from prompt caching, but the only independent measurement of
caching *in agentic settings* (Lumer et al., Jan 2026, 500+ sessions) finds
time-to-first-token improvements of **13–31%**, not 85% — and notes that naive
full-context caching sometimes *increased* latency. The cost-model assumption in
`0008` §7 was too optimistic and must be rebuilt before cache intelligence is
prioritized.

**The largest latency lever is elsewhere, and the effect ledger unlocks it.**
In agent loops, LLM generation reaches up to 96% of end-to-end latency while tool
execution stays roughly constant. Overlapping the two — speculative tool
execution — is therefore the biggest available win, and it is normally unsafe
because speculatively running a side-effecting tool is precisely what `0008` §6
exists to prevent. But the effect classifier in `0008` §6.3 is exactly the gate
that makes it safe: `PURE_READ` tools may be speculatively executed, and nothing
else may. **The safety layer becomes a performance enabler.** This is the
strongest new idea in this document.

**MCP integration is the one genuinely new subsystem, and it got easier.** The
2026-07-28 MCP revision removed the initialization handshake and session
management entirely — the protocol is now stateless. This **deletes "MCP
connection state" from the hard-to-recover list** in `0002` §14 and `0004`
Phase 3. But MCP tools are remote, third-party, and side-effecting, so every
one of them defaults to `EXTERNAL` under `0008` §6.3. **MCP multiplies the
importance of the effect ledger rather than being orthogonal to it.**

**"Claude Code features" are mostly harness features, not control-plane
features.** Skills, subagents, slash commands, and hooks belong to the agent
harness. Building them here would repeat exactly the mistake `0007` deleted two
components to avoid. One slice is genuinely portable and control-plane shaped:
a **capability broker** that governs which tools and MCP servers a session may
reach, under policy, across harnesses.

---

## 2. Scope discipline

This is a scope-expansion request against a project whose architecture is still
DRAFT and blocked on five questions (`0009`). Recording the boundary explicitly,
per risk R3:

| Ask | Disposition |
|---|---|
| Reduce latency | **Already in scope.** Re-prioritized and corrected, not added. |
| Seamless switching | **Already in scope.** One new failure mode identified (§7.3). |
| MCP / plugin integration | **New — Layer 2.** After the effect ledger, never before. |
| Claude Code / ChatGPT features | **Mostly out of scope.** One portable slice retained. |

Nothing here changes the build sequence in `0008` §14 before step 4.

---

## 3. VERIFIED

**V1. Independent measurement of prompt caching in agentic tasks is far below
vendor claims.** Lumer et al., *"Don't Break the Cache: An Evaluation of Prompt
Caching for Long-Horizon Agentic Tasks"*, arXiv:2601.06007 (v1 9 Jan 2026, v2 31
Jan 2026). Evaluated across OpenAI, Anthropic and Google on DeepResearch Bench,
500+ agent sessions, 10,000-token system prompts, 3–50 tool calls per session.
Findings: **cost reduction 41–80%; time-to-first-token improvement 13–31%.**
Strategic placement of dynamic content (at the end of system prompts, excluding
dynamic tool results) outperformed naive full-context caching, which
"occasionally increased latency." Tier T1 (peer-reviewable preprint). Date:
Jan 2026.

**V2. Vendor-documented caching figures are materially higher.** Anthropic
documents up to **90% cost and 85% latency reduction for long prompts**, with a
reported 79% TTFT reduction on a 100K-token cached prefix. Tier T1 (vendor
docs) — but see `I1`. Date: 2026.

**V3. Generation dominates agent-loop latency.** Tool execution latency is
essentially constant with model scale, while tool-calling *generation* latency
grows with model scale, "reaching up to 96% of the end-to-end latency."
Source: agent-speculation literature, arXiv:2603.18897. Tier T1. Date: 2026.

**V4. Parallel tool calling has a hard ceiling.** Empirically "only 15–25% of
tool calls in GAIA and SWE-bench are parallelizable with their predecessor."
Agent tool calls are generated online, so there is no static graph to prefetch.
Source: arXiv:2603.18897. Tier T1. Date: 2026.

**V5. Speculative tool execution is an active, working research area.** Systems
include PASTE (LLM–Tool co-scheduler), SpecBox (Markov-transition prefetch
daemon; control-plane telemetry in tens of microseconds), and SPORK
(self-speculative forking, no separate predictor required). Sources:
arXiv:2607.03333, arXiv:2607.23933, arXiv:2603.18897, arXiv:2605.13360.
Tier T1. Date: 2026.

**V6. MCP is now a stateless protocol.** The 2026-07-28 revision (RC 21 May
2026, final 28 Jul 2026) is "the largest revision of the protocol since launch."
It removes the initialization handshake and session management: "any MCP request
can land on any server instance, and the sticky routing and shared session
stores that horizontal deployments needed before are no longer required."
Tier T1 (official MCP blog / spec). Date: Jul 2026.

**V7. MCP transport and routing metadata changed.** Streamable HTTP now requires
`Mcp-Method` and `Mcp-Name` headers so "load balancers, gateways, and
rate-limiters can route on the operation without inspecting the body." Tier T1.
Date: Jul 2026.

**V8. MCP authorization hardened; sampling deprecated.** Six SEPs strengthen
OAuth 2.1 / OpenID Connect alignment — issuer validation per RFC 9207,
application-type declaration at registration, refresh-token guidance. Sampling
is **deprecated** in favour of direct integration with LLM provider APIs. Tool
schemas now support full JSON Schema 2020-12. An official Extensions framework
graduates Tasks and MCP Apps to first-class extensions. Tier T1. Date: Jul 2026.

**V9. Two MCP transports, with different credential models.** `stdio` (server as
local subprocess over stdin/stdout) and Streamable HTTP (single endpoint,
optional SSE for server→client). HTTP transports should conform to the
authorization spec; **stdio implementations retrieve credentials from the
environment instead.** Tier T1. Date: 2025-03-26 spec onward.

**V10. An official MCP registry exists.** `registry.modelcontextprotocol.io`,
launched preview Sept 2025, backed by Anthropic, GitHub, PulseMCP and Microsoft.
REST API — `GET /v0/servers?limit=10`. Open source, with a published OpenAPI
spec allowing compatible sub-registries. Tier T1. Date: Sept 2025 → 2026.

**V11. Claude Code's extension model is four primitives plus a packaging unit.**
Skills (`SKILL.md` in `.claude/skills/<name>/`, invoked by name or model
judgement, **running in the same context window**); hooks (fire at lifecycle
events, deterministic, invisible); subagents (isolated workers, one-way
return); MCP servers. **Plugins add no new capability** — they bundle those four
into a named, versioned, installable unit. Marketplaces are a `marketplace.json`
catalogue hostable anywhere. Tier T1 (Claude Code docs) + T2. Date: 2026.

---

## 4. INFERRED

**I1. The `0008` §7 cache cost model is too optimistic and must be rebuilt.**
Evidence: V1 measures 13–31% TTFT improvement in agentic settings against V2's
documented up-to-85%. The gap is explained by V1's own finding — agent contexts
mutate (tool outputs vary, ordering shifts, dynamic content is inserted), which
is precisely `0006:I1`. Inference chain: `0008` §7 justified cache intelligence
partly on switching cost, sized against vendor figures. If the real agentic
range is 13–31% TTFT and 41–80% cost, the *cost* case remains strong but the
*latency* case is much weaker than assumed. Confirm/falsify: run the §6 cost
model in `0005` Phase 6 against measured numbers, not documented ones.

**I2. Effect classification is the missing safety gate for speculative
execution.** Evidence: V3 (generation is up to 96% of latency) makes overlap the
dominant lever; V5 shows working systems; `0008` §6.3 already classifies every
tool by replay safety. Inference chain: speculative execution is unsafe exactly
when a tool has side effects, and the classifier already computes that property
for a different reason. A `PURE_READ` tool may be speculatively executed and
discarded at zero semantic cost; an `EXTERNAL` one may never be. Confirm/falsify:
prototype after `0008` step 2; measure wall-clock improvement on a real loop
where reads dominate.

**I3. MCP's move to statelessness deletes a recovery problem the roadmap
assumed.** Evidence: V6 removes session management and the init handshake;
`0002` §14 and `0004` Phase 3 both list "MCP connections" as non-reconstructible
state. Inference chain: if any request can land on any instance, there is no
per-session MCP state to restore after a crash — only credentials, which are
already environment- or OAuth-derived (V9). Confirm/falsify: check which MCP
version OpenHands' client implements; a pre-2026-07-28 client keeps the old
stateful behavior.

**I4. Every MCP tool is `EXTERNAL` until proven otherwise.** Evidence: MCP tools
are remote, third-party, and opaque; `0008` §6.3 defaults unclassified tools to
`EXTERNAL`. Inference chain: a control plane cannot inspect a third-party
server's side effects, so the safe default dominates — which means **enabling
MCP broadly makes most tool calls fall on the ledger's hard path.** This is a
real cost of the feature and an argument for explicit per-server classification.

---

## 5. UNKNOWN

**U1. Which MCP spec revision does the OpenHands SDK implement?** Determines
whether `I3` applies. Resolve by reading the SDK's MCP client and its pinned
protocol version string.

**U2. Does any provider expose a cache-state query API?** All current affinity
schemes (LiteLLM's and ours) *infer* cache residency rather than observing it.
If a provider exposes hit/residency directly, `0008` §7 simplifies considerably.
Resolve in `0005` Phase 6.

**U3. What is the real read/write ratio of tool calls in a coding agent?** `I2`'s
value depends entirely on it — speculative execution pays off only if
`PURE_READ` calls dominate. Resolve by instrumenting a real OpenHands session
and counting by effect class. Cheap, and it should be measured before any
speculation work.

**U4. Does the MCP registry expose enough metadata for policy decisions?**
Capability gating (§8.3) needs declared scopes, auth model, and side-effect
hints. Resolve by reading the registry OpenAPI spec.

---

## 6. Feature 1 — Latency

### 6.1 Where the latency actually goes

The instinct is to optimize tool execution. The measurement says otherwise:
**generation is up to 96% of end-to-end latency** (V3) and tool execution is
roughly constant. Two consequences:

- Optimizing tool execution is near-worthless on its own.
- The control plane's own hot-path cost — a local SQLite read at Seam C — is
  irrelevant against a multi-second generation. **`0008`'s in-band kernel is
  latency-safe by construction.** This was an open worry; it is now closed.

### 6.2 Lever table

| Lever | Expected effect | Evidence | Verdict |
|---|---|---|---|
| Prompt-cache affinity | 13–31% TTFT, 41–80% cost | V1 | Already `0008` §7 — **downgrade latency claim** |
| Cache-aware context layout | Recovers the gap between naive and strategic caching | V1 | **BUILD** — cheap, and pairs with §7 |
| Model tiering per sub-task | Large; generation scales with model size | V3 | **BUILD** — highest ratio of gain to effort |
| Speculative tool execution | Overlaps the 96% with the constant | V3, V5, I2 | **BUILD — Layer 2**, gated on effect class |
| Parallel tool calls | Ceiling of 15–25% of calls | V4 | **SKIP** — harness-owned, low ceiling |
| Streaming | Already handled | — | SKIP |

### 6.3 The correction to `0008` §7

`0008` §7 sequenced cache intelligence on a cost-and-latency argument sized
against vendor figures. V1 says the agentic latency benefit is roughly a third
of that. **The cost case survives; the latency case does not.** Cache
intelligence stays at build step 6, and the §14 justification should be rewritten
to lead with cost. A new cost model is required (`0005` Phase 6).

There is a second, cheaper finding hidden in V1: *strategic placement of dynamic
content beat naive full-context caching.* Putting volatile content at the end of
the system prompt and keeping dynamic tool results out of the cached prefix is a
**configuration change, not a build** — and it may capture much of the available
benefit before any cache-intelligence code exists. Test it first.

### 6.4 The synthesis: safety unlocks speed

Speculative tool execution is the biggest lever available (§6.2) and is normally
gated on a hard question — *is it safe to run this tool before we are sure we
want to?*

`0008` §6.3 already answers that question for a different reason. The effect
classifier is a total function over tools, and its `PURE_READ` class is exactly
the set that is safe to execute speculatively and discard.

```
Effect class      Replay-safe?    Speculation-safe?
PURE_READ              ✓                 ✓
IDEMPOTENT_WRITE       ✓                 ✗   (a discarded write still landed)
NON_IDEMPOTENT_WRITE   ✗                 ✗
EXTERNAL               ✗                 ✗
DESTRUCTIVE            ✗                 ✗
```

Note that speculation is *strictly stricter* than replay safety:
`IDEMPOTENT_WRITE` is safe to repeat but not safe to perform speculatively,
because a speculative write that is then discarded has still mutated the world.
The classifier supports both policies; the thresholds differ.

This reframes the effect ledger. It is not only a correctness tax — it is the
precondition for the project's largest latency win. Worth stating in `0008`.

**Value depends entirely on U3.** If a coding agent's calls are 80% reads, this
is significant. If 30%, it is not worth building. Measure before committing.

---

## 7. Feature 2 — Seamless switching

### 7.1 Four cases, not one

| Case | Difficulty | What actually breaks |
|---|---|---|
| Same model, different account | Trivial | Cache affinity only (`0006:V6`) |
| Same model, different provider | Easy | Cache; minor param/dialect drift |
| Different model, same family | Moderate | Context limit, cache reset, tokenizer |
| Different model, different family | Hard | Tool dialect, plan drift (`0006:I3`) |

Cases 1 and 2 are already served by the data plane. Case 4 is `0006:I3` and
unaddressed anywhere — genuinely greenfield, and genuinely low priority.

### 7.2 What "seamless" actually requires

Because chat completions are stateless (`0003:F2`), switching *between* turns is
close to free. The control plane's contribution is not the switch — it is
choosing *when* to switch, using the cost ledger and cache affinity to avoid
paying a cache miss unnecessarily.

### 7.3 The new hazard: mid-turn switching

Not previously recorded anywhere in this repo.

An assistant message containing unresolved `tool_call`s establishes a contract:
the next message must contain matching `tool_result`s keyed by `tool_call_id`.
If the endpoint changes **between the tool call and the tool result**:

- Different model families use different tool-call dialects and different id
  formats. A `tool_call_id` minted by model A may be rejected as malformed or
  unmatched by model B.
- Some providers validate that every `tool_use` block has a matching
  `tool_result`. A mismatch is a 400, not a graceful degradation.
- `0008` §6.2 keys the entire effect ledger on `tool_call_id`. **If a switch
  changes id semantics mid-turn, ledger lookups miss and a committed effect
  becomes invisible — re-executing it.**

That last point is the dangerous one: a mid-turn provider switch can defeat the
very mechanism built to prevent double execution.

**Design rule, proposed for `0008`:**

> **The turn is the atomic unit of routing.** An endpoint may change between
> turns and never within one. A turn with unresolved tool calls must complete
> against the endpoint that opened it, or be abandoned and replanned as a whole.

This is cheap to enforce at Seam A (the request hook knows whether the outgoing
message list ends with unresolved tool calls) and closes a real correctness hole.
It also interacts with `0009` Q2 — if `tool_call_id` is not stable across resume,
it is very unlikely to be stable across providers.

---

## 8. Feature 3 — MCP and plugin integration

### 8.1 What the stateless revision changes

V6 is a substantial simplification for this project. `0002` §14 and `0004`
Phase 3 both list MCP connection state among the things that cannot be rebuilt
by replaying a log. Under the 2026-07-28 protocol there is no session to rebuild:
any request may land on any instance, and credentials come from the environment
(stdio) or OAuth (HTTP) rather than from session state.

**Proposed deletion:** remove "MCP connections" from the non-reconstructible
state list, conditional on `U1`.

### 8.2 What it makes worse

MCP tools are remote, third-party, and opaque. Under `0008` §6.3 an unclassified
tool defaults to `EXTERNAL` — never re-executed on an ambiguous `INTENT`,
reconciled or blocked. So **enabling MCP broadly pushes most tool calls onto the
ledger's hard path** (`I4`), and simultaneously disqualifies them from
speculative execution (§6.4).

MCP therefore raises the value of per-server effect classification sharply. A
filesystem MCP server's `read_file` is `PURE_READ` and should be declared so; a
payments server's `create_charge` is `EXTERNAL` and must be. That declaration is
control-plane data, and it belongs in the capability matrix (`0008` §9).

### 8.3 The Capability Broker — the one new component

Multi-source MCP integration needs something between the harness and a set of
servers of varying provenance. Responsibilities:

| Responsibility | Why the control plane |
|---|---|
| Server registry & discovery | Federate the official registry (V10) with private sources |
| Per-server effect classification | Feeds `0008` §6.3; nothing else has this data |
| Capability gating | Which sessions may reach which servers, under policy |
| Credential brokerage | stdio env vs OAuth 2.1 (V9) differ per transport |
| Audit | Which server was reached, by which session, at what cost |
| Provenance & pinning | Third-party servers are a supply-chain surface |

Two properties make this control-plane work rather than harness work: it is
**policy over a fleet**, and it is **the same policy across harnesses**.

**Security note.** A third-party MCP server returns content into the agent's
context. That content is data, never instruction — and a compromised or hostile
server is a prompt-injection vector with tool access behind it. The broker's
gating and audit functions are the mitigation, and this should be treated as a
first-class requirement rather than a later hardening pass. Pin server versions;
default-deny unknown servers.

### 8.4 Sequencing

**Layer 2. After `0008` build step 3, never before.** MCP amplifies the effect
problem (§8.2); shipping broad MCP access before the ledger handles `EXTERNAL`
effects correctly would be building the hazard before the guard.

---

## 9. Feature 4 — "Claude Code / ChatGPT features"

### 9.1 The boundary

V11 decomposes Claude Code into skills, hooks, subagents, MCP servers, and
plugins as the packaging unit. Mapping each against this project:

| Primitive | Belongs to | Verdict |
|---|---|---|
| Skills (`SKILL.md`, same context window) | Harness | **SKIP** |
| Slash commands / shortcuts | Harness UI | **SKIP** |
| Subagents | Harness | **SKIP** — and `0004` defers multi-agent entirely |
| Hooks (lifecycle interception) | Harness | **SKIP** as a feature; **note the parallel** — Seam C is a hook |
| MCP servers | Shared | §8 |
| Plugins / marketplaces (packaging + distribution) | **Shared** | **Partial BUILD** — see §9.2 |

Most of this ask is out of scope, and saying so is the point. `0007` deleted the
context/memory layer for exactly this reason: the harness already does it better,
and duplicating it is the failure mode this project was reframed to avoid.

Note also that OpenHands has its own equivalents (microagents, repo instructions,
condensers). Building a second set inside the control plane would give you two
competing systems and no clear owner.

### 9.2 The portable slice

One thing in V11 *is* control-plane shaped. Plugins "add no new capability" —
they package and distribute. Packaging is harness-specific; **policy over what
may be installed and reached is not.**

So: no skill runtime, no subagent framework, no command palette. Instead the
capability broker (§8.3) extends to cover plugin sources — federating
marketplaces, pinning versions, enforcing allow-lists, and recording provenance.
That is one component serving both asks, and it survives a change of harness.

---

## 10. Revised component map

| Component | Status after this document |
|---|---|
| Effect Gate / Ledger | Unchanged — and now also the speculation gate (§6.4) |
| Request Hook | **+ turn-atomic routing rule** (§7.3) |
| Cache Intelligence | Unchanged in position; **latency justification weakened** (§6.3) |
| Capability Matrix | **Extended** — per-MCP-server effect classes, speculation eligibility |
| Capability Broker | **NEW — Layer 2** (§8.3) |
| Model tiering | **NEW — folds into the policy compiler**, high value (§6.2) |
| Speculative execution | **NEW — Layer 2**, gated on U3 (§6.4) |
| Skills / subagents / commands | **Explicitly out of scope** (§9.1) |

---

## 11. Impact on `0008`

Changes to fold in when `0008` is next revised:

1. **§7** — rewrite the cache justification to lead with cost, not latency (I1).
2. **§6.3** — add a speculation-eligibility column to the effect class table;
   record that speculation is strictly stricter than replay safety (§6.4).
3. **§5 / §9** — add the Capability Broker as a Layer 2 control-plane component.
4. **New design rule** — the turn is the atomic unit of routing (§7.3).
5. **§13** — record that the in-band kernel's latency cost is negligible against
   generation (V3), closing an open worry.
6. **§11** — add skills, subagents, and command palettes to the exclusion list.

`0008` stays DRAFT. None of this unblocks `0009` Q1–Q5.

---

## 12. New open questions

To be promoted into `0009`:

| id | Question | Blocks |
|---|---|---|
| Q8 | Which MCP spec revision does the OpenHands SDK implement? (`U1`) | §8.1 deletion |
| Q9 | What is the read/write ratio of tool calls by effect class? (`U3`) | Whether §6.4 is worth building |
| Q10 | Is `tool_call_id` stable across *providers*, not just across resume? | §7.3, and `0008` §6.2 |
| Q11 | Does any provider expose cache residency directly? (`U2`) | `0008` §7 simplification |
| Q12 | Does the MCP registry expose policy-grade metadata? (`U4`) | §8.3 |

**Q9 is the cheapest high-value measurement in the project.** One instrumented
session answers whether speculative execution is worth any effort at all.

---

## 13. Sources

**T1 — papers, official specs, vendor documentation**
- Lumer, Nizar, Jangiti, Frank, Gulati, Phadate, Subbiah — *Don't Break the Cache: An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks*, [arXiv:2601.06007](https://arxiv.org/abs/2601.06007) (v1 Jan 9 2026, v2 Jan 31 2026)
- *Parallelizing Tool Execution and LLM Generation for Low-Latency Agent Serving*, [arXiv:2603.18897](https://arxiv.org/html/2603.18897v3) (2026)
- *SPORK: Self-Speculative Forking to Accelerate Agentic LLM Inference*, [arXiv:2607.03333](https://arxiv.org/html/2607.03333) (2026)
- *SpecBox: Speculative Sandbox Scheduling for Efficient LLM Agent Serving*, [arXiv:2607.23933](https://arxiv.org/html/2607.23933v1) (2026)
- *Speculative Interaction Agents*, [arXiv:2605.13360](https://arxiv.org/pdf/2605.13360) (2026)
- [The 2026-07-28 MCP Specification Release Candidate](https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/) — MCP Blog (May 21 2026)
- [MCP Transports specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)
- [MCP Authorization specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-03-26/basic/authorization.mdx)
- [Official MCP Registry](https://registry.modelcontextprotocol.io/) and [registry docs](https://modelcontextprotocol.io/registry/about); [modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry)
- [Introducing the MCP Registry](https://blog.modelcontextprotocol.io/posts/2025-09-08-mcp-registry-preview/) (Sept 8 2025)
- [Prompt caching — Claude Platform Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Extend Claude Code — Claude Code Docs](https://code.claude.com/docs/en/features-overview)

**T2 — engineering blogs, practitioner analysis**
- [Is that allowed? Authentication and authorization in MCP](https://stackoverflow.blog/2026/01/21/is-that-allowed-authentication-and-authorization-in-model-context-protocol/) — Stack Overflow Blog (Jan 21 2026)
- [MCP Specification Version Timeline](https://hidekazu-konishi.com/entry/mcp_specification_version_timeline.html)
- [Claude Code Plugins Complete Guide](https://hidekazu-konishi.com/entry/claude_code_plugins_complete_guide.html)
- [The State of MCP Registries](https://safedep.io/the-state-of-mcp-registries/) — supply-chain perspective
- [Prompt Caching with OpenAI, Anthropic and Google Models](https://www.prompthub.us/blog/prompt-caching-with-openai-anthropic-and-google-models) — PromptHub

**T3 — context only, never sole basis**
- [stdio vs Streamable HTTP](https://kirkryan.co.uk/stdio-vs-streamable-http-choosing-the-right-mcp-transport/); [Claude Code Skills, Subagents, Hooks and Plugins](https://boringbot.substack.com/p/claude-code-skills-subagents-hooks); [MCP Cheat Sheet](https://www.webfuse.com/mcp-cheat-sheet)

---

*Version caveat: MCP moved from stateful to stateless within a single revision
(V6). Any claim here about MCP behavior is valid only against the revision the
OpenHands client actually implements — see `U1`. Per `0009` R1, re-verify before
building.*
