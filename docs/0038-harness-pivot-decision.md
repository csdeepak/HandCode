---
Number:        0038
Title:         The Pivot That Was Already Built
Type:          DECISION
Status:        DRAFT
Created:       2026-09-20
Supersedes:    —
Superseded-by: —
Depends-on:    0037, 0006, 0010, 0013
---

# 0038 — The Pivot That Was Already Built

`0037` asked four questions about moving this project toward a Claude-Code-like
harness on many APIs with multi-agent execution. Four research deliverables
answer them:

- `research/phase-10-1a-python-harnesses.md` (1,044 lines)
- `research/phase-10-1b-nonpython-harnesses.md` (560 lines)
- `research/phase-10-2-multiagent-cost-and-safety.md` (1,177 lines)
- `research/phase-10-3-model-selection.md` (1,198 lines)

**Status is DRAFT until the owner accepts it.** That rule was written to mean
no code moves on this document's authority alone. Item 1 (§3) has since
landed in `c8113f3` — the owner authorised it directly, not via this
document — and the blanket sentence that stood here was false the moment it
did. Items 2-7 remain unaccepted.

---

## 1. The decision

**No pivot.** Stay on `openhands-sdk`. Do not port. Do not build multi-agent.
Do not build a model-switching layer. Fix one live bug, make two small
configuration changes, and add one narrow dashboard read.

The pivot's own justification did not survive contact with the evidence. It
rested on four premises, and three of them were false:

| Premise behind the ask | Finding |
|---|---|
| A different harness is needed for many APIs | **False.** Every live candidate — and the incumbent — accepts the LiteLLM proxy with zero code (10.1b §2.3) |
| Claude-Code-style features must be built | **False.** `openhands-sdk` 1.45.0 already ships them (§2) |
| Multi-agent is a feature to add | **False for this budget.** It does not fit, and it breaks four invariants at once (§4) |
| Model switching needs a translation layer | **False.** LiteLLM 1.100.0 already does it, more completely (§5) |

The fourth premise — that the current single-agent system is correct — is the
one that turned out to be wrong, and in the owner's favour: the research found
a live bug (§3).

---

## 2. The features are in the dependency — and none of them are wired up

**Corrected by the checkpoint-0 drift audit (§9).** An earlier draft of this
section said these features were "already present," and then treated that as
though the owner had them. He does not.

```
$ grep -rn "PRE_TOOL_USE\|HookDecision\|AgentDefinition\|subagent\|claude_code" agentctl/
$                                                    # zero hits
```

Every capability below ships in a library this project depends on and does not
call. "Available" is not "built," and the distinction is the whole difference
between the owner's ask and this document's answer to it.

Verified against the installed SDK at `.venv/Lib/site-packages/openhands/`,
version 1.45.0:

| Asked for | Ships in the SDK at | Wired into `agentctl` |
|---|---|---|
| Pre-tool hook that can refuse | `sdk/hooks/types.py:39` `HookDecision.DENY`; `executor.py:67` | **no** |
| Claude-Code-style subagents | `sdk/subagent/schema.py::AgentDefinition` — Markdown frontmatter, `model` (incl. `inherit`), `tools` allowlist, `max_budget_per_run`, hooks, condenser | **no** |
| Claude Code plugin manifests | `sdk/plugin/format/claude_code.py` | **no** |
| Parallel tool execution | `sdk/agent/parallel_executor.py` + `sdk/conversation/resource_lock_manager.py` | **no** |

`10-1a`:56 said the pivot budget should be spent on exactly these. §7 as
originally written spent it on none of them.

Two qualifications, both material:

- **The SDK ships the subagent format, not the runtime.** `TaskManager` appears
  in two docstrings and no module; there is no `task` tool (10.2).
- **`max_budget_per_run` is inert here.** It compares `accumulated_cost`, which
  LiteLLM reports as `0.0` on every unpriced free endpoint (10.2). A budget cap
  that reads zero is not a cap. This is `0021` §5's mistake in a new place.

---

## 3. The bug, which is the urgent finding

**A single agent, one conversation, `tool_concurrency_limit=1`, can silently
drop a commit and record it as `COMMITTED`.**

Two verified premises compose into it:

