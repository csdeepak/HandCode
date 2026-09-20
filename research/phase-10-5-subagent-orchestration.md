<!--
Phase 10.5 — Subagent deployability, cross-model, orchestration.
Frozen 2026-09-21. Static analysis + zero-cost local experiments only.
No provider API call was made for this document. Zero quota spent.

Repo state: main @ 093fb26 (`fix: one capped key spoke for five working ones`),
on top of 2ab2a74 (`feat: a subagent that cannot produce an effect`) and
b040b72 (`feat: pick a source, and be told what picking it costs`).
SDK: openhands-sdk 1.45.0, installed at `.venv/Lib/site-packages/openhands/`.
-->

# Phase 10.5 — A Read-Only Subagent: Deployable, Cross-Model, Orchestrated?

**Frozen 2026-09-21.** Every claim is tiered VERIFIED / INFERRED / UNKNOWN and
cited to `file:line`. Nine experiments (E1–E9) were run; all are local, all
cost nothing, and all are reproducible from the code in §9.

---

## 1. Executive answer

**Not deployable today, and the reason is a one-line default, not the design.**
`agentctl subagent reviewer "question"` — the exact command the shipped
`--init` example tells you to run — crashes before it reaches the network,
because the example says `model: inherit`, nothing supplies a parent model, and
`subagent.run()` hands `model=None` to a pydantic-validated `LLM` (E5). Three
more gaps sit behind it: no key discovery, no proxy-credential placeholder, and
no `--source`, so the subagent calls one key at one provider with no failover —
the single-account shape that `093fb26` just finished removing from the
verification layer. All four are small; together they are the difference
between a demo and a tool.

**Cross-model works, and works better than the brief assumed — but not by the
route the brief assumed.** `definition.model` naming another provider does
function, by accident, because `LLM(api_key=None)` lets LiteLLM read that
provider's own env var (E9). But it reaches one of six accounts and has no
failover. The right answer is the one that landed four commits ago and was not
wired to subagents: **`--base-url <proxy> --model openai/pool-gemini`**. That
gets Gemini-only routing across all six Gemini accounts with `num_retries: 5`
and a 300s cooldown, and it answers the failover gap and the cross-provider
question with the same twenty lines. A read-only subagent with one tool also
genuinely dodges the cross-provider schema hazards of `phase-10-3` — not
because it is read-only, but because `read_file` has two scalar string fields
and no parallel calls to group.

