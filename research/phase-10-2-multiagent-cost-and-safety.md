---
Number:        (unallocated — promote to docs/0038 on acceptance)
Title:         Multi-Agent Execution, Costed and Safety-Audited Before Design
Type:          RESEARCH
Status:        ACCEPTED (frozen)
Created:       2026-09-20
Supersedes:    —
Superseded-by: —
Depends-on:    0006, 0010, 0012, 0013, 0017, 0019, 0037
Researched-by: Claude Opus 5 (primary sources + falsification experiments on this repo)
Phase:         10.2 (`docs/0037`)
Code-as-of:    6bb26d011244b933735539107b0c85dc60ee9f2f (2026-09-15)
SDK-as-of:     openhands-sdk 1.45.0 (the only installed `openhands` distribution)
---

# Phase 10.2 — Multi-Agent, Costed Before It Is Designed

Permalink base for every `file::symbol` citation below:
`https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/`

Thirteen experiments were run against this repository and its `.venv` to
produce this document. They are reproducible, cost nothing, need no API key,
and are listed as E1–E13 at the end of §8.

**One of them (E13) found a live defect in the shipped single-agent path.** It
is written up as V30 / I6 and it is the first item in §7. It is not a
multi-agent problem and its fix does not depend on the multi-agent verdict.

---

## 1. Executive answer

**The budget verdict is that multi-agent does not fit, and the reason is not
the one anyone expected: the pool in `proxy/proxy_config.yaml` has no usable
token budget to multiply.** Of the 42 deployments, the 12 Groq ones cannot
serve `agentctl run` past its first turn at all — Groq's free tier meters
`prompt + max_tokens` against an 8,000 tokens-per-minute ceiling, and this
runner's 3,593-token fixed prefix plus its declared `max_output_tokens=4096`
leaves **311 tokens** of conversation before a 413 (§6.4); the 12 Mistral
deployments have no verifiable published limit; so the entire practical daily
allowance is **OpenRouter's 300 requests/day** (6 accounts × 50, account-wide
across every `:free` model). A measured single-agent multi-file task on this
codebase costs 14 requests and ~335k tokens; a supervisor plus three workers
costs 32 requests and ~519k tokens even when the decomposition goes perfectly
(×2.29 requests, ×1.55 tokens), and at the rate the literature actually
measures for coding — Anthropic's own 3.75×, or the 10× that "The Illusion of
Multi-Agent Advantage" measures on SWE-Bench Lite — **one task consumes 17% to
47% of the entire day's request budget**, and at the 10× rate its 3.35M tokens
exceed the whole nominal Groq daily pool in a single task.

**The safety verdict is worse than the budget verdict, and it would stand even
if the budget were infinite.** Fencing does not do what the README implies: it
is a *record-level* guard, not an *agent-level* one, and a superseded holder
that is still alive executes new effects with undiminished authority (E10,
§5.2). The lease is keyed on `conversation_id`, so two agents in one workspace
never contend for it (E1). `find_by_intent` — the mechanism that catches a
repeated effect under a new id — is scoped to one conversation, so the single
most common documented multi-agent failure mode (MAST FM-1.3, *step
repetition*, 15.7% of 1,642 traces) produces an **undetected duplicate
effect** (E2). The git probe returns `LANDED` for a commit that never ran,
because another agent moved HEAD (E6) — a silent dropped commit in the exact
component the project exists to protect. And `SubstitutionHandoff` matches by
a content fingerprint with no agent in the key, so worker B claims worker A's
recorded observation and A then re-executes (E7).