1. `_ActionBatch.prepare` takes a *list* of `ActionEvent`s, partitions blocked
   from executable, and only then executes
   (`.venv/.../openhands/sdk/agent/agent.py:228-250`). Every gate decision and
   every `capture()` therefore runs **before** any tool in the batch executes.
2. `write_intent` asserts the fence only when a record already exists —
   `prev = self.lookup(...)`, then `if prev is not None`
   (`store.py::write_intent`; the line moved when the fix landed). A fresh
   `tool_call_id` skips the fence entirely.

So two HEAD-moving tool calls in one assistant message both fingerprint the
same HEAD. The first commits. A crash before the second makes the second's
probe read HEAD-has-moved, conclude `LANDED`, `SUBSTITUTE`, and record
`COMMITTED` for a commit that never happened.

The nine-point chaos suite cannot see this: its worker issues one effect per
run. This is `0024` again — the right outcome by the wrong route — except here
the outcome is wrong too.

**This is the first work item, ahead of everything else in this document.**

---

## 4. Multi-agent: SKIP, and `0013` §7 is confirmed

`0013` §7 deferred multi-agent to "Layer 3 — speculative" and `0010` §9.1 gave
subagents a SKIP. Both stand, now with evidence rather than instinct.

### 4.1 The budget does not allow it

> **Superseded by measurement, 2026-09-21 (§9.4).** The paragraph below read
> the *generated config* and concluded the owner did not hold Gemini or
> Cerebras keys. He holds both. Gemini is live and was simply missing from a
> stale config. `0037` was right about what he holds and wrong about what the
> config contained; this section made the opposite error. The corrected pool is
> **48 deployments across 24 accounts**, and the ceiling below is not the whole
> allowance.

The pool is smaller than this project believed. `proxy_config.yaml` contains
**OpenRouter, Mistral and Groq only** — no Gemini, no Cerebras. `0037` asserted
otherwise; that assertion was wrong and is corrected here.

Worse, 12 of the 42 deployments cannot serve past turn 1: Groq meters
`prompt + max_tokens` against 8,000 TPM, leaving roughly 311 tokens of
conversation after `max_output_tokens` and the measured 3,593-token system
prompt and tool schemas. Mistral's free limits are not verifiable from
published documentation. **The whole practical allowance is OpenRouter's 300
requests/day** (6 accounts × 50, account-wide).

| Scenario | req/task | tasks/day | % of daily pool |
|---|---|---|---|
| single agent (measured) | 14 | 21.4 | 4.7% |
| supervisor + 3 workers, clean | 32 | 9.4 | 10.7% |
| + SDK subagent defaults (condensers) | 35–41 | 7.3–8.6 | ~12% |
| at Anthropic's measured 3.75× | 52 | 5.8 | 17.3% |
| **automatic MAS** @ the Illusion paper's 10× (SWE-Bench Lite) | 140 | 2.1 | **46.7%** |

At 10×, one task costs 3.35M tokens. Structural overhead is the cause, not
waste: 26,713 tokens of re-read shared files, and the fixed prefix paid 32
times instead of 14 (+64,674).

### 4.2 Four invariants break, not one

Single-agent state is solid *because* it assumes one writer, and that
assumption is load-bearing in four places simultaneously:

| Component | What breaks |
|---|---|
| Lease | Keys on `conversation_id`, so two agents in one workspace never contend |
| Intent dedup | `find_by_intent` is conversation-scoped, so repeated work becomes an *undetected* duplicate effect |
| Git probe | Returns `LANDED` for a commit that never ran when another agent moves HEAD |
| Handoff | `SubstitutionHandoff` fingerprints carry no agent, so one worker claimed another's observation |

Entry price: **24 engineering days** of prerequisite work plus an undeclared
dependency. 5 of 11 specified chaos tests fail today.

### 4.3 A latent hazard to close now

`ResourceLockManager` falls back to a per-*tool-name* mutex when tools do not
implement `declared_resources()` — and `agentctl/runtime/tools.py` does not. So
`bash` and `write_file` would run concurrently if the limit were ever raised.
`agentctl` never sets it today, so the hazard is latent and would not fail
loudly. **Pin it explicitly rather than relying on a default.**