**Cross-provider fan-out beats `docs/0038` §4.1, decisively, on the constraint
that actually binds.** On a 12-file reconnaissance task, a supervisor plus
three read-only workers costs **3 OpenRouter requests instead of 13** — the
workers spend Gemini, Mistral and Groq quota, which §4.1 counted as zero.
That is **100 recon tasks/day instead of 23**, a 4.3× gain, and it inverts
§4.1's verdict for this one shape. The catch is that two of the three legs rest
on a quota nobody has measured (Gemini's free tier is no longer published) and
the third (Groq) needs `max_output_tokens` to become a parameter before it can
serve a second turn.

**Two concurrency bugs found, one of them live today.** `subagent.run()` writes
`os.environ[AGENTCTL_WORKSPACE]` (`subagent.py:155`) and never restores it. Run
two subagents concurrently on different workspaces and one silently reads the
other's files — confirmed end-to-end with two real agents against a stub
endpoint (E7): the subagent scoped to workspace `alpha` reported
`BRAVO-ONLY-SECRET` and reported it confidently. The same variable leaks
**sequentially** too (E4): after a subagent returns, the parent's next
`read_file` resolves against the subagent's workspace. Separately,
`subagent.run()` calls `rt.register_all()` (`subagent.py:146`), which overwrites
Seam C's gated tool resolvers with ungated ones in the SDK's global registry
(E8) — latent while `agentctl subagent` is its own process, a silent gate
bypass the moment an orchestrator shares one.

**The premise, contradicted where it deserves it.** A read-only subagent is
*not* a general-purpose worker, and the natural use case is the one it cannot
serve. `write_file` replaces a file's **entire** contents (`tools.py:255-257`),
so any agent that edits a file must hold that whole file in context. A
read-only worker's 400-token summary cannot substitute for it. On
`phase-10-2` §6.2's own benchmark task — edit `runner.py`, edit `cli.py`, add a
test — a read-only fan-out saves **nothing**, because the supervisor must read
all three files anyway before it can write them. Read-only subagents pay off on
**reconnaissance over files the writer will not touch**, and nowhere else. Sell
them as that or they will disappoint.

---

## 2. VERIFIED

Direct observation of source in this repo or in
`.venv/Lib/site-packages/openhands/` (T1), or a zero-cost local experiment.

### 2.1 The shipped command cannot run (E5)

| Step | Evidence |
|---|---|
| The example definition says `model: inherit` | `agentctl/cli.py:398` (`EXAMPLE_SUBAGENT`) |
| `--model` has no default | `agentctl/cli.py:767` — `sa.add_argument("--model", ...)`, no `default=` |
| The CLI passes it straight through | `agentctl/cli.py:487-488` — `run_subagent(..., model=args.model, base_url=args.base_url)` |
| `inherit` collapses to the `--model` value | `agentctl/runtime/subagent.py:161-162` — `chosen = model if declared in ("inherit","",None) else declared` |
| `LLM(model=None)` is rejected | **E5**: `pydantic ValidationError: 1 validation error for LLM` |

Contrast `agentctl run`, which defaults `--model` at `cli.py:719` and again at
`runner.py:37`. The subagent path has neither.

`inherit` is also a misnomer in this implementation. There is no parent LLM to
inherit from — `subagent.run()` is a standalone entry point that constructs its
own `LLM` (`subagent.py:164-166`). `inherit` means "whatever `--model` says,"
and when nothing says, it means "crash."

### 2.2 `definition.model` does not mean what the SDK means by it

`agentctl` treats `definition.model` as a **LiteLLM model id**
(`subagent.py:162` → `LLM(model=chosen)`). The SDK treats it as a **profile
name in an `LLMProfileStore`**:

```python
# .venv/Lib/site-packages/openhands/sdk/subagent/registry.py:216-228
if agent_def.model and agent_def.model != "inherit":
    store = _get_profile_store(agent_def.profile_store_dir)
    available_profiles = [name.removesuffix(".json") for name in store.list()]
    profile_name = agent_def.model.removesuffix(".json")
    if profile_name not in available_profiles:
        raise ValueError(f"Profile {agent_def.model} not found in profile store. ...")
    llm = store.load(profile_name)
```

`schema.py:322` confirms the intent in prose: *"model (optional): Model profile
to use (default: 'inherit')"*.

This divergence is **not** a bug — it is a deliberate, undocumented
simplification, and `phase-10-2` §6.6 already flagged that the project does not
use the profile store. But it has one consequence that matters for question 2:
`store.load()` returns a **whole LLM**, carrying its own `api_key` and
`base_url`. That is the SDK's mechanism for per-provider credentials.
`agentctl` replaced it with a single `api_key` parameter, so the definition
cannot carry a credential and the caller must supply the right one for whatever
provider the definition names. Nothing in `subagent.run()` checks that they
match.

### 2.3 No key discovery, and no proxy placeholder (E6)

`runner.run()` does two things `subagent.run()` does not:

```python
# agentctl/runtime/runner.py:154-164
api_key, key_env = _key_for(model)
...
elif base_url and not api_key:
    api_key, key_env = "proxy-holds-the-credentials", None
```

`runner.py:157-163` documents exactly why the placeholder exists: LiteLLM
"errors with `Missing credentials ... set OPENAI_API_KEY` if it is None — which
sends you looking for a key you deliberately do not have."

**E6** confirms the string `proxy-holds-the-credentials` appears in
`runner.run` and not in `subagent.run`. `subagent.run()` has no `_key_for` call
either, so it also loses `runner.py:88-99`'s `_env_var_for()` — the code whose
whole purpose is to name the *right* variable rather than telling you to set
`OPENROUTER_API_KEY` for a `gemini/` model.

Net: **point a subagent at the proxy and it fails with LiteLLM's raw
credentials error**, the exact failure `runner.py` was fixed to prevent.

### 2.4 `--source` exists for `run` and not for `subagent`

`b040b72` added source groups. They are in the regenerated config
(`proxy/proxy_config.yaml`, measured today):

| `model_name` | deployments | accounts | models |
|---|---|---|---|
| `pool` | 48 | 24 | all free |
| `pool-openrouter` | 18 | 6 | `nex-n2.5-pro:free`, `nemotron-3-super-120b-a12b:free`, `deepseek-chat-v3.1:free` |
| `pool-mistral` | 12 | 6 | `ministral-3b-latest`, `mistral-small-latest` |
| `pool-groq` | 12 | 6 | `openai/gpt-oss-120b`, `openai/gpt-oss-20b` |
| `pool-gemini` | 6 | 6 | `gemini-3.6-flash` |

`agentctl run --source gemini` becomes `model = "openai/pool-gemini"`
(`cli.py:250`) after validating the name against `sources()`
(`cli.py:243-249`) and refusing without `--base-url` (`cli.py:237-242`).
`SOURCE_PREFIX = "pool-"` at `proxy.py:44`; `sources()` at `proxy.py:139-165`.

The subagent parser (`cli.py:760-769`) has `--model` and `--base-url` but **no
`--source`**. The mechanism for pinning a subagent to one provider *with*
failover already exists, tested (`tests/test_source_picker.py`), and is not
wired up.

### 2.5 A bare group name is not a valid model id (E9)

| model string | LiteLLM provider resolution |
|---|---|
| `openrouter/deepseek/deepseek-chat-v3.1:free` | `openrouter`, reads `OPENROUTER_API_KEY` |
| `gemini/gemini-3.6-flash` | `gemini`, reads `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| `mistral/mistral-small-latest` | `mistral`, reads `MISTRAL_API_KEY` |
| `groq/openai/gpt-oss-120b` | `groq`, reads `GROQ_API_KEY` |
| `pool` | **`BadRequestError`** — no provider |
| `pool-gemini` | **`BadRequestError`** — no provider |
| `litellm_proxy/pool-gemini` | `litellm_proxy` |

So the proxy form needs a prefix. `cli.py:616` documents `openai/pool`, and
`cli.py:250` builds `openai/pool-<source>`. Either works; a bare group name
does not. This is worth stating because a user reading
`agentctl models` will see the bare group name and try it.

**The second half of E9 is the load-bearing one:** with `api_key=None`,
LiteLLM reads the provider's own environment variable. That is why a
cross-provider subagent works today at all — `subagent.run()` never sets
`api_key`, and the CLI never passes one, so `gemini/gemini-3.6-flash` finds
`GEMINI_API_KEY` by itself. It is working by omission, not by design, and it
breaks the moment a programmatic caller passes the parent's key.

### 2.6 The workspace env var is a process-global, and it races (E3, E4, E7)

```python
# agentctl/runtime/tools.py:42-44
def _workspace() -> Path:
    """Where work happens. Configuration, never model input (`docs/0023` §3)."""
    return Path(os.environ.get(WORKSPACE_ENV, ".")).resolve()
```

It is read **at executor call time**, on whatever thread the tool runs on.
`subagent.run()` sets it at `subagent.py:155` and never restores it.
`runner.run()` sets it at `runner.py:132` and never restores it either.

**E7 — the decisive experiment.** Two real `AgentDefinition`s, two real
`subagent.run()` calls, two real `Conversation`s, driven by a local stub
OpenAI endpoint. Workspace `alpha` contains `secret.txt` = `ALPHA-ONLY-SECRET`;
workspace `bravo` contains `BRAVO-ONLY-SECRET`. Each agent is told to read
`secret.txt` and report it.

```
=== SEQUENTIAL (baseline) ===
  alpha: REPORT: the file said [{'type': 'text', 'text': 'ALPHA-ONLY-SECRET'}]
  bravo: REPORT: the file said [{'type': 'text', 'text': 'BRAVO-ONLY-SECRET'}]
=== CONCURRENT (two threads, one process) ===
  alpha: REPORT: the file said [{'type': 'text', 'text': 'BRAVO-ONLY-SECRET'}]
  bravo: REPORT: the file said [{'type': 'text', 'text': 'BRAVO-ONLY-SECRET'}]
  subagents that read the WRONG workspace: ['alpha']
  stub completions served: 8
```

**Confirmed, not refuted.** And note the shape: no exception, no warning, a
confident report of the wrong workspace's contents. This is a cross-workspace
**confidentiality** failure, not merely a wrong answer — a read-only subagent
scoped to one directory reads another one's files and hands them to the model.
"Read-only" bounds what it can *change*, and says nothing about what it can
*see*.

**E4 — the same bug without any threads.** The leak is not a concurrency bug
that concurrency creates; concurrency only makes it obvious.

```
  parent tool call BEFORE subagent : PARENT WORKSPACE
  (subagent runs, then returns; env is never restored)
  parent tool call AFTER  subagent : SUBAGENT WORKSPACE
```

So even a strictly sequential orchestrator — parent runs, dispatches a
subagent, resumes — has its own workspace silently repointed. `tests/conftest.py:24`
snapshots and restores `AGENTCTL_WORKSPACE` between tests, which is why no
existing test catches this.

### 2.7 `rt.register_all()` un-gates the parent's tools (E8)

`subagent.py:146` calls `rt.register_all()`, which registers the **plain**
tool classes. `protect()` registers **gated** classes under the same names
(`seam_c.py:187-200`: *"Re-register each named tool with a gated executor"*).
The SDK's registry silently overwrites — `tool/registry.py:138-141` has a
literal `# TODO: throw exception when registering duplicate name tools` and
logs a warning.

```
after protect() installed Seam C:
    execute_bash  -> agentctl.adapters.openhands.seam_c
    write_file    -> agentctl.adapters.openhands.seam_c
    read_file     -> agentctl.adapters.openhands.seam_c
after subagent.run()'s rt.register_all():
    execute_bash  -> agentctl.runtime.tools
    write_file    -> agentctl.runtime.tools
    read_file     -> agentctl.runtime.tools
```

`runner.py:135-136` already knows this is dangerous — *"Do NOT register the
plain tools here: `protect()` registers gated versions under the same names"* —
and `subagent.py:144-146` does it anyway, with a comment explaining why
(a subagent started straight from the CLI has no parent run to have registered
them). Both comments are correct in isolation. Together they are a hazard.

**Why it is latent today:** `Agent` materialises its tools once, guarded by
`_initialized` (`agent/base.py:545`, `:628`), and `agentctl run` resolves
before a subagent could run. **Why it stops being latent:** an in-process
orchestrator that dispatches a read-only scout *before* the writer's first
step gives the writer ungated `execute_bash` and `write_file`. That is the
natural orchestrator design, and it is the same "latent, silent, would not
fail loudly" shape `docs/0038` §4.3 closed for `tool_concurrency_limit`.

### 2.8 What does *not* race (three candidate hazards, refuted)

| Candidate | Verdict | Evidence |
|---|---|---|
| Persistence dir collides between concurrent runs of the same subagent | **No** | `persistence_dir` is `<base>/<conversation_id.hex>` — `conversation/base.py:316-330`. `subagent.py:174` passes a name-keyed base, but each run gets a fresh `uuid4` (`local_conversation.py:322`), so subdirs differ. |
| `ResourceLockManager` serialises tools across separate agents | **No** | Per-`ParallelToolExecutor` instance (`parallel_executor.py:65`), and that is a per-`Agent` `PrivateAttr` (`agent/agent.py:416-417`). Two Agents share no lock. *This also means there is no cross-agent lock protecting the filesystem.* |
| `LLMRegistry` collides on a shared `usage_id` | **No** | `self.llm_registry = LLMRegistry()` is per-conversation (`local_conversation.py:494`). |

`tool_concurrency_limit` likewise does **not** constrain running several
separate agents. Its own field description scopes it: *"Maximum number of tool
calls to execute concurrently **within a single agent step**"*
(`agent/base.py:293-302`). `_build_agent`'s pin is correct and remains correct;
it is simply about a different axis than orchestration.

### 2.9 `service_id` is silently discarded (E1)

`subagent.py:165` passes `service_id=f"agentctl-subagent-{definition.name}"`.
There is no `service_id` field on `LLM` — the field is `usage_id`
(`llm/llm.py:596-604`) — and `model_config` is `ConfigDict(extra="ignore")`
(`llm/llm.py:676-678`). Measured:

```
usage_id after service_id kwarg : 'default'
has attr service_id?           : False
```

`runner.py:220` does the same thing. Harmless today (the registry is
per-conversation, §2.8) but the intent — distinguishing a subagent's spend —
is not achieved, and anyone reading the line would believe it was.

### 2.10 Measured token sizes (E1, E2)

| Quantity | Measured | `docs/0038` / `phase-10-2` §6.1 |
|---|---|---|
| System message, cl100k | **3,208** | 3,208 ✓ |
| `read_file` schema | **117** | 117 ✓ |
| `execute_bash` schema | **122** | 122 ✓ |
| `write_file` schema | **142** | 142 ✓ |
| **Read-only prefix** (`3,208 + 117`) | **3,325** | not previously computed |
| Writer prefix (all three) | **3,589** | 3,593 (4 tokens out) |

Two facts that fall out and matter later:

- **The system message is 3,208 tokens regardless of tool count.** Removing
  `bash` and `write_file` saves only their 264 schema tokens. A read-only
  subagent is **7.4% cheaper per request**, not meaningfully cheaper.
- `_build_agent` passes `include_default_tools=[]` (`runner.py:62`), so a
  subagent has **no `FinishTool` and no `ThinkTool`**, and
  `Agent.condenser` defaults to `None` (`agent/base.py:266-268`). The SDK's own
  subagent factory would have attached `default_condenser(...)`
  (`registry.py:257-259`). **`phase-10-2` §6.6's "+1 to +3 condenser requests
  per worker" does not apply to this implementation** — which is a real cost
  win and a real robustness loss: on context overflow it errors instead of
  auto-compacting.

### 2.11 Groq's limits, from the vendor (T1, fetched 2026-09-21)

`console.groq.com/docs/rate-limits`, free tier, `openai/gpt-oss-120b` and
`openai/gpt-oss-20b`: **30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD**, with
`x-ratelimit-*` headers on every response.

Note the RPD: **1,000 per model per account**. Six accounts × two models =
**12,000 requests/day of Groq headroom** against OpenRouter's 300. Groq is not
request-poor. It is token-poor, and that is the whole problem (§6.3).

### 2.12 Cost attribution is already free through the proxy

Seam A runs **inside the LiteLLM proxy** (`kernel/hook.py:1-5`), reading
`AGENTCTL_TELEMETRY` from the *proxy's* environment
(`proxy/agentctl_hook.py:12`), not the client's. The SDK sends
`x-litellm-session-id` = the conversation id
(`llm/options/common.py:78-83`, `local_conversation.py:1595-1606`), and the
hook reads it at `kernel/hook.py:151-152`.

So a subagent routed through the proxy **is already in the cost ledger**, under
its own `conversation_id`. It is attributable but **unlinked** to the parent,
because `subagent.py:172-179` constructs `Conversation` without passing
`conversation_id`. A subagent that calls a provider directly is invisible to
the ledger entirely.

---

## 3. INFERRED

Each states its chain. Confidence is mine, and named.

**I1. Routing subagents through the proxy answers the failover gap and the
cross-provider question with the same change.** *Chain:* §2.4 shows
`--source <name>` → `openai/pool-<name>` + `--base-url` already exists and is
validated; §2.11 and `proxy_config.yaml` show each source group spans all six
accounts of that provider; the generated `router_settings` set
`num_retries: 5`, `allowed_fails: 1`, `cooldown_time: 300` over the group, so a
capped key is skipped for five minutes while the other five serve. Therefore
one flag on `agentctl subagent` gives cross-provider pinning **and**
six-account failover, where a direct `gemini/...` call gives pinning and one
account. *Counter-argument, stated fairly:* it makes the proxy a hard
dependency for the interesting case, and the proxy is a separate process the
user must start. Direct mode should remain the zero-infrastructure path.
*Confidence: high.*

**I2. The live 429 that killed the demo would not have killed a proxy-routed
subagent.** *Chain:* the reported error carried
`X-RateLimit-Remaining: 0` on a single account; `093fb26`'s message records
that *"All six OpenRouter accounts were fine except the one it happened to
ask"*; `subagent.run()` calls one model with one key and has no retry across
accounts (`subagent.py:164-168`; `num_retries=2` retries the *same*
deployment). A proxy-routed call enters a group of 18 OpenRouter deployments
across 6 accounts and fails over. *Residual:* if the cap were genuinely
account-wide across all six, failover buys nothing — but `093fb26` establishes
it was not. *Confidence: high for the mechanism, medium for this specific
incident* (I did not see the raw trace).

**I3. A read-only subagent with one tool genuinely dodges the cross-provider
schema hazards — but because of the tool's shape, not its read-only-ness.**
*Chain:* `phase-10-3` §2.1 catalogues what LiteLLM 1.100.0 already rewrites and
names two poisons: Gemini thought signatures embedded in `tool_call_id`
(`utils.py::function_setup`) and unsignable Anthropic thinking blocks
(`factory.py::_drop_unsignable_thinking_blocks`), plus a repair pass for
orphaned/duplicated tool results gated on `modify_params`. A single-tool agent
never emits **parallel** tool calls, so the parallel-call grouping rewrite is
never exercised; `read_file`'s schema is two scalar strings
(`tools.py:179-181`, 117 tokens) with no enums, no nested objects, no unions —
the constructs that differ most across Anthropic/OpenAI/Gemini JSON-schema
dialects. *The read-only property contributes nothing here.* A read-only agent
with `grep`, `glob` and `read_file` would face the same parallel-call
translation as a writer. *Caveat:* this argument covers the *schema*. It does
**not** cover the synthetic-tool-result injection `docs/0038` §5.1 flags as an
open decision; a subagent hopping deployments mid-turn can still be handed a
tool result it never produced. It is less bad for a read-only agent (a
fabricated `read_file` result corrupts an answer, not the repository) but it is
not absent. *Confidence: high for schema, medium for the synthetic result.*

**I4. Parallel orchestration does not violate `test_tool_concurrency_pin.py`,
and the right way through is to call `subagent.run()` from threads.** *Chain:*
the test asserts exactly one `Agent(` call site in `agentctl/`, inside
`_build_agent` (`tests/test_tool_concurrency_pin.py:86-102`);
`subagent.py:139` imports `_build_agent` from `runner` rather than constructing
an `Agent`, so an orchestrator built on `subagent.run()` adds no call site and
the test keeps passing unchanged. §2.8 shows nothing in the SDK is shared
between two Agents. *So the SDK is not the obstacle — the two process-globals
in §2.6 and §2.7 are, and they are agentctl's own.* *Confidence: high.*

**I5. Fixing the workspace global properly means giving the tools a
non-global source, not save/restore around the call.** *Chain:* `_workspace()`
reads the env at call time on a worker thread (`tools.py:42-44`), so a
`try/finally` around `subagent.run()` narrows the sequential leak (E4) but does
nothing for E7 — two threads inside their windows simultaneously still collide.
`ToolExecutor.__call__` receives `conversation` as its second parameter
(`tools.py:129`, `:196`, `:264`) and every executor ignores it;
`Conversation(workspace=...)` is already passed (`subagent.py:173`) and lands on
`LocalWorkspace.working_dir` (`local_conversation.py:365-368`). So the plumbing
for a per-conversation workspace exists and is unused. *Counter-argument:*
`tools.py:43` and `docs/0023` §3 chose the env var deliberately — *"Configuration,
never model input"* — and reading it off the conversation could let a crafted
workspace value become model-influenced. The fix must keep the value
caller-supplied; a `contextvars.ContextVar` seeded by the caller preserves that
property exactly and is thread-local by construction. *Confidence: high for the
diagnosis, medium for `ContextVar` being the best of several fixes.*

**I6. The read-only fan-out's benefit is context compression, and it only
exists where the supervisor will not write the file it read.** *Chain:*
`WriteExecutor` replaces a file's entire contents (`tools.py:254-281`;
docstring: *"Writes the WHOLE file, which is what makes it
IDEMPOTENT_WRITE"*). To emit that, the supervisor must hold the entire file.
A worker's summary cannot substitute. On `phase-10-2` §6.2's benchmark — edit
`runner.py`, edit `cli.py`, add a test — all three files the workers would read
are files the supervisor must write, so the fan-out adds six requests and saves
zero context. It pays only when the read set is much larger than the write set.
*Confidence: high.* *This is the single most important limitation in this
document and it should be in the feature's help text, not just here.*

**I7. `max_budget_per_run` is inert, as `subagent.py:40-44` says — and is
additionally never read.** *Chain:* the module docstring's argument is correct
(`accumulated_cost` is `0.0` on unpriced free endpoints, `docs/0038` §2). But
`subagent.run()` reads `max_iteration_per_run` from the definition
(`subagent.py:177-178`) and never reads `max_budget_per_run` at all — it is not
passed to `Conversation`, unlike `runner.py:233-238` which sets it after
construction. So it is inert twice over. Harmless; worth one line in the
docstring so a reader does not go looking for the enforcement.
*Confidence: high.*

---

## 4. UNKNOWN

**U1. Gemini's free-tier RPD/RPM/TPM for `gemini-3.6-flash`.** This is the
number the entire fan-out budget rests on. `ai.google.dev/gemini-api/docs/rate-limits`,
fetched 2026-09-21, **no longer publishes a free-tier table**: it names the
tiers ("Free, Tier 1, Tier 3"), states that limits "can be viewed in Google AI
Studio," and links `aistudio.google.com/rate-limit`. This corroborates
`phase-10-3` §2.3 ("none documented") and `providers.py:96` ("Quotas are
per-model; check the console for current limits"). **Resolved at zero cost by:**
the owner opening `https://aistudio.google.com/rate-limit` while signed in and
recording the RPD/RPM/TPM for `gemini-3.6-flash`, one line into
`providers.py`. This is a web page, not an inference call — it spends nothing.
*Until then, every Gemini figure in §6 is conditional and labelled so.*

**U2. Mistral's free-tier limits.** Unchanged from `phase-10-2` §6.4 and
`docs/0038` §4.1: no verifiable published limit. `docs.mistral.ai/deployment/laplateforme/tier/`
returned **HTTP 404** today, so the previously-cited page has moved.
**Resolved by:** the console's own limits page, or by reading
`X-RateLimit-Remaining` off one real completion (which does cost one request).

**U3. Whether `gemini-3.6-flash` can sustain a 15,565-token worker context
inside its TPM.** Depends entirely on U1. `gemini-3.6-flash`'s *context window*
is not the constraint; its free-tier *TPM* is. **Resolved by:** U1, then
arithmetic.

**U4. Whether the proxy's `simple-shuffle` over a source group breaks a
subagent's turn.** `router_settings.routing_strategy: simple-shuffle`
(`proxy_config.yaml`) picks a fresh deployment per request. Within
`pool-gemini` all six deployments are the same model at different accounts, so
a mid-turn hop changes only the key — benign. Within `pool-groq` or
`pool-mistral` the group spans **two different models**, so consecutive turns
can change model mid-turn. Seam A's `TurnAffinity` (`kernel/hook.py:1-20`) is
designed to pin this, but `docs/0038` §5.1 records that it *"does not
eliminate"* synthetic tool-result injection. Whether a two-turn read-only
worker actually trips it was not tested. **Resolved by:** one offline run
against a stub proxy that deliberately alternates deployments mid-turn — the
E7 harness in §9 extends to this for free.

**U5. Whether a lowered `max_output_tokens` makes Groq usable in practice.**
§6.3's arithmetic says a one-read-one-report worker fits under 8,000 TPM at
`max_output_tokens=512`. It does not account for TPM being a *per-minute*
budget that a two-turn conversation accumulates against (§6.3 note). **Resolved
by:** one Groq run at `max_output_tokens=512` with `x-ratelimit-remaining-tokens`
captured — costs 2 requests out of 12,000/day, i.e. 0.017% of that pool. This
is the one live call I would recommend, and it is the cheapest of the set.

**U6. Whether `agentctl subagent`'s definitions directory diverges from the
SDK's on purpose.** `subagent.py:63` uses `.agentctl/agents`; the SDK's own
discovery uses `.agents/agents` and `.openhands/agents`
(`subagent/load.py:51-54`). `discover()` calls `load_agents_from_dir` directly
(`subagent.py:107`), bypassing `discover_agents`, so a Claude Code subagent
already sitting in `.agents/agents/` is invisible to `agentctl`. Given the
module docstring's claim to implement "the Claude Code subagent format," this
is probably an oversight rather than a decision, but I did not find a note
either way. **Resolved by:** asking the owner.

---

## 5. Mechanism — how a cross-provider read-only fan-out actually works

Implementer-level. What is shared, what races, what to do about it.

### 5.1 The topology

```
                    ┌──────────────────────────────────────┐
                    │ agentctl run  (the WRITER)           │
                    │ model openai/pool  --base-url proxy  │
                    │ gate ON · ledger ON · lease held     │
                    │ AGENTCTL_WORKSPACE = /repo           │
                    └───────────────┬──────────────────────┘
                                    │ orchestrator (plain code, no LLM)
              ┌─────────────────────┼─────────────────────┐
              ▼                     ▼                     ▼
      ┌───────────────┐     ┌───────────────┐     ┌───────────────┐
      │ scout-gemini  │     │ scout-mistral │     │ scout-groq    │
      │ openai/       │     │ openai/       │     │ openai/       │
      │  pool-gemini  │     │  pool-mistral │     │  pool-groq    │
      │ read_file only│     │ read_file only│     │ read_file only│
      │ no gate·no    │     │               │     │ max_out 512   │
      │  ledger·no    │     │               │     │  (else dies   │
      │  lease        │     │               │     │   on turn 2)  │
      └───────┬───────┘     └───────┬───────┘     └───────┬───────┘
              └─────────────────────┼─────────────────────┘
                                    ▼
                         3 × ~400-token reports
                     spliced into the writer's next turn
```

The orchestrator is **code, not an LLM**. That matters for the budget: the
"supervisor" in `phase-10-2` §6.3 cost 260,474 tokens precisely because it was
a model deciding how to decompose. If decomposition is a `for` loop over three
definitions, the supervisor cost collapses to the writer's own turns.

### 5.2 Request path for one scout

1. `subagent.run(defn, task, workspace=ws, model="openai/pool-gemini",
   base_url="http://localhost:4000", api_key=<placeholder>)`.
2. `validate(defn)` — refuses anything outside `{read_file}` and any
   `mcp_config` (`subagent.py:70-97`). Cheap, local, no I/O.
3. `rt.register_all()` (`subagent.py:146`) — **mutates the SDK's global tool
   registry.** ← *hazard, §2.7*
4. `os.environ[AGENTCTL_WORKSPACE] = str(ws)` (`subagent.py:155`) —
   **process-global.** ← *hazard, §2.6*
5. `LLM(model="openai/pool-gemini", base_url=..., api_key=...)`. LiteLLM
   resolves provider `openai`, posts to `<base_url>/chat/completions`.
6. Proxy: `model_name` lookup → `pool-gemini` group → `simple-shuffle` over
   6 deployments → `gemini/gemini-3.6-flash` with `GEMINI_API_KEY_n`.
   `num_retries: 5`, `allowed_fails: 1`, `cooldown_time: 300` handle a capped
   key. Seam A stamps the turn and records cost against this conversation's id.
7. `_build_agent(llm, ["read_file"])` — `tool_concurrency_limit=1`,
   `include_default_tools=[]`, no condenser.
8. `Conversation(agent, workspace=ws, persistence_dir=.../<name>/<uuid>.hex,
   max_iteration_per_run=...)`. Fresh `LLMRegistry`, fresh
   `ResourceLockManager`, fresh state lock. **Nothing shared with any other
   conversation.**
9. `conv.send_message(task); conv.run()`.
10. `_final_text(conv)` returns the last *agent* message (`subagent.py:198-229`).

Steps 5–10 are cleanly isolated per subagent. **Steps 3 and 4 are the entire
concurrency problem.**

### 5.3 The shared-state ledger, exhaustively

| State | Scope | Races across concurrent subagents? |
|---|---|---|
| `os.environ[AGENTCTL_WORKSPACE]` | **process** | **YES — proven, E7.** Last writer wins; the loser silently reads the wrong tree. |
| SDK tool registry `_REG` | **process** | **YES for correctness of the *writer*, E8.** Lock-protected so no corruption, but last-registration wins and Seam C loses. Two read-only subagents both registering the plain set is idempotent and harmless *between themselves*. |
| `Agent._tools` | per-Agent, `_initialized`-guarded | No |
| `ResourceLockManager` | per-`ParallelToolExecutor`, per-Agent | No — *and therefore no cross-agent filesystem lock exists* |
| `LLMRegistry` | per-Conversation (`local_conversation.py:494`) | No |
| Conversation state + lock | per-Conversation | No |
| `persistence_dir` | `<base>/<uuid>.hex` | No |
| Effect ledger / lease / git probe | **not touched** — no effect tools | No. *This is the read-only safety argument, and it holds.* |
| Cost ledger | written by the **proxy** process | No — appends per request, distinct `conversation_id` |
| `AGENTCTL_TELEMETRY` | process, `setdefault` in `runner.py:133` | No (subagent never sets it; the proxy owns the file) |

**The honest summary: read-only concurrency is safe in the SDK and unsafe in
`agentctl`, and both unsafe things are `os`-level globals in files this project
owns.** Neither needs the 24 days of `docs/0038` §4.2.

### 5.4 The two fixes, precisely

**Fix A — workspace.** Replace the env-var read with a `ContextVar` seeded by
the caller, falling back to the env var so nothing existing breaks:

```python
# agentctl/runtime/tools.py
import contextvars
_WS: contextvars.ContextVar[str | None] = contextvars.ContextVar("agentctl_ws", default=None)

def _workspace() -> Path:
    return Path(_WS.get() or os.environ.get(WORKSPACE_ENV, ".")).resolve()

@contextlib.contextmanager
def workspace_scope(ws: str | Path):
    tok = _WS.set(str(Path(ws).resolve()))
    try: yield
    finally: _WS.reset(tok)
```

`subagent.run()` wraps steps 4–10 in `workspace_scope(ws)` instead of assigning
the env var. Three properties this keeps: the value stays caller-supplied
(`docs/0023` §3's "configuration, never model input" is preserved exactly), the
sequential leak of E4 is closed by `reset`, and `ContextVar` values propagate
into `ThreadPoolExecutor` workers **only if the executor copies the context** —
which `ParallelToolExecutor` does not guarantee. **So the regression test must
be E7 itself, not a unit test of `workspace_scope`.** If propagation fails,
fall back to threading the workspace onto the executor instance at
`ToolDefinition.create()` time, which `tools.py:170`, `:207` and `:285` already
accept parameters for.

**Fix B — registry.** Make `register_all()` idempotent-and-deferential:

```python
def register_all(*, overwrite: bool = True) -> list[str]:
    from openhands.sdk.tool.registry import list_registered_tools
    already = set(list_registered_tools())
    for name, cls in TOOLS.items():
        if overwrite or name not in already:
            register_tool(name, cls)
    return list(TOOLS)
```

`subagent.run()` calls `register_all(overwrite=False)`. A standalone
`agentctl subagent` still registers everything (nothing is there yet); an
in-process subagent under a gated parent leaves Seam C alone. Guard it with a
test in the shape of `test_tool_concurrency_pin.py`: *after* `protect()`,
calling `subagent.run()` must leave `_MODULE_QUALNAMES["write_file"]` pointing
at `seam_c`.

### 5.5 Failure modes worth designing for

- **One scout 429s.** Through the proxy, five sibling accounts absorb it. Direct,
  the whole scout fails. The orchestrator must return a *partial* result set,
  and the writer's prompt must say which scout failed — a silently-missing
  report is `docs/0024`'s "right outcome by the wrong route" again.
- **A scout's report is wrong.** There is no verification. `read_file` errors
  come back as `ReadObservation.make(..., is_error=True)` (`tools.py:201-202`)
  and a model may narrate around one. The writer must treat reports as
  **pointers to verify**, not facts. This is the fan-out's real quality risk and
  the reason `phase-10-2` §6.3's "no duplicated work" model is generous.
- **A scout runs away.** `max_iteration_per_run` is the only real bound
  (`subagent.py:177-178`, and §I7). Default 15. Three scouts × 15 = 45 requests
  worst case. Set it to 5 for a scout and say so in the definition.

---

## 6. The budget arithmetic, shown

All inputs measured today (§2.10) except where marked. Cumulative context is
modelled exactly — every request resends the prefix plus the whole history,
which is what makes agent cost quadratic in turns. Same method as
`phase-10-2` §6.

### 6.1 Inputs

| Quantity | Value | Provenance |
|---|---|---|
| System message | 3,208 | **measured today**, E1, cl100k |
| `read_file` schema | 117 | **measured today**, E2 |
| **Read-only prefix** | **3,325** | sum; paid on every scout request |
| Writer prefix (3 tools) | 3,589 | **measured today**; `docs/0038` says 3,593 |
| `max_output_tokens` | 4,096 | `subagent.py:166`, hard-coded, no flag |
| Task statement | ~80 | modelled |
| A read_file tool call | ~40 out | modelled |
| A scout's final report | ~400 out | modelled |
| Recon corpus | 12 files × 3,000 tok | modelled |

### 6.2 The recon task: single agent vs. three scouts

*Task: "find where the lease TTL is enforced and what changes it" over a
12-file candidate set.*

**Single agent.** Request *i* carries `3,669 + 3,040(i−1)`:

```
  req  1: 3,669      req  5: 15,829      req  9: 28,029
  req  2: 6,709      req  6: 18,869      req 10: 31,069
  req  3: 9,749      req  7: 21,909      req 11: 34,109
  req  4: 12,789     req  8: 24,949      req 12: 37,149
  req 13 (report): 40,149
  ───────────────────────────────────────────────────────
  13 requests · 284,817 in · 880 out · 285,697 total · peak ctx 40,149
```

**One scout, 4 files.** Prefix 3,325 + task 80 = 3,405:

```
  req 1: 3,405   req 2: 6,445   req 3: 9,485   req 4: 12,525
  req 5 (report): 15,565
  ───────────────────────────────────────────────────────
  5 requests · 47,425 in · 560 out · 47,985 total · peak ctx 15,565
```

**Writer, consuming three reports:**

```
  req 1 (plan):                        3,669 in,  100 out
  req 2 (3 reports = 1,200 tok):       4,969 in,   40 out
  req 3 (read the one file that matters, 3,000):
                                       8,009 in,  400 out
  ───────────────────────────────────────────────────────
  3 requests · 16,647 in · 540 out · 17,187 total
```

**Totals:**

| | requests | tokens |
|---|---|---|
| single agent | 13 | 285,697 |
| 3 scouts | 15 | 143,955 |
| writer | 3 | 17,187 |
| **FAN-OUT TOTAL** | **18** | **161,142** |
| **vs single** | **×1.38** | **×0.56** |

The fan-out uses **38% more requests and 44% fewer tokens**. In
`phase-10-2` §6.3's units that is the opposite sign on tokens (×1.55 there) and
the same sign on requests (×2.29 there, ×1.38 here). The difference is entirely
that scouts return summaries instead of pulling file bodies into a context that
then carries them forever.

### 6.3 Against the real pool — where the verdict actually flips

`phase-10-2` §6.4 and `docs/0038` §4.1 both charge every request to
OpenRouter's 300/day, because `model: inherit` guaranteed it. Pinning scouts to
source groups changes the denominator:

| | OpenRouter req | Gemini req | Mistral req | Groq req |
|---|---|---|---|---|
| single agent | **13** | 0 | 0 | 0 |
| fan-out (writer + 3 scouts) | **3** | 5 | 5 | 5 |

```
  Binding pool = OpenRouter, 6 accounts × 50/day = 300/day   [T1, measured, docs/0038 §9.4]

  single agent   300 / 13 =  23.1 recon tasks/day      (4.3% of the pool per task)
  fan-out        300 /  3 = 100.0 recon tasks/day      (1.0% of the pool per task)
                            ─────
                            ×4.33
```

**This is the answer to question 4.** The cross-provider hypothesis is
correct and the effect is large: **4.33× more recon tasks per day on the
constraint that binds.** `docs/0038` §4.1's table is not wrong — it is
answering a different question. Its rows all assume one pool. Extend it:

| Scenario | req/task | OR req/task | tasks/day | % of OR pool |
|---|---|---|---|---|
| single agent, §4.1 measured | 14 | 14 | 21.4 | 4.7% |
| supervisor + 3 **writers**, clean | 32 | 32 | 9.4 | 10.7% |
| supervisor + 3 writers @ 3.75× | 52 | 52 | 5.8 | 17.3% |
| automatic MAS @ 10× | 140 | 140 | 2.1 | 46.7% |
| **writer + 3 read-only scouts, pinned cross-provider** | **18** | **3** | **100.0** | **1.0%** |

**Caveat that must travel with that row (U1, U2):** it assumes Gemini and
Mistral can absorb 5 requests peaking at 15,565 tokens. Gemini's free-tier
limits are **no longer published** and Mistral's were never verifiable. If
both legs were unusable and only Groq remained, the fan-out would be
`3 + 5 = 8` OpenRouter-equivalent... no: the two dead scouts' work returns to
the writer, which lands back near the single-agent figure. **The row is
conditional on U1, and U1 is a free lookup.**

**Groq, recomputed for a read-only worker.** `docs/0038` §4.1 computed 311
tokens of conversation headroom for the writer; my measurement gives 315 for
the writer and:

```
   8,000  TPM ceiling                     [T1, console.groq.com/docs/rate-limits]
  -4,096  max_output_tokens (subagent.py:166, hard-coded)
  -3,325  read-only prefix (measured)
  ══════
     579  tokens of conversation
```

579 instead of 311 — **better and still useless.** Scout request 1 is 3,405.
It does not fit. But `max_output_tokens` is a constant in one line of
`subagent.py`, and a scout's report is ~400 tokens:

```
  max_output_tokens = 4096  ->    579 tokens of conversation   (dead)
  max_output_tokens = 1024  ->  3,651                          (1 small file)
  max_output_tokens =  512  ->  4,163                          (1 file ≤ ~4k)
  max_output_tokens =  256  ->  4,419
```

**So the Groq verdict flips — partially.** At `max_output_tokens=512` a Groq
scout can read one ~4,000-token file and report. It cannot do the 4-file scout
above (request 2 is 6,445). And TPM is **per minute**, so even the two-turn
one-file scout accumulates `7,837 + 7,877 = 15,714` tokens inside one minute
against an 8,000 ceiling — **it must pace itself ~60s between turns** (U5).
Honest verdict: **Groq is a one-file, rate-paced reader**, worth having for
breadth, useless for latency, and it needs `max_output_tokens` to become a
parameter first. Its 12,000 RPD (§2.11) is enormous and almost entirely
unspendable.

### 6.4 What the fan-out does *not* buy (I6, restated with numbers)

On `phase-10-2` §6.2's benchmark — thread `--dry-run` through `cli.py` and
`runner.py`, add a test — the writer must emit whole-file `write_file` calls
for all three files. It must therefore read all three. Three scouts reading
those same three files add `3 × 2 = 6` requests and ~32,000 tokens and remove
**zero** tokens from the writer's context.

| Task shape | read set | write set | fan-out verdict |
|---|---|---|---|
| Recon: "where is X handled?" | 12 files | 0 | **×4.33 on the binding pool** |
| Review: "does this PR break Y?" | 8 files | 0 | **strong win** |
| Edit: "thread a flag through 3 files" | 3 | 3 | **pure loss: +6 req, +32k tok, 0 saved** |
| Mixed: "find the bug and fix it" | 12 | 2 | **win on the finding half only** |

---

## 7. Verdict per question, and a build order

### Question 1 — deployability: **NO today, YES after roughly a day's work.**

| Gap | Real blocker? | Why |
|---|---|---|
| `model: inherit` + no `--model` default → crash | **BLOCKER** | The shipped example command does not run (E5). Two lines. |
| No key discovery / no `_env_var_for` | **BLOCKER** | Failure is LiteLLM's raw error with no guidance; `runner.py:88-99` already solves it. |
| No proxy-credential placeholder | **BLOCKER** | `--base-url` cannot work without it (E6, `runner.py:157-164`). |
| **`AGENTCTL_WORKSPACE` leak (E4)** | **BLOCKER** | Bites *sequentially*, before any orchestration. Silent cross-workspace read. |
| No `--source` / no failover | **BLOCKER for real use** | One key, no failover — the shape `093fb26` just removed elsewhere. §I2. |
| `rt.register_all()` un-gates Seam C (E8) | **Latent; blocker for orchestration** | Harmless across processes; a silent gate bypass in one. Close it now, per `docs/0038` §4.3's own precedent. |
| No cost attribution | **Fine** | Free through the proxy already (§2.12). Linking to the parent is a nicety. |
| No record/replay | **Fine** | Genuinely useful for testing, not for shipping. `ReplayServer` exists and is reusable (§9 E7 is a variant of it). |
| Runs outside the effect ledger | **Fine — by design** | The safety argument holds; §5.3 confirms it. |
| `service_id` discarded (E1) | **Cosmetic** | Misleading line; one-word fix. |
| No condenser | **Accept, document** | Saves 1–3 requests/scout vs. the SDK default; errors instead of compacting on overflow. For a ≤5-iteration scout, the right trade. |
| `.agentctl/agents` vs `.agents/agents` (U6) | **Ask** | Claude Code definitions are currently invisible. |

### Question 2 — cross-model: **works; the useful version needs the proxy.**

Direct (`model: gemini/gemini-3.6-flash`) works today **only because
`api_key` is never set and LiteLLM reads `GEMINI_API_KEY` itself** (E9) — one
account of six, no failover, and it breaks if any caller passes a key.
Proxy-routed (`--source gemini` → `openai/pool-gemini`) gets all six accounts
plus retry and cooldown. `model: inherit` does **not** do what it looks like:
there is no parent, it means "use `--model`", and with no `--model` it crashes.
`definition.model` also diverges from the SDK's profile-name semantics
(§2.2) — fine as a choice, worth one line of documentation.

Schema hazards: a single-tool agent with two scalar string parameters does dodge
the parallel-call and complex-schema translation issues (§I3) — *because of the
tool, not the read-only property*. The synthetic-tool-result injection
`docs/0038` §5.1 flags is not dodged; it is merely less harmful.

### Question 3 — orchestration: **sequential works now; parallel needs the two fixes and nothing else.**

- **Does it violate `test_tool_concurrency_pin.py`?** No. `subagent.run()`
  routes through `_build_agent` (`subagent.py:139`) and adds no `Agent(` call
  site. An orchestrator calling `subagent.run()` from threads keeps the test
  green. §I4.
- **Does `tool_concurrency_limit=1` constrain running several agents?** No. Its
  own field description scopes it to "within a single agent step"
  (`agent/base.py:293-302`), and §2.8 shows nothing is shared between two
  `Agent`s — not the lock manager, not the LLM registry, not the tool cache.
- **The `os.environ[WORKSPACE_ENV]` bug:** **CONFIRMED, and worse than
  suspected.** E7 shows a real cross-workspace read with two real agents; E4
  shows the same variable leaks sequentially. Fix per §5.4A, regression-test
  with E7 itself.
- **Is read-only concurrency safe?** In the SDK, yes (§5.3 table). In
  `agentctl`, no — two process-globals, both ours, both fixable in a day, and
  neither requiring any part of the 24 days in `docs/0038` §4.2.

### Question 4 — budget: **the hypothesis is right, and it is conditional.**

Cross-provider fan-out beats §4.1's table **4.33×** on the binding OpenRouter
pool for recon-shaped tasks (§6.3). It saves 44% of tokens and costs 38% more
requests overall. It is worth **nothing** on edit-shaped tasks (§6.4, I6).
Groq needs `max_output_tokens` parameterised and even then is a one-file paced
reader (§6.3). **Gemini — the leg the whole thing leans on — rests on U1, an
unmeasured quota, resolvable free in one browser tab.**

### Build order

Smallest first. Each step names what it buys and what it costs.

| # | Step | Buys | Size |
|---|---|---|---|
| **0** | Owner opens `aistudio.google.com/rate-limit`, records `gemini-3.6-flash` RPD/RPM/TPM into `providers.py`. | Closes **U1** — the number §6.3's headline row depends on. Free. | 10 min, 1 line |
| **1** | Make `agentctl subagent` run. `--model` default = `runner.DEFAULT_MODEL`; call `_key_for` / `_env_var_for`; add the `proxy-holds-the-credentials` placeholder. | The shipped `--init` command works. Three of the four hard blockers. | ~15 lines |
| **2** | Fix the workspace global (§5.4A) + land **E7 as a test**. | Closes the confidentiality bug that bites sequentially *and* the one that blocks parallelism. Unblocks everything after. | ~25 lines + 1 test |
| **3** | `register_all(overwrite=False)` (§5.4B) + a Seam-C-survives test. | Closes the latent gate bypass before an orchestrator exists, exactly as `docs/0038` §4.3 argued for the concurrency pin. | ~8 lines + 1 test |
| **4** | `--source` on `agentctl subagent` — port `cli.py:232-251` verbatim. | Cross-provider pinning **and** six-account failover, one flag. Answers Q2's useful half and the failover blocker together (§I1). | ~20 lines |
| **5** | `--max-output-tokens` on `agentctl subagent` (default 4096, scouts use 512). | Makes `pool-groq` serve a turn at all (§6.3). Unlocks 12,000 RPD of otherwise-dead quota. | ~5 lines |
| **6** | `agentctl subagent --all "<question>"` — dispatch every valid definition, sequentially, collect reports, print them. | The orchestration product, at zero concurrency risk. Proves the workflow before adding threads. | ~40 lines |
| **7** | Make step 6 concurrent (`ThreadPoolExecutor`), gated on steps 2–3 passing. | The ×4.33 in §6.3 arrives with wall-clock as well as quota benefit. | ~15 lines |
| **8** | Pass `conversation_id` into the subagent's `Conversation` and stamp a parent id. | Links scout spend to the parent run in the cost ledger (§2.12). Nice-to-have; the data is already there, just unlinked. | ~10 lines |
| **9** | *Only if 0–8 all land:* one live Groq probe at `max_output_tokens=512`, capturing `x-ratelimit-remaining-tokens`. | Closes **U5**. **Cost: 2 requests of 12,000/day = 0.017%.** The only live call I recommend. | 1 run |

Steps 0–3 are the honest minimum before anyone calls this deployable. Steps
4–5 are what make it *worth* deploying. Steps 6–7 are the feature. **Do not
start at 6.**

One line of help text that should ship with step 6, per §I6:

> Scouts read; they do not write. A scout's summary cannot replace the file
> contents a `write_file` needs, so fanning out over files you are about to
> edit costs requests and saves nothing. Use them to find things.

---

## 8. Sources, tiered and dated

### T1 — source code, this repo @ `093fb26`
- `agentctl/runtime/subagent.py` — 40-44, 60, 63, 70-97, 100-119, 127-182, 139, 146, 154-155, 161-166, 168-179, 198-229
- `agentctl/runtime/runner.py` — 37, 40-70, 62, 88-99, 132, 135-136, 154-164, 219-222, 233-238
- `agentctl/runtime/tools.py` — 37, 42-44, 129, 170, 179-181, 196, 201-202, 207, 254-281, 285, 292-302
- `agentctl/cli.py` — 231-251, 395-406, 428-490, 616, 705-745, 760-769
- `agentctl/control/proxy.py` — 40-44, 47-75, 100-165, 190+, 240-254, 290-311
- `agentctl/adapters/openhands/__init__.py` — 74-150; `seam_c.py` — 187-200
- `agentctl/kernel/hook.py` — 1-33, 151-152; `agentctl/control/cost/ledger.py` — 30-46, 106-128
- `agentctl/control/providers.py` — 82-97; `agentctl/control/replay/server.py` — 1-60
- `proxy/proxy_config.yaml` (regenerated 2026-09-21; 48 deployments / 24 accounts, 5 model groups); `proxy/agentctl_hook.py:12`
- `tests/test_subagent.py`, `tests/test_tool_concurrency_pin.py:74-102`, `tests/conftest.py:24-30`

### T1 — source code, `openhands-sdk 1.45.0` (`.venv/Lib/site-packages/openhands/sdk/`)
- `subagent/schema.py` — 26-41, 198-282, 312-382 (esp. 207-209, 322)
- `subagent/registry.py` — 153-282 (esp. 216-228 profile store, 257-259 default condenser)
- `subagent/load.py` — 51-54, 175-216
- `agent/base.py` — 150-170, 255-310 (condenser default None; `tool_concurrency_limit` default 1, "within a single agent step"), 540-630
- `agent/agent.py` — 416-422; `agent/parallel_executor.py` — 51-65, 345-357
- `conversation/resource_lock_manager.py` — 35-117; `conversation/base.py` — 316-330
- `conversation/impl/local_conversation.py` — 300-500 (esp. 322, 365-368, 494), 1570-1610
- `llm/llm.py` — 200-218, 596-604, 676-678; `llm/options/common.py` — 60-85
- `llm/llm_profile_store.py` — 1-120; `tool/registry.py` — 31-34, 113-160

### T1 — official vendor documentation (fetched 2026-09-21)
- Groq, *Rate Limits* — `console.groq.com/docs/rate-limits`. Free tier,
  `openai/gpt-oss-120b` / `-20b`: **30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD**;
  `x-ratelimit-*` headers on every response; cached tokens exempt.
- Google, *Gemini API Rate Limits* — `ai.google.dev/gemini-api/docs/rate-limits`.
  Tiers named ("Free, Tier 1, Tier 3"); **no free-tier numeric table**; directs
  to `aistudio.google.com/rate-limit`. → **U1.**
- Mistral, `docs.mistral.ai/deployment/laplateforme/tier/` — **HTTP 404**
  today. → **U2.**

### T1 — prior measurements inherited (re-verified where cited)
- `docs/0038` §4.1, §4.2, §4.3, §4.4, §5.1, §5.2, §9.2, §9.4 — OpenRouter
  6 × 50 = 300/day confirmed across all six accounts via `GET /api/v1/key`;
  48 deployments / 24 accounts; 3,593-token writer prefix (I measure 3,589).
- `research/phase-10-2-multiagent-cost-and-safety.md` §6.1–§6.6 — token model,
  benchmark task, §6.6's `AgentDefinition` repricing.
- `research/phase-10-3-model-selection.md` §2.1 (LiteLLM normalisation), §2.3
  (per-provider quota signals), §4 U1–U6, §6.5 (source picker spec).
- Commit `093fb26` message — six OpenRouter accounts healthy, one capped.

### T2 — maintainer statements
- `tool/registry.py:139` — `# TODO: throw exception when registering duplicate
  name tools`, i.e. silent overwrite is acknowledged upstream as unfinished.
- `agent/base.py:296-301` — `tool_concurrency_limit` description: *"concurrent
  tools share the conversation object, filesystem, and working directory, so
  mutations to shared state may race."*

### T3 — none relied upon
No third-party source decided anything in this document.

### Staleness flags
- **U1 (Gemini free-tier limits)** gates §6.3's headline row. Free to close.
- **U2 (Mistral)** unchanged since `phase-10-2`; the cited doc URL has moved.
- SDK pinned at 1.45.0. §2.8's isolation guarantees (per-Agent lock manager,
  per-Conversation LLM registry) are implementation details, not documented
  contracts, and should be re-checked on upgrade.

---

## 9. Experiments — all local, all free, all reproducible

No provider API call was made. Total quota spent: **zero**.

| # | What | Result |
|---|---|---|
| E1 | `Agent.static_system_message` token count + `service_id` fate | 3,208 tok; `usage_id='default'`, no `service_id` attr; `condenser=None`; `include_default_tools=[]` |
| E2 | `to_openai_tool()` schema tokens | `read_file` 117, `execute_bash` 122, `write_file` 142 — matches `docs/0038` |
| E3 | Two threads set `AGENTCTL_WORKSPACE`, then call `ReadExecutor` | Both read workspace B |
| E4 | Sequential: parent env → subagent env → parent reads again | Parent silently reads the subagent's workspace |
| E5 | `model: inherit` with no `--model` → `LLM(model=None)` | `pydantic ValidationError` |
| E6 | Source-diff `subagent.run` vs `runner.run` for the proxy placeholder | Present in `runner`, absent in `subagent` |
| E7 | **Two real subagents, two real Conversations, concurrent, against a local stub OpenAI endpoint** | **`alpha` reported `BRAVO-ONLY-SECRET`.** Sequential baseline correct. 8 stub completions served. |
| E8 | `protect()` then `rt.register_all()`, inspect `_MODULE_QUALNAMES` | All three tools flip `seam_c` → `agentctl.runtime.tools` |
| E9 | `litellm.validate_environment` / `get_llm_provider` over 7 model ids | Bare `pool*` → `BadRequestError`; per-provider env vars as tabulated in §2.5 |

E7's stub is ~45 lines of `http.server` returning a canned `tool_calls`
response then a canned final message — the same idea as
`agentctl/control/replay/server.py`, without the fingerprint matching. It is
the right harness for step 2's regression test and for closing **U4**.