**And the audit turned up a live single-agent bug that has nothing to do with
multi-agent at all.** `openhands-sdk` emits every `ActionEvent` in an assistant
message — and therefore runs every gate decision and every world-fingerprint
`capture()` — *before* it executes any of them
([`response_dispatch.py:160-184`](https://github.com/OpenHands/software-agent-sdk)).
So when one assistant message contains two HEAD-moving tool calls, both capture
the same pre-commit HEAD; the first commits; a crash before the second executes
makes the second's probe read `LANDED`, and the gate answers `SUBSTITUTE`. **The
second commit is silently dropped and the ledger records it as `COMMITTED`.**
Reproduced end to end at `tool_concurrency_limit=1`, one agent, one
conversation (E13). The nine-point chaos suite cannot see it because
`experiments/0004-nine-point/worker.py` issues exactly one effect per run. This
is `at-least-once` failing, in shipped code, today.

**Verdict: SKIP for multi-agent, FIX for the batch bug.** `docs/0013` §7 was
right to defer this and the evidence overturns nothing in it. Two things are
worth salvaging: **per-worker `git worktree` isolation restores the git probe to
correct verdicts** (E8) and survives 120 concurrent commits from three worktrees
on Windows with zero failures (E9); and the SDK's subagent *format* is real
(`AgentDefinition`, `model: inherit`, tool allowlists) while its subagent
*runtime* — `TaskManager` — **is not installed and is not a declared
dependency** (V26), so nothing can be adopted for free.

---

## 2. VERIFIED

Each claim below was established by reading source or by running an experiment
named in §8 (E1–E13). Source tier and date are given for external claims.

### 2.1 The pool

**V1. The real pool is 18 OpenRouter + 12 Mistral + 12 Groq deployments across
18 accounts — and contains no Gemini and no Cerebras.**
`proxy/proxy_config.yaml` (generated, header says "42 deployment(s) across 18
account(s)"): 6 OpenRouter accounts × 3 `:free` models, 6 Mistral × 2, 6 Groq
× 2. `agentctl/control/providers.py::PROVIDERS` supports Gemini and Cerebras,
but neither key was set when the file was generated, so they contribute zero
deployments today. **The task brief's premise that "Gemini, Cerebras have
their own [caps]" is not true of the current pool.** T1, this repo,
2026-09-20.

**V2. OpenRouter's free-tier cap is 50 requests/day, account-wide across every
`:free` model, rising to 1,000/day only after $10 of lifetime credit
purchase; plus 20 RPM.** T1 —
`https://openrouter.ai/docs/api-reference/limits`, fetched 2026-09-20. This
matches what `providers.py` already records in its `note`: *"One account-wide
cap covers every `:free` model."* It is a **request** cap, not a token cap, so
context size is free and turn count is everything.

**V3. Groq's free tier for `openai/gpt-oss-20b` and `openai/gpt-oss-120b` is
30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD, enforced per organization.**
T1 — `https://console.groq.com/docs/rate-limits`, fetched 2026-09-20. The same
page states rate limits "apply at the organization level, not individual
users" and that "cached tokens do not count towards your rate limits."

**V4. Groq's TPM ceiling is charged against `prompt + max_tokens`, not against
tokens actually generated, and the rejection is a 413.** T3 (multiple
independent issue trackers and a DEV article, 2026) corroborated by the T1
rate-limits page's framing of TPM as a budget. Consequence, computed in §6.4:
with `max_output_tokens=4096`
([`runtime/runner.py::run`](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/runtime/runner.py#L189))
and a 3,593-token fixed prefix, **311 tokens of conversation remain**. This is
labelled VERIFIED for the arithmetic and INFERRED for the live behaviour (I1).

**V5. The measured fixed per-request prefix of `agentctl run` is 3,593
tokens**: 3,208 for `Agent.static_system_message` and 385 for the three
OpenAI tool schemas (`execute_bash`, `read_file`, `write_file`), cl100k
encoding, openhands-sdk 1.45.0. Measured by instantiating the exact agent the
runner builds. T1, this repo, 2026-09-20.

**V6. There is no cache affinity anywhere in this project.**
`grep -rn "optional_pre_call_checks\|prompt_caching\|deployment_affinity"` over
`agentctl/` and `proxy/` returns nothing. `router_settings` is
`simple-shuffle` with no weights, so consecutive turns land on the same
deployment with probability 1/42 = 2.4%. `docs/0025` §5's measured 96.34% cache
hit and `docs/0036`'s 94.93% were both obtained **pinned to a single
deployment**, not through the pool. T1, this repo.

### 2.2 The ledger and the gate under concurrency

**V7. The writer lease is keyed on `conversation_id`, so two agents in one
workspace never contend for it (E1).** Two `LedgerStore` instances over the
same database file, holders `agent-A` and `agent-B`, acquired
`conv-supervisor` and `conv-worker-1` simultaneously, both receiving fence 1.
[`ledger/store.py::LedgerStore.acquire`](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/kernel/ledger/store.py#L60)
and `schema.sql` — `CREATE TABLE lease (conversation_id TEXT PRIMARY KEY, …)`,
whose own comment reads *"Fencing: one live writer per conversation."* That
comment is accurate; the guarantee people read into it ("one live writer per
workspace") is not one the code makes.

**V8. Fencing is record-level, not agent-level: a superseded holder that is
still alive continues to execute new effects with full authority (E10).**
Agent B stole agent A's lease (fence 2), executed and committed. Agent A then
called `gate.guard()` on a *new* `tool_call_id` and received **EXECUTE**, and
a record was written carrying the stale fence token 1.
[`ledger/store.py::LedgerStore.write_intent`](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/kernel/ledger/store.py#L189)
only calls `_assert_fence` when `prev is not None`. A first sighting is
unfenced by construction. This is correct and sufficient for the case fencing
was designed for — crash-resume, where the superseded holder is *dead* — and
it is a hole the moment both holders are alive.

**V9. `_assert_fence` is a no-op whenever the in-memory fence map has no entry
(store.py:181–183).** `self._fences` is per-process and per-instance. A
superseded process that restarts has an empty map, so `ours is None` and the
guard returns early. T1, this repo.

**V10. `find_by_intent` — the duplicate-effect catcher — is scoped to one
conversation, so two workers issuing the identical call are not deduplicated
(E2).** Two `ToolCall`s with identical `tool_name` and `args` produce identical
`intent_hash` values, as designed. Looking the hash up in the originating
conversation finds the `COMMITTED` twin; looking it up under a second
conversation returns `None`.
[`ledger/store.py::LedgerStore.find_by_intent`](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/kernel/ledger/store.py#L125)
— `WHERE conversation_id=? AND intent_hash=?`. This is the mechanism
`docs/0023` §4 added to survive a model minting a different `tool_call_id`; it
does not survive a *different agent* minting one.

**V11. `SubstitutionHandoff` matches by a content fingerprint with no agent or
conversation in the key, so one agent claims another's substitution (E7).**
Worker A's Seam B offered a recorded observation for `file_write(path=…)`;
worker B issued the identical call and its `claim()` returned **A's
observation**, after which A's own `claim()` returned `None` and A fell
through to execute.
[`adapters/openhands/handoff.py::SubstitutionHandoff.claim`](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/adapters/openhands/handoff.py#L56)
— the fingerprint is `sha256({"t": tool_name, "a": args})`, nothing more. Both
halves are wrong: B skips an effect it needed, A repeats one it already did.

**V12. Seam C installs into a process-global registry that the last caller
wins.** [`adapters/openhands/seam_c.py::install`](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/adapters/openhands/seam_c.py#L181)
calls `register_tool(name, …)`; the SDK's
`openhands/sdk/tool/registry.py::register_tool` holds a module-global `_REG`
and, on a duplicate name, only logs `"Duplicate tool name registerd"` before
overwriting (`# TODO: throw exception when registering duplicate name tools`).
Two `protect()` calls in one process therefore leave every agent sharing the
*last* agent's handoff — which is the mechanism that makes V11 reachable in
practice. T1, openhands-sdk 1.45.0 as vendored in `.venv`.

**V13. `LedgerStore` cannot be used from a second thread (E5).** `ProgrammingError:
SQLite objects created in a thread can only be used in that same thread.`
`sqlite3.connect` is called without `check_same_thread=False`
([store.py:45](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/kernel/ledger/store.py#L45)).
The class docstring says so — *"Not thread-safe by design"* — and this is the
enforcement.

**V14. Two *processes* writing the same ledger concurrently is fine at the
SQLite layer (E4).** 240 fsynced write-intent/commit pairs from two threads
with separate connections completed in 0.55 s with zero errors.
`busy_timeout` is 5,000 ms (Python's `sqlite3.connect` default `timeout=5.0`),
`journal_mode=wal`, `synchronous=2` (FULL). **The durability layer is not the
problem. The semantics above it are.**

### 2.3 The git probe

**V15. The git probe returns `LANDED` for an effect that never happened, when
another agent commits to the same repository during the window (E6).** Agent A
captured HEAD and tree; agent A's commit never ran; agent B committed its own
work; A's probe returned `LANDED`. The gate then answers `SUBSTITUTE` and A's
commit is **silently dropped**, with the ledger recording it as `COMMITTED`.
[`reconcile/git.py::GitProbe.probe`](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/kernel/reconcile/git.py#L90)
— `if head_now != pre.get("head"): return LANDED`, whose own comment says
*"With a single writer in the workspace, that was our commit."* The assumption
is documented in
[`reconcile/base.py`](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/kernel/reconcile/base.py#L22):
*"the agent's workspace has a single writer."* The code is honest; the feature
violates it.

**V16. The second failure mode is a spurious BLOCK flood (E6, variant).** When
another agent merely dirties the working tree without committing, HEAD is
unchanged and the tree hash differs, so the probe returns `INCONCLUSIVE` and
the gate fails closed. Correct, and unusable: every ambiguous effect in a
concurrent workspace needs `agentctl resolve`, which destroys the autonomy
multi-agent was for.

**V17. Per-worker `git worktree` isolation restores correct probe verdicts
(E8).** With workers A and B in separate worktrees on separate branches
sharing one `.git`: B committing elsewhere → A's probe says `DID_NOT_LAND`
(correct); A committing → `LANDED` (correct). `rev-parse --show-toplevel`
resolves to the worktree, so the toplevel guard from `docs/0019` also works
and now *distinguishes* workers. The worktree's `.git` is a **file**, not a
symlink, so this needs no Developer Mode on Windows.

**V18. Concurrent git commits across worktrees are safe (E9).** 3 worktrees ×
40 commits each, run concurrently on Windows against one shared `.git`: **0
failures**, each worktree ending at 41 commits on its own branch. Git's
per-branch `refs/heads/<name>.lock` and content-addressed object store handle
it.

### 2.4 The evidence for the benefit

**V19. Anthropic — the vendor with the strongest incentive to sell multi-agent
— measures it at ~15× chat tokens against ~4× for a single agent, and says
plainly it does not suit coding.** Exact sentences: *"multi-agent systems use
about 15× more tokens than chats"*; *"agents typically use about 4× more
tokens than chat interactions"*; *"most coding tasks involve fewer truly
parallelizable tasks than research, and LLM agents are not yet great at
coordinating and delegating to other agents in real time"*; *"some domains
that require all agents to share the same context or involve many dependencies
between agents are not a good fit for multi-agent systems today."* T2,
`anthropic.com/engineering/multi-agent-research-system`, **published 13 June
2025 — older than 12 months, flagged.** 15/4 = **3.75× a single agent**.

**V20. The one controlled, budget-matched evaluation covering SWE-Bench Lite
finds automatic multi-agent systems *lose* to a single agent while costing up
to 10×.** *"automatic MAS consistently underperform CoT-SC despite being up to
10x more expensive"*; *"CoT-SC consistently outperforms automated MAS
frameworks, frequently achieving higher accuracy at less than 10% of the
computational cost."* T1 (arXiv preprint, not peer-reviewed) —
*The Illusion of Multi-Agent Advantage*, Jwalapuram et al., Salesforce
Research / HKUST-GZ / UBC / NTU, arXiv:2606.13003v2, **13 June 2026**.

**V21. The same paper finds a competency floor that this project's pool sits
below.** *"No Gains for Mid-Tier Models: MAS fails to provide consistent
improvements for models like GPT-4o or GPT-OSS"*; *"a competency floor for MAS:
architectural complexity may only yield benefits when the underlying backbone
already possesses the high inherent reasoning capabilities necessary to
navigate complex coordination."* And, decisively for this pool: *"GPT-OSS-120B
was excluded from SWE-Bench Lite due to consistent formatting failures in code
patches."* **`openai/gpt-oss-120b` is 6 of the 42 deployments in
`proxy_config.yaml`.** T1 preprint, 13 June 2026.

**V22. A second controlled study with normalized token accounting reaches the
same conclusion.** *"at most one of six tested MAS exceeds the matched
single-agent anchor… the remaining five trail by 2.56–11.29 points and occupy
more expensive accuracy–cost trade-offs."* Measured instance-level tokens:
single agent 27,435 at 74.12% average accuracy; EvoAgent 34,154 (+24.5%) at
75.56% (+1.44, *within* the paper's one-run uncertainty guidance); ChatEval
105,838 (+286%) at 68.84%. T1 preprint — *Do More Agents Help?*, Fu et al.,
arXiv:2606.05670v1, **4 June 2026**.

**V23. The only direct study of concurrent multi-agent *code generation*
measures a 13.1% raw slowdown, 82–189% code-volume inflation, a 7.7% code-
quality regression, and a 5–10% semantic-conflict rate that survives perfect
character-level convergence.** 600 trials, 6 tasks × 50 runs × 2 modes, Claude
Sonnet 4.5, up to 5 agents. Per-task range −21.1% speedup to +39.4% slowdown.
Speedup for suitable tasks *peaks at N=3* and degrades to break-even by N≈20;
unsuitable tasks *"degrade immediately."* T1 preprint — *CodeCRDT*,
arXiv:2510.18893v1, **18 October 2025**. Scope limits stated by the authors:
TypeScript/React only, tasks under 100 LOC, *"no >10k LOC codebases."*

**V24. The canonical failure taxonomy puts *step repetition* — duplicated work
— at 15.7% of 1,642 real multi-agent traces, the single most prevalent mode.**
Other modes that bear directly on this codebase: reasoning-action mismatch
13.2%, unaware of termination 12.4%, disobey task specification 11.8%,
incorrect verification 9.1%, no/incomplete verification 8.2%, loss of
conversation history 2.8%. T1 (UC Berkeley; arXiv record shows no venue, so treated as a
high-quality preprint) — *Why Do Multi-Agent LLM Systems Fail?*, Cemri et al., arXiv:2503.13657v3, **26 October
2025**, κ = 0.88 inter-annotator agreement, 14 modes in 3 categories.

**V25. Cognition, shipping a production coding agent, published the opposite
recommendation to the one the owner is asking for.** Principle 1: *"Share
context, and share full agent traces, not just individual messages."*
Principle 2: *"Actions carry implicit decisions, and conflicting decisions
carry bad results."* On parallel subagents: *"Subagent 1 and subagent 2 cannot
see what the other was doing"*, so *"their work ends up being inconsistent
with each other."* Recommendation: *"The simplest way to follow the principles
is to just use a single-threaded linear agent."* T2, `cognition.com/blog/
dont-build-multi-agents`, **12 June 2025 — older than 12 months, flagged.**

---

### 2.5 What openhands-sdk 1.45.0 already ships, and what it does not

This subsection exists because the premise "multi-agent is greenfield" is
wrong, and so is the premise that the SDK hands it to you.

**V26. The SDK ships the Claude-Code subagent *format* but not the runtime
that spawns one, and that runtime is not a declared dependency.**
`openhands/sdk/subagent/schema.py::AgentDefinition` accepts exactly the Claude
Code frontmatter fields — `name`, `description`, `model` (including the literal
`"inherit"`), `tools`, `skills`, `max_iteration_per_run`, `max_budget_per_run`,
`hooks`, `mcp_servers`, `permission_mode`, `condenser`. `subagent/registry.py::
agent_definition_to_factory` turns one into a `Callable[[LLM], Agent]`. But
nothing *runs* it: its docstring defers to a `TaskManager` that appears
**only in two docstrings** in the installed tree (`subagent/registry.py:177`,
`observability/laminar.py:428`) and exists in no module. There is no `task` or
delegate tool in `sdk/tool/builtins/` (`finish`, `invoke_skill`, `switch_llm`,
`think`, `vision_inspect`). `pyproject.toml` declares
`openhands = ["openhands-sdk>=1.45.0"]` and the only installed distribution is
`openhands_sdk-1.45.0`. **Adopting SDK subagents means adding a dependency that
is currently outside the 502-test surface.** T1, this repo + `.venv`,
2026-09-20.

**V27. `agentctl`'s three tools do not implement `declared_resources()`, so the
parallel executor falls back to a per-tool-name mutex — which lets `bash` and
`write_file` run concurrently (E11, E12).** `grep declared_resources
agentctl/runtime/tools.py` returns nothing; at runtime all three return the
base class's `DeclaredResources(keys=(), declared=False)`
(`sdk/tool/tool.py:513-521`), and `ParallelToolExecutor._resolve_lock_keys`
maps `declared=False` to `[f"tool:{tool.name}"]`. Measured pairings:

| pair | lock keys | at `tool_concurrency_limit > 1` |
|---|---|---|
| `bash` + `bash` | `tool:bash` vs `tool:bash` | serialized |
| `write_file` + `write_file` | same key | serialized |
| **`bash` + `write_file`** | `tool:bash` vs `tool:write_file` | **concurrent** |
| **`bash` + `read_file`** | different keys | **concurrent** |

So the lock manager the coordinator flagged does *not* protect this project: it
protects same-named tools from each other and permits `execute_bash` (which can
`git commit`) to run in parallel with `write_file` in the same workspace.

**V28. That hazard is latent, not live: `agentctl` never sets
`tool_concurrency_limit`, and `Agent` does not read a profile on direct
construction.** `agent/base.py:293` declares `tool_concurrency_limit: int =
Field(default=1, ge=1, …)` with its own warning that above 1 *"concurrent tools
share the conversation object, filesystem, and working directory, so mutations
to shared state may race."* `Agent.model_post_init` builds
`ParallelToolExecutor(max_workers=self.tool_concurrency_limit)`.
`runtime/runner.py` constructs `Agent(llm=…, tools=…,
include_default_tools=[])` — a direct pydantic construction that touches
neither `profiles/agent_profile.py` nor `settings/model.py`, both of which also
carry the field. **One keyword argument away from live.** T1, this repo.

**V29. The cross-thread SQLite hazard (V13) does *not* fire, because every
ledger write happens on the agent thread.** `_ActionBatch.prepare` dispatches
tools through the thread pool and *collects* their events;
`batch.emit(conversation, on_event)` is then called on the caller's thread
(`agent/agent.py:588`), and Seam B's `__call__` handles both `ActionEvent` and
`ObservationEvent` from there. **A negative finding, and an important one:**
raising `tool_concurrency_limit` would not produce the loud `ProgrammingError`
that would have made the problem obvious. It would produce silent racing
effects instead.

**V30. The batch ordering runs every gate decision and every world-fingerprint
capture before any tool executes — and that produces a false `LANDED` in
single-agent mode (E13).** `response_dispatch.py::_handle_tool_calls` loops
over `message.tool_calls` calling `_get_action_event`, which ends in
`on_event(action_event)` (`agent/agent.py:1341`), and only afterwards calls
`self._execute_actions(conversation, action_events, on_event)`. Measured, with
`tool_concurrency_limit=1`, one agent, one `conversation_id`:

```
  guard(call_1) = EXECUTE    guard(call_2) = EXECUTE
  call_1 captured HEAD 5db483de
  call_2 captured HEAD 5db483de   SAME? True
  executing call_1 -> ok
  *** process dies before call_2 executes ***
  resume verdict for call_2 = SUBSTITUTE   probe said: LANDED
  commits in repo now: 2  ('part 2' never ran)
```

Nothing in `agentctl` or in `LLM` disables parallel tool calls
(`grep parallel_tool_calls agentctl/` returns nothing), so the provider default
— enabled, for OpenAI-compatible endpoints — applies. `docs/0010` §6.2 already
records that 15–25% of calls are parallelizable in practice.

**V31. `max_budget_per_run` — the SDK's per-subagent cost control — is inert on
this pool.** `local_conversation.py:705-712` compares
`conversation_stats.get_combined_metrics().accumulated_cost` against the limit.
`docs/0021` §5 and the README establish that LiteLLM reports `response_cost:
0.0` for an endpoint it cannot price — *not `None`, zero* — and every one of
the 42 deployments is free and unpriced. So `spent` is `0.0` forever and
`spent < max_budget_per_run` is always true. **The one budget guard the
subagent format offers cannot fire on the only endpoints this project uses**,
and it is the same defect `docs/0021` §5 already named and that
`Totals.describe_cost()` already fixed on this side of the boundary. T1, this
repo + `.venv`.

---

## 3. INFERRED

**I1. Groq's 12 deployments are unusable for `agentctl run` beyond turn 1, and
the 2.4M-token Groq daily pool is therefore a phantom.** Chain: V3 gives an
8,000 TPM ceiling per account per model; V4 says the ceiling is charged
against `prompt + max_tokens`; `runner.py` declares
`max_output_tokens=4096`; V5 measures the unavoidable prefix at 3,593. Then
8,000 − 4,096 − 3,593 = **311 tokens** of conversation before a 413, and turn 2
of every measured trajectory in §6.2 already exceeds that. Confidence is high
on the arithmetic, medium on the live behaviour because V4's mechanism is T3.
**Falsify in five minutes:** point `agentctl run` at `groq/openai/gpt-oss-120b`
with a trivial task and watch whether turn 2 returns 413; then set
`max_output_tokens=1024` and see whether the failure moves to turn 3.

**I2. Multi-agent forfeits nothing in *relative* cache terms here, because the
cache is already gone.** Chain: V6 gives 2.4% expected same-deployment
probability through the pool versus the 96.34% measured pinned. Uncached input
for one single-agent task is therefore 309,784 tokens instead of 11,615 — a
**×26.7 penalty that the single agent already pays**. Multi-agent multiplies
the request count on top of that, but does not change the ratio.
**This corrects the framing in `docs/0037` and `docs/0010` §6**: cache
affinity is not a multi-agent problem, it is a *pool* problem that exists
today, and because OpenRouter meters requests rather than tokens it currently
costs nothing on the only provider that works. Fixing it would matter if and
only if Groq or Mistral became usable.

**I3. The two ways of assigning `conversation_id` to a supervisor-plus-workers
topology both fail, in opposite directions.** Chain from V7, V8, V10, V11.
*(a) One conversation_id for all agents:* the second `protect()` raises
`LeaseHeld` and cannot start; with `takeover=True` it starts and the first
agent's next write to an existing record raises `StaleFence`, which
`gate.guard`'s fail-closed wrapper converts to BLOCK — and `_try_block`'s own
`store.block()` call then raises `StaleFence` again and is swallowed, so the
record is **stranded in INTENT and never appears in `agentctl blocked`**.
*(b) One conversation_id per agent (the natural design):* no lease contention
at all (V7), no cross-agent intent dedup (V10), no cross-agent fencing (V8),
and the handoff cross-claims anyway (V11). There is no third option that the
current schema expresses.

**I4. The effect ledger would convert MAST FM-1.3 (step repetition, 15.7%)
from a wasted-tokens problem into a duplicate-effect problem.** Chain: V24
says step repetition is the most common multi-agent failure; V10 says
identical calls in different conversations are not deduplicated; the gate's
first-sighting branch writes INTENT and returns EXECUTE. So the 15.7% case
lands as a second real `git commit` / file append. **This is the project's
headline guarantee — "at most once" — failing on the most likely multi-agent
event.** Falsify with chaos test C3 (§5.5).

**I5. The realistic multi-agent request multiplier for this workload is 2.3×
to 10×, not the 1.55× a clean decomposition suggests.** Chain: §6.3 models a
supervisor and three workers with one reconciliation round, no duplicated
work, and no retries, and gets ×2.29 requests — this is the *best case by
construction*. V19 measures 3.75× on tasks multi-agent suits; V20 measures up
to 10× on SWE-Bench Lite; V23 measures 82–189% output inflation on concurrent
code generation. The honest planning range is **×2.3 (optimistic) to ×3.75
(Anthropic's own, on favourable tasks) to ×10 (measured on coding)**.

**I6. The batch false-`LANDED` (V30) is a live defect in the shipped
single-agent path, and it is the *first* thing to fix regardless of the
multi-agent verdict.** Chain: V30 reproduces it end to end; the reachability
condition is "one assistant message containing two or more HEAD-moving tool
calls", which nothing disables and which `docs/0010` §6.2 measures at 15–25% of
calls; the git probe is the only probe vulnerable, because
`reconcile/filesystem.py` verifies *our bytes* are present rather than
inferring from "something changed" — the module docstring says so in as many
words: *"That is stronger than the git probe, which can only infer from 'HEAD
moved'."* **The fix is small and local:** re-`capture()` at execution time
rather than at gate time for probes whose evidence is positional, or refuse to
select the git probe for a call that is not the first HEAD-mover in its batch.
Confidence high. Falsify with chaos test C10 (§5.5).

**I7. Raising `tool_concurrency_limit` would silently reproduce E6 and E7
inside one agent.** Chain: V27 says `bash` and `write_file` take different
locks; V28 says the executor honours the limit with no other guard; V29 says
the ledger will not complain because writes stay on the agent thread. So a
`git commit` in `bash` and a `write_file` to the same tree execute in two
threads with the gate having already fingerprinted both against the same
pre-state. **The single-writer assumption in `reconcile/base.py` is violated by
a configuration change, not by a feature.** Falsify: chaos test C11 (§5.5).

**I8. `docs/0013` §7's deferral was correct, and nothing found here overturns
it.** Chain: §7 tiered multi-agent as "Layer 3 — speculative, only once
single-agent state is genuinely solid." V8, V10, V11, V15 show single-agent
state is solid *precisely because* it assumes one writer, and that every
correctness mechanism in the kernel encodes that assumption somewhere. The
deferral's stated condition has not been met. `docs/0010` §9.1's SKIP verdict
on subagents is likewise confirmed by V19, V20, V23 and V25 — four
independent sources, two of them from organisations shipping the feature.

---

## 4. UNKNOWN

**U1. Mistral's current free-tier limits.** `providers.py` deliberately records
no rate limits because *"they go stale in weeks"*, and Mistral's own help page
for free-tier limits now 404s. The widely repeated figures (1 req/s, 500k TPM,
~1B tokens/month) are **T3 only**. 12 of the 42 deployments therefore have an
unverifiable budget. *Resolve:* read Admin Console → Limits for one account and
record the number **with the date it was true**, per `docs/0034` and
`docs/0021` §5.

**U2. Whether Groq's TPM rejection is deterministic per request or windowed.**
V4's sources describe it as non-deterministic — the same request can return 200
then 413 because the budget is a shared time window. That changes I1 from
"unusable" to "unreliable", which is a different remediation. *Resolve:* the
five-minute experiment in I1, run 20 times.

**U3. Whether a multi-agent topology would ever be *worth* its cost on this
pool, at any price.** V21's competency floor says architectural complexity pays
only above a capability threshold, and names GPT-OSS as below it. No study
found evaluates a supervisor-worker topology on `ministral-3b`,
`gpt-oss-20b/120b`, `nemotron-3-super` or `deepseek-chat-v3.1`. *Resolve:* not
worth resolving — the experiment costs a week of quota to answer a question
whose prior is already strongly negative.

**U4. ~~Whether `ParallelToolExecutor` is reachable from `agentctl run`~~ —
ANSWERED, and the answer changed the document.** It is **not reachable today**
(V28: the default is 1, and `Agent` is constructed directly rather than from a
profile), it would **not fail loudly** if it were (V29: ledger writes stay on
the agent thread, so no `ProgrammingError`), and it would **not be protected**
by `ResourceLockManager` (V27: `bash` and `write_file` take different locks).
What remains open is only *whether anyone will turn it on* — which §7 item 2
closes by pinning it to 1 explicitly. **The hunt for this question found a
different and worse one: V30, the batch false-`LANDED`, which is live now at
`tool_concurrency_limit=1`.**

**U5. Whether six accounts per provider is within those providers' terms.**
`docs/0013` §1 explicitly corrects `0003:F4` to say that multi-account routing
concerns *"apply only to creating multiple accounts on one provider to get past
that provider's limits."* The current pool is 6 OpenRouter + 6 Mistral + 6 Groq
accounts. **That is the case `docs/0013` said the concerns do apply to**, and
multi-agent increases reliance on it by 2.3×–10×. *Resolve:* read each
provider's acceptable-use terms and record the finding. Out of scope for this
document but it is not out of scope for the project.

**U6. Which pool models actually emit parallel tool calls, and how often.** V30's
bug needs two HEAD-moving calls in one assistant message. `docs/0010` §6.2 cites
a 15–25% parallelizable ceiling, but that is not a measurement of
`nemotron-3-super`, `deepseek-chat-v3.1`, `ministral-3b` or `gpt-oss-*`.
*Resolve:* count `len(message.tool_calls) > 1` over the existing
`--record` cassettes and over one fresh dogfood run. **This sets the frequency
of a bug already proven to exist, not its existence** — the fix in I6 is worth
making either way.

**U7. Whether `openhands-tools`' `TaskManager` persists subagent events into the
parent `EventLog` with `parent_id` lineage, or into a separate conversation.**
This is the question `docs/0006`:76 needs answered to size the journal BUILD,
and it **cannot be answered from the installed tree** — the module is not there
(V26). The two available hints point opposite ways: `observability/laminar.py`
:428 says a subagent runs *"synchronously inside its parent's `task` TOOL
span"*, which suggests parent lineage; but `registry.py`'s factory returns a
bare `Agent` and says nothing about a Conversation, and
`agent_definition_to_factory` gives each subagent **its own condenser with a
distinct `usage_id`** *"else its tokens get deduped"* — which implies separate
metrics accounting and therefore, probably, a separate conversation.
*Resolve:* `pip install openhands-tools` into a scratch venv and read
`TaskManager`; do **not** add it to `pyproject.toml` to find out.

---

## 5. Mechanism — concurrent writers against this lease and fence design

### 5.1 What the design actually guarantees

Three durable facts, then the gap.

1. `lease` is `(conversation_id PRIMARY KEY, holder, fence_token, expires_at)`.
   `acquire` refuses a **live** lease held by a different holder unless
   `takeover=True`, and always returns `prev.fence_token + 1`.
2. `effect_record.fence_token` stores the fence of the writer that created the
   record.
3. `_assert_fence(conversation_id, record_fence)` raises `StaleFence` when
   `record_fence > ours` — that is, when the record was written by a
   *newer* holder than us.

The guarantee that composes out of those three is: **a superseded writer
cannot mutate a record that a newer writer has already touched.** That is
exactly and only what crash-resume needs. `docs/0016` §3's scenario is a
process that hung, had its lease stolen, and then woke up mid-`commit()`; fact
3 rejects it.

### 5.2 The gap, stated precisely

The fence is attached to *records*, not to *the right to act*. Three
consequences, each verified:

- **A first sighting is unfenced.** `write_intent` looks up `prev` and only
  calls `_assert_fence` if `prev is not None`. A superseded-but-alive agent
  calling `guard()` on a fresh `tool_call_id` gets EXECUTE (V8/E10).
- **The fence map is process-local and forgettable.** `self._fences` is a plain
  dict on the instance; if it has no entry, `_assert_fence` returns
  immediately (V9). A restarted process is unfenced.
- **Different conversations never share a fence namespace.** `_fences` is keyed
  by `conversation_id`, and so is the `lease` table. Two workers are two
  namespaces (V7/E1).

So for a supervisor plus three workers there is **no mutual-exclusion primitive
in the system at all**. The lease protects a conversation from being resumed
twice. Nothing protects a *workspace* from being written twice.

### 5.3 The three concrete breakages, in the order they will bite

**(a) Duplicate effect via unshared intent dedup.** Worker 1 and worker 3 both
decide the fix needs `git add -A && git commit -m "add --dry-run"`. Identical
`intent_hash`. Worker 3's gate calls `find_by_intent(conv-worker-3, hash)` →
`None` → first sighting → EXECUTE. Two commits. The guarantee the README
states on its front page — *"Duplicate effect: none"* — is false for this
path. Prevalence prior: MAST FM-1.3, **15.7%** (V24).

**(b) Silently dropped effect via a false `LANDED`.** Worker 1 captures HEAD
before committing and crashes mid-tool. Worker 2 commits. Worker 1 resumes;
`GitProbe.probe` sees HEAD moved and returns `LANDED`; the gate returns
`SUBSTITUTE` and hands worker 1 an observation for work that never happened.
The ledger now says `COMMITTED` for an effect that does not exist, which is
the **one direction the whole design is built to avoid** — `docs/0008` §6.5
chooses fail-closed everywhere precisely to never assert this. Verified, E6.

**(c) Cross-claimed substitution via a fingerprint with no owner.** Seam B for
worker A offers `(action, call, observation)` into a handoff whose fingerprint
index is keyed on `sha256({tool_name, args})`. Worker B's Seam C — which, by
V12, is *the same handoff object*, because `register_tool` overwrote A's —
calls `claim()` and matches by fingerprint. B receives A's observation and
skips its own execution; A's later `claim()` misses and A executes again.
Verified, E7. Note the irony: the identity-first / fingerprint-fallback design
in `handoff.py`'s docstring was hardened against CPython address recycling
(`docs/0028`) and is *correct* for one agent; the fingerprint fallback is what
makes it wrong for two.

### 5.4 Why "just add a workspace lease" is not the fix

A workspace lease would serialize the workers, which removes the only thing
multi-agent was for. The useful decomposition is *concurrency without shared
mutable state* — which is §5.6's worktree recommendation — not mutual
exclusion over one tree. Cognition reaches the same place from a different
direction (V25): *"multi-agent systems work best today when writes stay
single-threaded."*

### 5.5 The chaos tests that would prove or disprove safety

In the style of `tests/test_chaos_nine_point.py`: real process death via
`os._exit()`, real effects counted from the filesystem, a barrier to make the
interleaving deterministic. The existing harness runs one
`experiments/0004-nine-point/worker.py`; these need a **two-worker harness with
a rendezvous file**, which is the single largest piece of new test
infrastructure.

| # | Name | Setup | Assert |
|---|---|---|---|
| **C1** | `test_two_agents_one_workspace_commit_at_most_once` | Two workers, distinct `conversation_id`, same repo, both told to commit the same change, barrier-released together | `rev-list --count HEAD` grows by **≤ 1** |
| **C2** | `test_concurrent_committer_does_not_produce_false_landed` | Worker A crashes at `mid_tool`; worker B commits; A resumes | A's resume verdict is **not `LANDED`/`SUBSTITUTE`**; A's commit either lands or is `BLOCKED`, never silently skipped |
| **C3** | `test_step_repetition_is_deduplicated_across_agents` | Two agents, identical `intent_hash`, sequential | The second gets `SUBSTITUTE`, not `EXECUTE` — **currently fails** (V10) |
| **C4** | `test_superseded_holder_cannot_start_a_new_effect` | A holds lease; B takes over; A calls `guard()` on a fresh id | A gets `BLOCK`/`ESCALATE` — **currently returns `EXECUTE`** (V8) |
| **C5** | `test_handoff_never_crosses_agents` | Agent A offers a substitution; agent B issues the identical call | B gets **no claim** — **currently claims A's** (V11) |
| **C6** | `test_append_under_two_writers_lands_at_most_once_each` | Both agents append a *distinct* line to one file, crash at each of the 9 points | Exactly one copy of each line; no interleaved half-lines. This is the `mid_tool` case from `docs/0019` squared |
| **C7** | `test_worktree_isolation_keeps_probe_verdicts_correct` | Per-worker worktrees; A crashes at each of the 9 points while B commits continuously | A's verdict matches the existing nine-point expectation table — **passes today** (E8) |
| **C8** | `test_ledger_survives_four_writer_processes` | 4 processes, 500 effects each, `synchronous=FULL` | Zero `OperationalError`; every record in a legal terminal state; p99 write latency recorded |
| **C9** | `test_blocked_effects_are_visible_after_a_fence_rejection` | Force the `StaleFence` → `_try_block` → `StaleFence` path from I3(a) | The record appears in `agentctl blocked` — **currently stranded in `INTENT`** |
| **C10** | `test_two_head_movers_in_one_batch_do_not_produce_a_false_landed` | **Single agent, single conversation.** Two HEAD-moving tool calls gated in one batch; execute the first; crash; resume | The second's verdict is **not `SUBSTITUTE`** — **currently fails** (V30/E13) |
| **C11** | `test_parallel_tool_execution_does_not_race_the_workspace` | `tool_concurrency_limit=2`; one `bash` doing `git commit` and one `write_file` in the same batch | Both effects land exactly once; no probe returns `LANDED` for the other's work — **expected to fail** (I7) |

**C10 and C11 are not multi-agent tests.** They belong to the shipped
single-agent path and should be written whatever this document's verdict is.
C3, C4, C5, C9 and C10 are written to fail today; that is the point. They are
the acceptance criteria for any future BUILD, and five of eleven failing before
a line of feature code is written is the measurement this phase was for.

### 5.6 Workspace isolation — the comparison, and the recommendation

| | separate `git worktree` | separate containers | one shared tree + locking |
|---|---|---|---|
| **Token cost** | unchanged; shared files still re-read per worker (26,713 tok in §6.3) | unchanged | unchanged in theory, **worse** in practice — a worker must re-read files another just changed |
| **Disk / setup cost** | shared object store, `.git` is a *file* not a symlink → **works on Windows with no Developer Mode** | Docker Desktop + WSL2; a new top-level dependency the README explicitly does not have | none |
| **Git probe** | **correct verdicts** (E8): `DID_NOT_LAND` when another worker commits, `LANDED` only for our own. `--show-toplevel` resolves to the worktree, so `docs/0019`'s toplevel guard now *distinguishes* workers | correct inside the container; the host ledger cannot see it | **broken** (E6): false `LANDED`, or an `INCONCLUSIVE` flood |
| **Concurrent writes** | **0 failures over 120 concurrent commits** (E9) | isolated by construction | needs a lock that serializes the parallelism away |
| **Crash recovery** | crashed worker's worktree is intact and re-probeable; `git worktree prune` cleans stale ones | container death loses the workspace unless bind-mounted; SQLite over a WSL2 bind mount has known locking hazards | crashed worker's file lock blocks everyone to TTL |
| **Integration cost** | supervisor must merge N branches — where V23's 5–10% semantic conflicts land | same merge problem, plus image build | none (that is the whole problem) |

**Recommend separate worktrees**, and only worktrees. Containers are the
funded-team answer and bring a dependency this project has deliberately
avoided. A shared tree with locking is the only option that breaks the git
probe, and it breaks it in the silent direction.

Worth stating: worktrees fix (b) from §5.3 and nothing else. (a) and (c) are
ledger and handoff bugs and survive any workspace layout.

### 5.7 The journal prerequisite, scoped and priced

`docs/0006`:76 gave the session/turn journal **"CONFIGURE for OpenHands /
BUILD for multi-agent"**, and single-agent work escaped the BUILD by
subscribing to OpenHands' own `EventLog` through
[`adapters/openhands/seam_b.py::OpenHandsContext`](https://github.com/csdeepak/HandCode/blob/6bb26d011244b933735539107b0c85dc60ee9f2f/agentctl/adapters/openhands/seam_b.py#L31),
which takes `conversation_id` as a constructor argument and hardcodes it into
every `ToolCall`. That single line is the whole reason the escape worked, and
the whole reason it stops working.

| # | Work item | Why multi-agent forces it | Days |
|---|---|---|---|
| J1 | **Schema migration machinery**, then `agent_id`, `parent_agent_id`, `workspace_key` on `effect_record`; new `agent` and `turn` tables | `schema.sql` is `CREATE TABLE IF NOT EXISTS` run through `executescript` on every connect — there is **no migration path for an existing ledger** today, and 4 crash experiments + a dogfood ledger exist | 2 |
| J2 | **Workspace-scoped lease** alongside the conversation lease, with `_assert_fence` extended to check both | V7: nothing protects a workspace | 2 |
| J3 | **Effect scope as a first-class concept**, so `find_by_intent` can ask "same effect, different agent, same workspace" — *and so two workers legitimately appending different lines are not wrongly collapsed* | V10/I4. This is a design question, not a `WHERE` clause change: today "same intent hash" means "same effect", and under multi-agent that is sometimes true and sometimes catastrophically false | 3 |
| J4 | **Per-agent Seam C isolation.** `register_tool` is a process-global that last-writer-wins (V12), so either one OS process per agent or a fork of tool resolution | V11/V12 | 3 |
| J5 | **Connection-per-thread or a single-writer queue** in `LedgerStore`, plus an explicit `busy_timeout` pragma rather than relying on `sqlite3.connect`'s default | V13. Note V29: today this would *not* fail loudly, so the queue is needed for correctness, not just to stop a crash | 2 |
| J6 | **Commit attribution in the git probe** — worktree-aware capture, or trailer stamping at Seam C for the dedicated `commit` tool | V15. `docs/0016` §4 chose fingerprinting over trailers precisely to stay at Seam B; multi-agent reopens that decision | 3 |
| J7 | **Client-agnostic journal + normalization layer**: turn records, the agent tree, and idempotency markers keyed on `(agent_id, tool_call_id)` rather than `tool_call_id` alone — the I2 gap `docs/0006` named | The ledger records *effects*, not *turns*; there is no record of which agent did what or who spawned whom | 4 |
| J8 | **Record/replay under interleaving.** `control/replay/cassette.py` keys turns by order within one conversation; concurrent agents interleave nondeterministically, so `--replay` — the project's zero-cost regression tool — stops being deterministic | `docs/0029`'s guarantee is single-threaded | 4 |
| J9 | **The C1–C9 chaos matrix** plus a two-worker rendezvous harness | §5.5 | 4 |
| J10 | `agentctl blocked` / `status` / `resolve` made agent-aware | `Guard.blocked()` filters by one `conversation_id` | 1 |
| | **Total** | | **24** |

**Does the SDK's subagent machinery shrink this?** The honest answer is: it
shrinks J7 *if and only if* U7 resolves favourably, and it cannot be checked
from the installed tree because the runtime is not there (V26). The two
in-tree hints disagree — `observability/laminar.py:428` says a subagent runs
*"synchronously inside its parent's `task` TOOL span"* (parent lineage), while
`subagent/registry.py`'s factory gives each subagent its own condenser LLM with
a distinct `usage_id` *"else its tokens get deduped out of conversation stats"*
(separate accounting). **If subagent events land in the parent `EventLog` with
`parent_id` links, J7 shrinks from 4 days to roughly 1** — Seam B would only
need to read an agent id off the event instead of taking it from a constructor
argument. **If they land in a separate conversation, J7 grows**, because
`protect()` acquires one lease per `conversation_id` (V7) and every worker
would need its own `Guard`, its own `LedgerStore` and its own Seam C — which
V12's process-global `register_tool` forbids inside one process.

Nothing else in the table moves. J1–J6 and J8–J10 are all about *this*
codebase's assumptions, and the SDK does not hold any of them for us:
`ResourceLockManager` locks tool names, not workspaces (V27); `max_budget_per_run`
cannot fire on unpriced endpoints (V31); and `tool_concurrency_limit` is a
footgun rather than a guarantee (V28, I7).

**24 engineering days before a single line of multi-agent feature code**, and
that estimate has a known bias: this project's own record (README, "Method")
is that *"every milestone so far has been finished by a bug only execution
could find"* — cp1252 on Windows, a crashed process holding its own lease, CRLF
breaking the append probe. Concurrency bugs are the worst class for that.
Against the observed velocity (M2a+M4+M2b landed 2026-09-05 → 09-08), 24
engineering days is plausibly 3–5 calendar weeks. J3 and J8 are the two items
that are *design* problems rather than implementation ones, and either could
double.

---

## 6. The token arithmetic, shown

### 6.1 Inputs, and which are measured

| Quantity | Value | Provenance |
|---|---|---|
| System prompt | 3,208 tok | **measured** — `Agent.static_system_message`, cl100k, SDK 1.45.0 |
| Tool schemas (3) | 385 tok | **measured** — `bash` 122, `read_file` 117, `write_file` 142 |
| Fixed per-request prefix | **3,593 tok** | sum of the above; paid on *every* request |
| `runner.py` | 4,495 tok | **measured**, cl100k |
| `cli.py` | 6,614 tok | **measured** |
| `tests/test_cli.py` | ~700 tok | **measured** (2,818 chars) |
| `max_output_tokens` | 4,096 | **measured** — `runner.py::run` |
| Turn structure, retries, report sizes | modelled | stated per row in §6.2/6.3 |

The task: *"add a `--dry-run` flag to `agentctl run`; thread it through
`cli.py` and `runner.py`; add a test."* A genuine multi-file change on this
codebase, of the kind the owner would actually run. Cumulative context is
modelled exactly — every request resends the prefix plus the whole history so
far, which is what makes agent cost quadratic in turns.

### 6.2 One agent

```
  # turn                                  ctx in     out     obs
  1 bash: ls -R agentctl                   3,713      60     400
  2 bash: grep max_iterations              4,173      60     600
  3 read_file runner.py                    4,833      40   4,495
  4 read_file cli.py                       9,368      40   6,614
  5 read_file tests/test_cli.py           16,022      40     700
  6 write_file runner.py                  16,762   4,615      30
  7 write_file cli.py                     21,407   6,734      30
  8 write_file tests/test_dry.py          28,171     900      30
  9 bash: pytest -q  (FAILS)              29,101      60     800
 10 read_file runner.py (re-read)         29,961      40   4,615
 11 write_file runner.py (fix)            34,616   4,665      30
 12 bash: pytest -q  (passes)             39,311      60     400
 13 bash: git diff --stat                 39,771      60     300
 14 finish                                40,131     140       0
    TOTAL                                317,340  17,514
    14 requests · 334,854 tokens · final context 40,271
```

### 6.3 A supervisor and three workers, same task

Worker 1 owns `runner.py`, worker 2 owns `cli.py`, worker 3 owns the test.
**This model is deliberately generous to multi-agent**: one reconciliation
round, no duplicated work, no worker retries beyond one, no output inflation.

```
                              requests    input tok  output tok        TOTAL
single agent                        14      317,340      17,514      334,854
supervisor                          14      254,339       6,135      260,474
worker 1  (runner.py)                6       71,713       9,960       81,673
worker 2  (cli.py)                   5       76,284       7,354       83,638
worker 3  (tests)                    7       90,292       2,560       92,852
MULTI-AGENT TOTAL                   32      492,628      26,009      518,637

multiplier                       x2.29                              x1.55
```

Two overheads are worth naming separately because they are structural, not
modelling choices:

- **Re-reading shared files: 26,713 tokens of pure duplication.** `runner.py`
  is read by the supervisor (to plan), worker 1 (to edit), worker 2 (for the
  signature) and worker 3 (for the API). `cli.py` is read three times. No
  amount of prompt engineering removes this; it is what "N contexts" means.
- **The fixed prefix is paid 32× instead of 14×: 114,976 vs 50,302 tokens, a
  +64,674 tax** before any work is done. Every additional agent turn buys
  another 3,593-token toll.

And the supervisor is not cheap. It is the second-largest consumer in the
table (260k tokens) because it must read the files to decompose the task, then
absorb three reports, then re-read both files to reconcile. **A supervisor that
does not read the code writes a worse plan; a supervisor that does read it has
most of a single agent's context anyway.** That is the bottleneck V19 names.

### 6.4 Against the real pool

```
OpenRouter : 6 accounts x 50 req/day, ACCOUNT-WIDE over all :free models
             = 300 requests/day                                    [T1]
Groq       : 6 accounts x 2 models x 200,000 TPD = 2,400,000 tok/day [T1]
             per-account TPM ceiling = 8,000, charged on prompt+max_tokens
Mistral    : no verifiable published limit                          [T3/UNKNOWN]
```

**The Groq ceiling, worked through:**

```
  8,000  TPM ceiling
 -4,096  max_output_tokens declared by runner.py
 -3,593  system prompt + tool schemas
 ══════
    311  tokens of conversation before a 413
```

Turn 2 of §6.2 is already at 4,173. **11 of 14 single-agent requests exceed
8,000 tokens outright; the largest is 40,131 — five times the ceiling.** The
2.4M-token Groq pool cannot be spent by this agent at all (I1).

**What one task costs as a share of the day, on the only provider that works:**

| Scenario | req/task | tasks/day | % of the day's budget |
|---|---|---|---|
| single agent (measured model) | 14 | **21.4** | 4.7% |
| supervisor + 3 workers, clean decomposition | 32 | **9.4** | 10.7% |
| supervisor + 3 workers @ Anthropic's 3.75× (V19) | 52 | **5.8** | **17.3%** |
| automatic MAS @ the Illusion paper's 10× (V20) | 140 | **2.1** | **46.7%** |

And in tokens, for when Mistral or Groq is eventually usable:

| Scenario | tokens/task | vs Groq's nominal 2.4M/day |
|---|---|---|
| single agent | 334,854 | 14% |
| supervisor + 3 workers, clean | 518,637 | 22% |
| multi @ 3.75× | 1,255,702 | **52%** |
| multi @ 10× | 3,348,540 | **140% — one task exceeds the day** |

**The answer to "does multi-agent fit in this budget at all?" is: at the clean
rate it fits four times a day and at the rate the literature measures for
coding it fits twice, buying a result the same literature says is *worse* than
the single agent it replaced.** At the 10× rate one task exceeds the entire
nominal Groq daily token pool. That is the sentence the executive answer leads
with.

### 6.5 Cache affinity, quantified

`docs/0010` §6 warns that rotation destroys a warm cache and asks what N agents
do to it. The measurement inverts the question:

| Configuration | cache hit | uncached input per single-agent task |
|---|---|---|
| Pinned to one deployment (`docs/0025` §5, measured) | 96.34% | 11,615 tok |
| Through the pool, `simple-shuffle`, 42 deployments | 1/42 = 2.4% | 309,784 tok |
| | | **×26.7** |

There is no `optional_pre_call_checks: ["prompt_caching"]` in
`proxy/proxy_config.yaml` and no affinity code anywhere in `agentctl/` (V6).
So **the single agent already pays the full ×26.7 penalty the moment it uses
the pool.** N agents multiply the number of requests, not the miss rate.

Two consequences the brief did not anticipate:

1. **Cache affinity is not a multi-agent blocker. It is a live single-agent
   defect**, and it is worth exactly as much as the providers charge for
   tokens — which, on OpenRouter free, is **nothing**, because the cap is
   requests. It becomes worth fixing the day Groq or Mistral becomes usable
   (Groq's own docs say cached tokens do not count against rate limits).
2. `simple-shuffle` over a `pool` group spanning **seven distinct models**
   means consecutive turns usually change *model*, not just account. That is
   `docs/0023` §4's `tool_call_id` instability by design, and it is why
   `find_by_intent` exists. It is also `docs/0010` §7.1 case 4 —
   "different model, different family" — on every single turn.

### 6.6 Repriced against the SDK's actual subagent model

`docs/0037` asked for a hypothetical supervisor/worker design. The SDK's
`AgentDefinition` is more specific than that, and each of its knobs changes the
arithmetic in a direction worth naming:

| `AgentDefinition` field | Effect on §6.3's numbers | Net |
|---|---|---|
| `model: "inherit"` (the documented default) | every worker uses the **parent's LLM**, so all four agents draw on the same 300-request OpenRouter budget. No quota isolation, no per-worker failover domain | **no change** — §6.3 stands exactly |
| `model: <profile>` | a worker could be pinned to a different provider — *the only genuine budget win available* — but `registry.py` resolves it through `LLMProfileStore`, which this project does not use, and the pool's other providers are unusable (I1) or unverifiable (U1) | **no change today** |
| `tools: [...]` allowlist | a worker restricted to `read_file` **cannot produce effects at all**, which removes it from every hazard in §5.3 | see below — the one design that survives |
| `max_budget_per_run` | compared against `accumulated_cost`, which is `0.0` on every unpriced free endpoint (V31) | **inert; provides zero protection** |
| `max_iteration_per_run` | caps worker turns, the one control that does work | bounds the tail, not the mean |
| `condenser` (defaults to `LLMSummarizingCondenser` for subagents) | each condensation is an **extra LLM request** against the 300/day cap, plus a second `usage_id`'s tokens | **+1 to +3 requests per worker on long runs** |
| `hooks` (`PRE_TOOL_USE` / `HookDecision.DENY`) | a second place that can refuse a tool, independent of Seam B | see §7 note |

So the SDK's own model makes §6.3 **slightly worse, not better**: `model:
inherit` guarantees no quota isolation, `max_budget_per_run` cannot fire, and
per-subagent condensers add requests. The corrected planning figure is
**32 + 3 to 9 condenser requests = 35–41 requests per task**, i.e. **7.3 to 8.6
tasks/day** against the 300-request budget, before any of the failure-mode
multipliers in I5.

**The one configuration that survives every objection in this document is a
read-only subagent.** `tools: [read_file]` with `model: inherit` produces a
worker that cannot write, cannot commit, and therefore cannot reach the
ledger's write path, the git probe, or the substitution handoff at all. It
costs requests and buys context isolation — which is precisely Cognition's
formulation (V25): *"multi-agent systems work best today when writes stay
single-threaded and the additional agents contribute intelligence rather than
actions."* It is also, not coincidentally, the only shape that needs **none**
of the 24 days in §5.7.

---

## 7. Verdict

# SKIP multi-agent. FIX the batch bug first.

Not "BUILD AFTER the journal." **SKIP**, and the budget arithmetic is the
deciding evidence, exactly as `docs/0037` required. The FIX is separate and
unconditional: V30 is a defect in the shipped single-agent path and its
remediation does not depend on this verdict.

**The deciding chain, in one line each:**

1. The only usable provider caps **requests**, at 300/day (V2). Groq's 12
   deployments cannot serve this agent's context at all (I1). Mistral's 12 are
   unverifiable (U1). So the budget is 300 requests, not 42 deployments.
2. A supervisor plus three workers costs **2.29× the requests** of one agent
   in the best case I could construct — **35–41 requests once the SDK's own
   subagent defaults are priced in** (§6.6) — and 3.75×–10× at the rates
   actually measured for coding (§6.3, I5): 17% to 47% of the day, per task.
3. The thing bought with that is, on the only controlled budget-matched
   evaluation that includes SWE-Bench Lite, **worse than the single agent**
   (V20), and specifically worse for backbones at this pool's capability tier,
   one of which the authors had to exclude for producing invalid code patches
   (V21).
4. Even granting the benefit, it costs **24 engineering days** of
   correctness-critical prerequisite work (§5.7) against 502 tests that
   currently encode a single-writer assumption in at least four places.
5. And the feature would ship with a **duplicate-effect hole on the most
   prevalent multi-agent failure mode** (I4, V24) and a **silent dropped-commit
   hole** in the component the project's front page uses as its example (V15).
6. The SDK does not carry any of this for you. Its subagent *runtime* is not
   installed and not a declared dependency (V26); its resource locks key on
   tool names, not workspaces, and would let `bash` and `write_file` race
   (V27, I7); and its per-subagent budget guard cannot fire on an unpriced
   endpoint (V31). **Multi-agent is not greenfield, and it is also not free.**

**What overturns this verdict, and nothing less:**

- U1 resolves in Mistral's favour with a verified, dated token allowance large
  enough to absorb ×3.75, **and**
- C3, C4, C5, C7, C9 and C10 (§5.5) pass, **and**
- a replicated study shows a supervisor-worker topology beating a single agent
  *per token* on multi-file coding with a sub-frontier backbone.

The third condition is the one to watch. Four independent sources say the
opposite today, two of them from organisations that ship the feature and have
every incentive to say otherwise (V19, V25).

**Contradicting the owner, plainly.** `docs/0013` §7 put multi-agent in "Layer
3 — speculative, only once single-agent state is genuinely solid", and
`docs/0010` §9.1 gave subagents a flat SKIP. The research asked to overturn
those. It confirms them, and it sharpens the reason: single-agent state is
solid *because* it assumes one writer, and that assumption is load-bearing in
the lease, the intent-hash dedup, the substitution handoff and the git probe
simultaneously. Multi-agent is not a feature on top of this kernel. It is a
different kernel.

**What to do instead, in priority order.** The first item is not optional and
is not multi-agent.

1. **Fix V30 — the batch false-`LANDED`. (2 days, do this first.)** Land C10 as
   a failing test, then fix it. The defect is that `_capture()` runs at gate
   time for every call in a batch, so a positional probe fingerprints a world
   that later calls in the same batch will change. Two candidate fixes, both
   local to the kernel: *(a)* re-`capture()` at execution time for probes whose
   evidence is positional, which means Seam C has to feed the gate — a real
   design change; or *(b)* have `GitProbe` refuse to answer when its
   `pre_state` was captured in the same turn as an earlier HEAD-mover, which
   degrades to `INCONCLUSIVE` → BLOCK and is **correct, cheap, and fail-closed
   in the project's own idiom**. Prefer (b). This is the single highest-value
   output of this phase.
2. **Close I7 — pin `tool_concurrency_limit=1` explicitly in
   `runtime/runner.py`, with a comment saying why. (½ day)** It is the default
   today, so this changes no behaviour; it stops a future SDK default change
   or a profile-based construction from silently enabling concurrent tools
   against a single-writer kernel (V28). Add C11 as an `xfail` recording what
   would break. A one-line dependency default should not be able to void the
   guarantee on the README's front page.
3. **Close I1 — point one run at Groq and confirm the 413. (½ day)** If it is
   real, `agentctl doctor` should say *"Groq deployments cannot serve this
   context size"* rather than listing 12 healthy deployments that cannot do
   the job. Same class of honesty as `docs/0021` §5's pricing-coverage column
   and `docs/0034`'s four ways a key check can lie. While there, note that
   `max_budget_per_run`-style guards read `0.0` on this pool (V31) — the
   project already solved that with its `priced` column and the SDK has not.
4. **Land C7 as a single-agent test. (1 day)** Worktree isolation already
   passes (E8/E9). A test asserting the git probe stays correct with a
   concurrent committer buys the safety property with no multi-agent
   machinery, and it is the only piece of §5.7 worth building on its own
   merits.
5. **Write the DECISION document** recording this SKIP, per `CONVENTIONS.md`.
   `docs/0037` says nothing in `agentctl/` changes before it exists — which,
   note, means items 1–4 need that document written first.

**If some multi-agent is wanted anyway**, the only shape this document can
defend is a **read-only subagent**: `tools: [read_file]`, `model: inherit`
(§6.6). It cannot write, cannot commit, and therefore touches none of §5.3's
three breakages, and it needs none of §5.7's 24 days. It costs requests and
buys context isolation — exactly Cognition's *"additional agents contribute
intelligence rather than actions"* (V25). It still needs
`openhands-tools` for a runtime that is not currently a dependency (V26).

The honest summary for `docs/0037`'s own standard — *"its most valuable
possible output is still the `0005` one: what should I not build?"* — is that
this phase's value is a 24-day build not started, a correctness core not
broken, **and one real bug in the shipped single-agent path found by looking
for a different one**.

---

## 8. Sources, tiered and dated

### T1 — source code, official documentation, papers

**This repository**, at commit `6bb26d011244b933735539107b0c85dc60ee9f2f`
(2026-09-15), all read 2026-09-20:
- `agentctl/kernel/ledger/store.py` — `LedgerStore.acquire` (L60), `find_by_intent` (L125), `_assert_fence` (L175), `write_intent` (L189), `_fences` (L48)
- `agentctl/kernel/ledger/schema.sql` — `lease` table, `PRAGMA journal_mode/synchronous`
- `agentctl/kernel/gate.py` — `EffectGate._guard` (L63), `_decide_on` (L93), `_resolve_ambiguous` (L119), `_try_block` (L264)
- `agentctl/kernel/reconcile/git.py` — `GitProbe.probe` (L75), the `LANDED` branch (L90)
- `agentctl/kernel/reconcile/base.py` — the single-writer assumption (L22–26)
- `agentctl/adapters/openhands/handoff.py` — `SubstitutionHandoff.claim` (L56), `_by_fingerprint` (L47)
- `agentctl/adapters/openhands/seam_c.py` — `install` (L181), `register_tool` call (L190)
- `agentctl/adapters/openhands/__init__.py` — `protect` (L74), single `acquire` (L105)
- `agentctl/adapters/openhands/seam_b.py` — `OpenHandsContext` (L31)
- `agentctl/runtime/runner.py` — `max_output_tokens=4096` (L189), `holder=f"run-{os.getpid()}"`
- `proxy/proxy_config.yaml` — 42 deployments / 18 accounts, `router_settings`
- `agentctl/control/providers.py` — `PROVIDERS`, and the deliberate absence of rate limits (L13)
- `tests/test_chaos_nine_point.py` — the nine-point style C1–C9 follow

**openhands-sdk 1.45.0** (vendored in `.venv`, read 2026-09-20 — the only
installed `openhands` distribution; `pyproject.toml` declares
`openhands = ["openhands-sdk>=1.45.0"]` and nothing else):
- `openhands/sdk/tool/registry.py::register_tool` — module-global `_REG`, duplicate names warn and overwrite
- `openhands/sdk/agent/base.py:293` — `tool_concurrency_limit: int = Field(default=1, ge=1, …)` and its shared-state warning; `Agent.model_post_init` builds the executor from it
- `openhands/sdk/agent/parallel_executor.py` — `ParallelToolExecutor.execute_batch`, `_run_safe`, `_resolve_lock_keys` (`declared=False` → `tool:<name>` mutex)
- `openhands/sdk/conversation/resource_lock_manager.py` — `ResourceLockManager`, sorted acquisition, per-prefix timeouts
- `openhands/sdk/tool/tool.py:513-521` — `ToolDefinition.declared_resources` default `DeclaredResources(keys=(), declared=False)`
- `openhands/sdk/agent/response_dispatch.py:160-184` — the batch loop: all `ActionEvent`s emitted, **then** `_execute_actions`
- `openhands/sdk/agent/agent.py:1341` — `on_event(action_event)`; `:571-588` — `_execute_actions` → `_ActionBatch.prepare` (worker threads) → `batch.emit` (caller thread)
- `openhands/sdk/subagent/schema.py::AgentDefinition` — the Claude Code frontmatter fields; `subagent/registry.py::agent_definition_to_factory` — `model: inherit`, tool allowlist, per-subagent condenser with a distinct `usage_id`
- `openhands/sdk/conversation/impl/local_conversation.py:705-712` — `max_budget_per_run` compared against `accumulated_cost`
- `openhands/sdk/hooks/types.py`, `hooks/executor.py` — `PRE_TOOL_USE`, `HookDecision.DENY`
- **Absent from the installed tree:** `TaskManager` (referenced only in `subagent/registry.py:177` and `observability/laminar.py:428`), and any `task`/delegate tool in `sdk/tool/builtins/`

**Official provider documentation:**
- OpenRouter, *API Rate Limits*, `openrouter.ai/docs/api-reference/limits` — 50 free requests/day account-wide, 1,000 with $10+ lifetime credits, 20 RPM. Fetched **2026-09-20**.
- Groq, *Rate Limits*, `console.groq.com/docs/rate-limits` — `openai/gpt-oss-20b` and `-120b` free tier: 30 RPM / 1K RPD / 8K TPM / 200K TPD, organization-level, cached tokens exempt. Fetched **2026-09-20**.

**Papers** — note that every one is an arXiv preprint; none could be confirmed
peer-reviewed from its arXiv record, so none of them decides anything alone.
They are used to corroborate each other and the T2 vendor statements:
- Cemri, Pan, Yang et al., *Why Do Multi-Agent LLM Systems Fail?*, arXiv:2503.13657v3, **26 Oct 2025**, UC Berkeley. **Preprint** (v1 17 Mar 2025, v3 26 Oct 2025; no venue on the arXiv record). MAST taxonomy, 1,642 traces, κ=0.88. FM-1.3 step repetition 15.7%.
- Jwalapuram, Lin, Li et al., *The Illusion of Multi-Agent Advantage*, arXiv:2606.13003v2, **13 Jun 2026**, Salesforce Research / HKUST-GZ / UBC / NTU. **Preprint.** CoT-SC beats automatic MAS at <10% of cost; SWE-Bench Lite included; GPT-OSS competency floor.
- Fu, Fang, Shao et al., *Do More Agents Help? Controlled and Protocol-Aligned Evaluation of LLM Agent Workflows*, arXiv:2606.05670v1, **4 Jun 2026**. **Preprint.** Normalized token accounting; 5 of 6 MAS trail the single-agent anchor.
- Anonymous, *CodeCRDT: Observation-Driven Coordination for Multi-Agent LLM Code Generation*, arXiv:2510.18893v1, **18 Oct 2025**. **Preprint.** 600 trials; −21.1% to +39.4%; 82–189% code inflation; 5–10% semantic conflicts; N=3 optimum.
- Tran & Kiela, *Single-agent LLMs outperform multi-agent systems on multi-hop reasoning under equal thinking token budgets*, **2026** — cited via arXiv:2606.13003; not read directly. Listed for completeness, decides nothing here.

### T2 — maintainer statements and official engineering blogs

- Anthropic, *How we built our multi-agent research system*, `anthropic.com/engineering/multi-agent-research-system`, **13 June 2025**. ⚠️ **Older than 12 months.** 15× / 4× token multipliers; explicit statement that coding is not a fit.
- Cognition (Walden Yan), *Don't Build Multi-Agents*, `cognition.com/blog/dont-build-multi-agents`, **12 June 2025**. ⚠️ **Older than 12 months.** Two principles; the Flappy Bird subagent-inconsistency example; "just use a single-threaded linear agent".

### T3 — third-party; corroborating only, decides nothing

- Multiple GitHub issue trackers and one DEV article (2026) describing Groq's 413 as a TPM-budget rejection charged on `prompt + max_tokens`. **Used only to raise the confidence of I1's mechanism; the arithmetic itself rests on T1.**
- Several aggregator sites reporting Mistral's free "Experiment" tier as 1 req/s, 500k TPM, ~1B tokens/month. **Explicitly not relied on — recorded as U1.**

### Experiments run for this document (E1–E13)

All against this repository, `.venv` Python 3.13.7, SQLite 3.50.4, Windows 11,
**2026-09-20**. Zero cost, no network, no API key.

| # | Question | Result |
|---|---|---|
| E1 | Does the lease exclude two agents in one workspace? | **No** — both granted, fence 1 each |
| E2 | Does intent-hash dedup cross conversations? | **No** — same conv finds the twin, other conv returns `None` |
| E3 | Does fencing reject a superseded writer's update? | **Yes** — `StaleFence` on an existing record |
| E4 | Do two writer processes corrupt or block the ledger? | **No** — 240 fsynced writes, 0.55 s, 0 errors; `busy_timeout` 5,000 ms |
| E5 | Can one `LedgerStore` be used from a second thread? | **No** — `ProgrammingError` |
| E6 | Git probe verdict with a concurrent committer, shared tree | **`LANDED` for an effect that never ran**; `INCONCLUSIVE` when the tree is merely dirtied |
| E7 | Does one agent claim another's substitution? | **Yes** — B received A's observation; A then fell through to execute |
| E8 | Git probe verdicts with per-worker worktrees | **Correct** — `DID_NOT_LAND` for another's commit, `LANDED` only for our own |
| E9 | Concurrent commits across 3 worktrees, one `.git`, Windows | **0 failures / 120 commits** |
| E10 | What does the gate do for a superseded-but-alive agent? | **`EXECUTE`** on a new `tool_call_id`, record written with the stale fence |
| E11 | Do agentctl's tools implement `declared_resources()`? | **No** — all three return `declared=False`; executor falls back to a `tool:<name>` mutex |
| E12 | Which tool pairs would run concurrently at limit > 1? | `bash`+`write_file` and `bash`+`read_file` **concurrent**; same-name pairs serialized |
| E13 | Two HEAD-movers in one batch, single agent, limit=1, crash between them | **False `LANDED` → `SUBSTITUTE`; the second commit is silently dropped and recorded `COMMITTED`** |

---

## 9. The decision I am asking you to make

**Do you accept SKIP for multi-agent execution, and close the ask in
`docs/0037` by recording that `docs/0013` §7 and `docs/0010` §9.1 were right —
and separately authorise the V30 fix, which is not a multi-agent decision at
all?**

The evidence that decides it is §6.4: the usable daily allowance is 300
OpenRouter requests, a supervisor-plus-three-workers task costs 17%–47% of
that at measured rates, and the controlled evaluation that includes SWE-Bench
Lite says the result is worse than the single agent it replaced — on backbones
one tier *above* this pool's.

If you accept, the follow-on work is five items totalling ~4 days (§7), none
of which is multi-agent. The first — fixing the batch false-`LANDED` (V30/E13)
— closes a hole in the guarantee the README states on its front page, and it
exists today whether or not you ever build a second agent.

If you reject, the entry price is the 24-day prerequisite in §5.7 **plus** a
dependency on `openhands-tools` that is not currently declared (V26), and the
first deliverable is C3, C4, C5, C9 and C10 going green — five tests that fail
today against a correctness core that currently passes 502.

**A third option exists and is cheap:** a read-only subagent
(`tools: [read_file]`, `model: inherit`, §6.6) needs none of the 24 days
because it cannot produce an effect. If the real want behind "multi-agent" is
*parallel exploration of a large codebase without polluting the main context*,
that shape delivers it and nothing in this document argues against it.