### 4.4 What survives

- **Per-worker `git worktree` isolation restores correct probe verdicts** —
  verified, including 120 concurrent commits across 3 worktrees on Windows with
  zero failures. This is the design to use *if* multi-agent is ever revisited.
- **A read-only subagent** (`tools: [read_file]`, `model: inherit`) needs none
  of the 24 days, because it cannot produce an effect. This is the affordable
  slice of the original ask.

---

## 5. Model selection: mostly CONFIGURE

### 5.1 Cross-provider history — build nothing

LiteLLM 1.100.0 already rewrites tool definitions, tool-call emission,
tool-result return, parallel-call grouping and system-prompt placement for
Anthropic and Gemini, and it already handles the two hazards that actually
bite: it strips Gemini thought signatures from `tool_call_id` when the next hop
is not Gemini (`utils.py::function_setup`), and drops Anthropic thinking blocks
whose signature cannot be verified (`factory.py::_drop_unsignable_thinking_blocks`).

The entire change is one flag in `control/proxy.py::build`, which today emits
`drop_params: true` and nothing else ([`proxy.py:158`](../agentctl/control/proxy.py)):

```yaml
litellm_settings:
  drop_params: true
  modify_params: true        # enables sanitize_messages_for_tool_calling
```

**The counter-argument, stated fairly:** `modify_params` lets LiteLLM edit the
agent's action history invisibly, and this project exists partly because it does
not trust invisible edits to action history. The answer is that LiteLLM's
translation runs underneath either way — building a second normaliser means
owning two, and the one written here would not know about thought signatures.

One open decision: LiteLLM may silently inject a *synthetic tool result* for an
orphaned tool call. A system with an effect ledger should decide deliberately
whether that is acceptable, and if it is not, do that one repair in `agentctl`
where the ledger can see it.

### 5.2 The live pool is readable — from a different endpoint

`/v1/models` returns **model groups, not deployments**: against the 42-deployment
pool it returns exactly two rows, `pool` and `paid` (measured). `/model/info` is
the real answer — one row per deployment, `model_info.id` verbatim, `api_key`
stripped, and no credential needed because the generated config sets no
`master_key` (measured).

**BUILD, narrowly (<80 lines):** `dash.py::_providers` reads
`GET {proxy}/model/info` when a proxy is configured, falling back to the
environment when it is not, plus `/health/liveliness` for reachability. It
reports what the proxy actually loaded rather than what the environment implies.

**SKIP the live-capacity light.** Cooldown state has no HTTP surface — it lives
in the router's in-process `DualCache`. The nearest readable proxy,
`litellm_deployment_state` on `/metrics`, was measured still reporting `2.0`
(complete outage) **15 seconds after the cooldown had expired**, because it is
only cleared by a subsequent successful request. `/health` costs 42 completions.
Panel 1 must answer **UNKNOWN with its reasons**, per the standing rule that a
panel with nothing behind it says so.

### 5.3 Quota display — one provider, and only one

**BUILD:** `GET https://openrouter.ai/api/v1/key` returns
`free_model_daily_requests` with `used`, `limit`, `remaining`. `probe.py:55`
already calls the sibling `/api/v1/auth/key` with the same auth and the same
never-echo-the-key discipline, so this extends a tested path. Manual refresh
only.

**SKIP everything else.** Google AI Studio, Mistral and Cerebras expose no
usable quota signal to an ordinary inference key. Anthropic's Rate Limits API
needs an Admin key and is documented as unavailable for individual accounts.
These stay reactive: the 429 is the signal, and the pool routes around it.

This is exactly what `providers.py`'s docstring concluded independently —
*"What the key is worth, you find out from the provider"* — now backed by a
provider-by-provider audit.

**Passive and free:** record Groq's `x-ratelimit-remaining-*` when a response
carries them, displayed with the timestamp of the request that observed them.
Never poll.

---

## 6. If the harness is ever reconsidered

10.1b found exactly one non-Python harness that reproduces Seam C rather than
degrading to Seam B: **Goose**, via its Agent Client Protocol server
(`goose acp`), with Python as the ACP *client* declaring `fs.readTextFile`,
`fs.writeTextFile` and `terminal` capabilities. Goose then stops executing its
own `write`, `edit` and `shell` tools and sends each to the client, whose reply
*becomes the tool result*.

Everything else tops out at Seam B. OpenCode, Crush, Cline and Codex all fire a
pre-execution hook that can veto and rewrite arguments, but none has a field in
which a hook can return a result — so a blocked call reaches the model as a
rejection, never as the recorded output. That is the M2a-versus-M2b distinction
this project already drew, and it costs clean resume.

Cost if ever taken: **900–1,400 lines** of new Python (no Python ACP library
exists), and the nine-point chaos suite must be redesigned around JSON-RPC
exchanges rather than in-process function boundaries. The property survives;
the tests do not. `0013` §5's ~150-line estimate is falsified by roughly an
order of magnitude.

**Go/no-go before any adapter code:** a one-afternoon spike — stub ACP client,
crash between `terminal/create` and `terminal/output`, resume, count the
effects. It is the `docs/0014` experiment pointed at a new target.

Also settled: **Wispr is not a harness.** The reference was to Wispr Flow, a
voice-dictation product. **Roo Code is archived** (2026-05-15) and **Continue is
dormant** (3 commits on `main` since April 2026). **Aider is dropped** — last
commit 2026-05-22, and releases after 0.16.0 refuse Python 3.13. The
**OpenHands application** is dropped: it has no agent loop, being a FastAPI
server pinning `openhands-sdk==1.34.0`, eleven releases behind.

---

## 7. What changes

In order. Roughly four days, none of it multi-agent.

| # | Work | Why it is first |
|---|---|---|
| 1 | **Fix the batch false-`LANDED`** (§3), starting with a failing test | A live correctness bug; every other item assumes the ledger is honest |
| 2 | **Pin `tool_concurrency_limit=1` explicitly** (§4.3) | Closes a latent hazard that would not fail loudly |
| 3 | **Confirm the Groq 413 and make `doctor` report it** (§4.1) | 12 of 42 deployments are dead weight the user cannot currently see |
| 4 | **Land the worktree probe test** (§4.4) | Preserves the one verified multi-agent result |
| 5 | **`modify_params: true`** (§5.1), gated behind the suite | One line; removes a whole category of build work |
| 6 | **`dash` reads `/model/info`** (§5.2) | Reports what is loaded, not what is implied |
| 7 | **OpenRouter quota in `dash`** (§5.3) | The only honest quota number available |

Items 5–7 are **not** the owner's original ask, though an earlier draft of this
document claimed they were. They are a LiteLLM flag, a dashboard read and a
quota number. His ask was a section in which you *choose a source* — which
`research/phase-10-3-model-selection.md` §6.5 specifies in full, and which §7
omitted without declining it. Corrected by the checkpoint-0 audit (§9), which
also found asks #3 and #5 dropped.

A Phase 0 is supposed to shrink the work (`0007`). It is not supposed to shrink
the *ask*, and the difference is the thing this document got wrong.

---

## 8. What this falsified

Recorded because the method requires it:

- **`0037` §10.2 said the pool included Gemini and Cerebras.** It does not.
  Written from the provider registry rather than the generated config.
- **`0013` §5's ~150-lines-per-harness estimate.** Holds for the seams; refuted
  for a port, which drags 300–700 lines of new untested journal code with it
  (Python targets) or 900–1,400 lines (Goose/ACP).
- **The assumption that the double-execution bug is only a liability.** It is
  the mechanism Seam C runs on: OpenHands persists the action before executing
  and re-drives unmatched actions on resume, which is exactly the hook that
  lets a recorded result be substituted. Every Python challenger persists after
  the call returns, leaving no `tool_call_id` to match. Porting would not fix
  `0014`'s bug; it would make it undetectable.


---

## 9. Checkpoint-0 drift audit

An independent audit was run against this document with one question: *has the
owner's ask been quietly replaced with something easier?* It was told to verify
rather than trust, including everything here. Its findings, accepted:

### 9.1 What it falsified

| Claim | Verdict |
|---|---|
| §2 "already present" | **Overclaim.** `grep` over `agentctl/` for those SDK symbols returns zero hits. Available is not built. §2 rewritten |
| §7 "items 5-7 are the owner's original ask" | **False.** §7 rewritten |
| `sdk/agent/resource_lock_manager.py` | Wrong path; it is `sdk/conversation/`. Fixed |
| `store.py:194` | Stale after `c8113f3`. Re-anchored to the symbol |
| 10× row | Scope qualifier "automatic MAS" had been deleted from the research's own label. Restored |
| "Nothing in `agentctl/` changes before that" | Broken by this document's own first work item. Amended above |

It also found that **three of the owner's six asks are not on the work list**:
stripping unneeded features (`0037` Phase 10.4, never run and never declined),
the source picker (specified in full at `10-3` §6.5, omitted from §7), and the
Claude-Code harness surface (`10-1a`:56 named three SDK features to spend the
pivot budget on; §7 spent it on none).

### 9.2 The number that decides §4.1, now measured

The audit's sharpest finding was that **300 requests/day was assumed, never
measured**, while OpenRouter documents 50/day below $10 lifetime credit and
1,000/day above it — a 20× swing on the number the multi-agent verdict rests
on, one free HTTP call away, with the auth path already shipping in
`control/probe.py:54`.

Measured on 2026-09-21, `GET /api/v1/key`:

```
is_free_tier             : True
free_model_daily_requests: {"used": 0, "limit": 50, "remaining": 50}
```

**The assumption holds** for the one account reachable from this environment.
`keys.env` is absent here, so five of the six OpenRouter accounts were not
measured; 300/day stands only if they share the tier. Recorded as a
partially-closed unknown rather than a confirmed fact.

### 9.3 What the audit did not overturn

The STAY verdict, the pool composition, the Groq 311-token arithmetic, and the
four broken invariants were each re-checked against source and held. The audit's
own conclusion on multi-agent: **skip the supervisor-and-workers topology, but
lead with the safety argument, not the budget** — four correctness mechanisms
assume one writer, and that would decide it at any budget. §4 leads with the
budget, which is the weaker half.

It further noted that the **read-only subagent** — described at §4.4 as the
affordable slice of the owner's ask — was described and then not scheduled.


### 9.4 The keys file, and what the config was hiding

The owner supplied `~/.agentctl/keys.env`, which closed §9.2's open unknown and
opened a larger one. `agentctl keys --check`, 2026-09-21:

```
31/31 credentials authenticate across 6 provider(s)

  gemini     6 accounts   live, inference ok (gemini-3.6-flash)
  cerebras   6 accounts   authenticates, but inference needs payment
  openrouter 6 accounts   live, free tier
  mistral    6 accounts   live, inference ok
  groq       6 accounts   live, inference ok
  anthropic  1 account    paid, not called
```

**Two findings, and the second is the one that matters.**

*The 300/day ceiling is confirmed.* All six OpenRouter accounts report
`free_model_daily_requests limit=50` from `GET /api/v1/key`. §9.2's partial
measurement is now complete: 6 × 50 = 300/day for OpenRouter. The audit's
suspicion that the owner might be on the 1,000/day credited tier is closed
negative.

*But OpenRouter was never the whole allowance.* **Six live Gemini accounts were
being held and were absent from the generated config** — so §4.1's "the whole
practical allowance is OpenRouter's 300 requests/day" was false, not because
the 300 was wrong but because the sentence assumed the config described the
keys. It did not; it was stale. Regenerating with `agentctl proxy --verify`
produces **48 deployments across 24 accounts** (18 openrouter, 12 mistral,
12 groq, 6 gemini).

This matters beyond arithmetic. Twelve of those deployments are Groq, which
§4.1 establishes cannot carry a conversation past turn 1. `gemini-3.6-flash`
has no such limit. So the pool did not merely grow by six — it gained its first
free capacity that can sustain a long agent loop, while the config the whole
budget argument was computed over did not know Gemini existed.

Cerebras is correctly excluded: six accounts authenticate and none can infer
without payment, which is exactly what `providers.py`'s docstring predicted
would happen to a free tier and why it records no quota numbers.

**Consequence for §4.** The safety half of the multi-agent SKIP is untouched —
four invariants still assume a single writer, and that decides it at any
budget. The budget half is now materially weaker than this document claimed,
and the audit was right that it was the weaker half to lead with.
