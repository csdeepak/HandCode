---
Title:         Phase 10.1a — Python Harness Survey (Five Seams)
Type:          RESEARCH
Status:        FROZEN
Created:       2026-09-20
Brief:         docs/0037 Phase 10.1 (Python-importable candidates only)
Depends-on:    0005 (method), 0006 (§5 mechanism style), 0008 (seam model), 0013, 0014
Scope-note:    Non-Python candidates named in 0037 (Cline, Roo Code, Goose, OpenCode,
               Crush, Continue, Codex CLI) are out of scope for this part and are
               listed in §4 with the reason.
---

# Phase 10.1a — Python Harness Survey, scored on the five seams

Every claim below is tagged **[V]** VERIFIED, **[I]** INFERRED, or **[U]** UNKNOWN.
Source tier is **T1** (source code / official reference), **T2** (maintainer
statement), **T3** (third party). No T3 source is load-bearing anywhere in this
document. Every version is pinned. Every date is stated.

**Method note.** I did not read about these harnesses. I downloaded the
published artefact for each one, extracted it, and read the code. The incumbent
was read from the copy already installed in this repository's virtualenv
(`.venv/Lib/site-packages/openhands/sdk/`, `openhands_sdk-1.45.0.dist-info`), so
every line number for OpenHands is from the exact build `agentctl` runs against.
Line numbers for challengers are from the wheel or sdist named in §8. Where a
claim could only come from a repository rather than a release artefact, I fetched
it from GitHub at a named commit.

---

## 1. Executive answer

**STAY.** The survey does not find a better harness; it finds that the property
`agentctl` was built around is rarer than the brief assumes, and the incumbent is
the only Python candidate that has it. OpenHands SDK is the **only** harness of
the eleven examined that makes a tool action durable *before* it executes
(`EventLog.append` → `atomic_write_text` with an explicit `os.fsync` and
`os.replace`, one immutable file per event) **and** re-drives the unmatched
action *through the real executor* on resume (`Agent.step` →
`get_unmatched_actions` → `_execute_actions`) — which is simultaneously the
double-execution bug `docs/0014` reproduced *and* the precise affordance that
makes Seam C's SUBSTITUTE verdict deliverable at all. Every challenger I traced
— LangGraph/LangChain, OpenAI Agents SDK, pydantic-ai, smolagents, SWE-agent,
mini-swe-agent — persists the tool call **after** it returns, or not at all; on
those harnesses a crash mid-effect leaves the harness with no record that the
call was ever made, so resume does not re-drive a matching `tool_call_id` and
Seam C is never asked the question it exists to answer. Moving would not fix the
bug; it would make the bug invisible and downgrade the system to fail-closed-only
— the exact degradation the README calls losing Seam C. Three challengers
(LangChain `wrap_tool_call`, OpenAI Agents `FunctionTool.on_invoke_tool`, Strands
`BeforeToolCallEvent`) genuinely have a *cleaner* Seams B/C than OpenHands and
would delete `handoff.py` outright (112 lines), but that saving is ~110 lines
against 400–700 lines of new, untested durable-journal code plus the loss of a
coding harness the owner does not have to write — and against 502 tests whose
subject would change. The brief's premise that this is an open question is wrong:
the correct move is to spend the pivot budget on the things the incumbent already
ships and `agentctl` does not yet use — `hooks/types.py::HookEventType.PRE_TOOL_USE`
with `DENY`, the Markdown `AgentDefinition` subagent registry, and
`plugin/format/claude_code.py`, which already reads Claude Code plugin manifests.

---

## 2. VERIFIED

Claims I traced to source I could open and re-read.

### V1 — OpenHands SDK writes the action durably, with fsync, before executing it. [T1]

`openhands/sdk/conversation/event_store.py::EventLog.append` (installed 1.45.0,
lines 188–238) takes a cross-process file lock, serialises the event with
`event.model_dump_json(exclude_none=True)`, and writes it to its own file
`self._path(idx, event_id=evt_id)` via the FileStore. `openhands/sdk/io/local.py`
line 63–68 routes that string write to `atomic_write_text`, and
`openhands/sdk/utils/files.py::atomic_write_text` (lines 6–22) does:

```
file.write(value)
file.flush()
os.fsync(file.fileno())
os.replace(temporary_path, path)
```

So an event is fsync'd and atomically renamed into place before `append`
returns. The log is append-only in the strongest sense available on a
filesystem: one new immutable file per event, never rewritten, plus a separate
length marker advanced afterwards (`_advance_length_marker`), which is
deliberately deleted-then-written so "an interrupted update leaves no marker
rather than a stale one claiming to be current" (its own docstring, line ~262).

*No other Python candidate in this survey does this.* See V7–V12.

Permalink: `OpenHands/software-agent-sdk` tag `v1.45.0` = commit
`49ea74587c376b90700f6eff128c3d9b57585d27`, tagged **2026-09-07**.

### V2 — The ordering that produces the double-execution bug is unchanged in 1.45.0. [T1]

`openhands/sdk/agent/response_dispatch.py::_handle_tool_calls` (lines 143–186)
builds every `ActionEvent` via `_get_action_event` — which emits it through
`on_event`, i.e. persists it — and only then calls `self._execute_actions(...)`
at line 184. `openhands/sdk/agent/agent.py::_ActionBatch.prepare` (lines 228–265)
then partitions blocked actions and calls `executor.execute_batch(...)`.
`_ActionBatch.emit` appends the `ObservationEvent` afterwards.

Write-ahead intent, then execute, then write the result. This is exactly what
`docs/0006` V1/V2 recorded, and it still holds in the build installed here.

### V3 — Resume re-drives the unmatched action through the real executor. [T1]

`openhands/sdk/agent/agent.py::Agent.step` lines 646–652:

```python
pending_actions = ConversationState.get_unmatched_actions(state.active_branch())
if pending_actions:
    logger.info("Confirmation mode: Executing %d pending action(s)", len(pending_actions))
    self._execute_actions(conversation, pending_actions, on_event)
    return
```

`ConversationState.get_unmatched_actions` (`conversation/state.py` lines 677–716)
pairs `ActionEvent` against `ObservationEvent`/`UserRejectObservation` by
`action_id` and against `AgentErrorEvent` by `tool_call_id`, returning the
orphans in chronological order. Nothing in that function knows whether the side
effect landed. Confirmed unchanged at **v1.49.2** (see V6).

### V4 — Seam B's blocking mechanism is real and is consumed before execution. [T1]

`conversation/state.py::ConversationState.block_action` (line 650) records
`{action_id: reason}` into `self.blocked_actions`, which is a persisted state
field. `agent/agent.py::_ActionBatch.prepare` line 246 calls
`state.pop_blocked_action(ae.id)` for every action **before** building the
`executable` list, and `_ActionBatch.emit` turns each blocked action into a
`UserRejectObservation(rejection_source="hook")`. So a callback that calls
`block_action` during the `ActionEvent` callback prevents execution, and the
agent receives a well-formed rejection rather than a dangling tool call. This is
precisely what `agentctl/adapters/openhands/seam_b.py::SeamB._decide` relies on.

### V5 — Seam C's substitution mechanism is a plain mutable field. [T1]

`openhands/sdk/tool` exposes `ToolDefinition` with an `executor` field;
`agentctl/adapters/openhands/seam_c.py::gate_tools` replaces it with
`t.model_copy(update={"executor": GatedExecutor(...)})`. `GatedExecutor.__call__`
may return an observation without ever calling `self._inner`. Verified by the
adapter's own working code plus `ToolExecutor` being importable from
`openhands.sdk.tool`.

**The cost of this seam in OpenHands is `handoff.py` (112 lines).**
`ToolExecutor.__call__(action, conversation)` receives only the `Action`, and
`Action` carries no `tool_call_id` — that lives on the `ActionEvent`, which only
Seam B sees. The mailbox, the id-identity keying, the strong reference that stops
CPython recycling an address, and the fingerprint fallback all exist to bridge
that gap. Three challengers do not have this gap (V13, V15, V17). This is the
single place where the incumbent is genuinely worse than the field.

### V6 — The incumbent's seam contract is stable across releases. [T1]

At tag `v1.49.2` (four minor releases and 13 days after the pinned 1.45.0),
`conversation/state.py` still defines `block_action` at line 650 and
`get_unmatched_actions` at line 677 — identical line numbers — and
`agent/agent.py` still calls `get_unmatched_actions` then
`self._execute_actions(conversation, pending_actions, on_event)` at lines
654/660. Fetched from GitHub at `?ref=v1.49.2` on 2026-09-20.

A port's headline risk is that the adapter breaks under the harness. The
incumbent has not moved these symbols in a month of active development.

### V7 — LangGraph persists a task's writes *after* the task returns, and checkpoints *after* the superstep. [T1]

`langgraph` **1.2.11** (wheel, `langgraph-1.2.11-py3-none-any.whl`).
`langgraph/pregel/_loop.py::PregelLoop.tick` (lines 599–681) computes the
superstep's tasks **in memory** via `prepare_next_tasks(...)` and persists
nothing about them. `PregelLoop.after_tick` (lines 682–723) applies the writes
and only then calls `self._put_checkpoint({"source": "loop"})` — the comment in
the source is literally `# save checkpoint`, after `# all tasks have finished`.
`PregelLoop.put_writes(task_id, writes)` (line 415) is called with the writes a
task **produced**.

There is therefore no durable record that a tool is about to run. A crash between
"bash executed `git commit`" and "the ToolMessage was written" leaves the
checkpoint store with nothing at all about that call.

`durability` is `Literal["sync","async","exit"]` (`langgraph/types.py` line 89),
documented at `pregel/main.py` lines 2705–2711 as *"persisted synchronously
before the next step starts"* — the next **step**, not before the side effect.
Default is `"async"`.

### V8 — OpenAI Agents SDK persists the turn's items after the tools have run. [T1]

`openai-agents` **0.22.3** (wheel).
`agents/run_internal/agent_runner_helpers.py` lines 555–584, docstring *"Persist
turn items when persistence is enabled and guardrails allow it"*, calls
`save_result_to_session(session, [], list(items), run_state, ...)` where `items`
is the turn's `new_step_items` — which contains the `ToolCallItem` **and** the
`ToolCallOutputItem` together. The only thing persisted before the model call is
the user input (`agents/run.py` lines 952–966). `SQLiteSession.add_items` is at
`agents/memory/sqlite_session.py` line 338.

Additional finding: in `agents/run.py` line 954 the persistence branch is guarded
by `and not sandbox_runtime.enabled` — **session persistence is skipped entirely
when the sandbox runtime is on.**

### V9 — SWE-agent rewrites the whole trajectory file, after the action executed. [T1]

`SWE-agent/SWE-agent`, commit `3ea751c0`, last commit **2026-07-16**.
`sweagent/agent/agents.py::DefaultAgent.save_trajectory` (line 779):

```python
data = self.get_trajectory_data()
self.traj_path.write_text(json.dumps(data, indent=2))
```

A truncating full-file rewrite. Not append-only, not atomic, no fsync. It is
called from `DefaultAgent.step` → `add_step_to_trajectory` → the run loop's
`save_trajectory(choose=False)` at line 415/427, i.e. after
`handle_action` has already called `self._env.communicate(input=run_action, ...)`
at line 962.

Blocking exists but is static: `DefaultAgent.handle_action` line 947 does
`if self.tools.should_block_action(step.action): raise _BlockedActionError()` —
a config regex blocklist, not a callback that could consult a ledger. The hook
interface `sweagent/agent/hooks/abstract.py::AbstractAgentHook` has
`on_action_started(step)` firing before execution, but **every hook method
returns `None`**; there is no refusal channel.

### V10 — mini-swe-agent does a truncating rewrite after every step. [T1]

`mini-swe-agent` **2.4.6** (wheel).
`minisweagent/agents/default.py::DefaultAgent.save` (lines 183–190) is
`path.write_text(json.dumps(data, indent=2))`, called from the `finally:` block
of the `run()` loop at line 119 — after `self.step()` has already executed the
action via `execute_actions` (line 154: `self.env.execute(action)`). No
`tool_call_id`, no resume path, no append-only log. The whole agent is 190 lines.

### V11 — smolagents has no persistence and no pre-tool refusal. [T1]

`smolagents` **1.26.0** (wheel).
`smolagents/agents.py::MultiStepAgent._setup_step_callbacks` (line 416) registers
callbacks on `ActionStep`, and they are invoked at line 623 —
`self.step_callbacks.callback(memory_step, agent=self)` — i.e. after the step.
No pre-tool callback with a refusal return. `from_dict`/`from_folder` (lines
1011, 1119) restore an *agent configuration*, not mid-run state: there is no
resume-with-pending-actions path. `MultiStepAgent.execute_tool_call` (line 1453)
is subclassable, which is a Seam C by inheritance, but there is nothing to
substitute *from*.

### V12 — pydantic-ai ships no persistence of its own. [T1]

`pydantic-ai-slim` **2.46.0** (wheel). There is no event store, no session
table, no checkpoint. `agent.run()` returns `AgentRunResult`; the caller persists
`all_messages()`. The only durability story is `pydantic_ai/durable_exec/`
with `temporal/`, `dbos/` and `prefect/` backends — i.e. durability is delegated
to an external workflow engine.

### V13 — pydantic-ai has the cleanest single-seam block *and* substitute. [T1]

`pydantic_ai/toolsets/wrapper.py::WrapperToolset.call_tool(name, tool_args, ctx, tool)`
(lines 66–70) delegates to `self.wrapped.call_tool(...)`. A subclass may return a
value **without** delegating — that is SUBSTITUTE — or raise — that is BLOCK.
`ctx` is a `RunContext` whose `tool_call_id` field is declared at
`pydantic_ai/_run_context.py` line 174. **Identity is present at the executor.**

The in-tree proof that refusal works this way is
`pydantic_ai/toolsets/approval_required.py::ApprovalRequiredToolset.call_tool`
(lines 26–31), which raises `ApprovalRequired` before `super().call_tool(...)`.

### V14 — LangChain v1 middleware can return a tool result without executing the tool. [T1]

`langchain` **1.4.2** (wheel).
`langchain/agents/middleware/types.py::AgentMiddleware.wrap_tool_call(self, request, handler) -> ToolMessage | Command`
(line 674). The docstring is explicit that `handler` "can be called multiple
times" — and, by omission, zero times.

The shipped proof is
`langchain/agents/middleware/tool_emulator.py::LLMToolEmulator.wrap_tool_call`
(line 145): when `should_emulate` it builds a `ToolMessage` from an LLM and
**never calls `handler`**. That is Seam C, in tree, in a released package.
`request.tool_call["name"]`/`["args"]`/`["id"]` are all present, so identity is at
the seam. The agent-loop import path is `langchain.agents.factory::create_agent`
(line 772); the older `langgraph.prebuilt.chat_agent_executor::create_react_agent`
(langgraph-prebuilt 1.1.0, line 278) still exists.

### V15 — OpenAI Agents SDK has a first-class pre-tool refusal that returns a message. [T1]

`agents/tool_guardrails.py::ToolGuardrailFunctionOutput.reject_content(message, ...)`
(line 92), docstring: *"Message to send to the model instead of the tool result."*
Behaviours are `AllowBehavior` / `RejectContentBehavior` / `RaiseExceptionBehavior`
(line 69). `ToolInputGuardrailData.context` is a `ToolContext` (line 124) which
carries `tool_call_id`.

Seam C is separately available: `agents/tool.py` line 468 declares
`on_invoke_tool: Callable[[ToolContext[Any], str], Awaitable[Any]]` as an ordinary
dataclass field — wrappable exactly like `ToolDefinition.executor`, but with
`tool_call_id` in hand. `RunHooks.on_tool_start` (`agents/lifecycle.py` line 70)
returns `None` and cannot refuse; the guardrail is the refusal channel.

### V16 — Claude Agent SDK is not an in-process loop and cannot substitute for built-in tools. [T1]

`claude-agent-sdk` **0.2.157** (sdist).
`src/claude_agent_sdk/_internal/transport/subprocess_cli.py::SubprocessCLITransport._find_cli`
(line 248) searches for a `claude` executable (`shutil.which("claude")`,
`~/.local/bin/claude.exe`, `~/.npm-global/bin/claude`, …) and spawns it. The agent
loop runs in that binary, out of the owner's process, over stdio JSON.

Seam B exists and is good: `CanUseTool = Callable[[str, dict, ToolPermissionContext], Awaitable[PermissionResult]]`
(`src/claude_agent_sdk/types.py` line 278) with `PermissionResultDeny(message=..., interrupt=...)`
(line 268). `PreToolUse` is also a `HookEvent` (line 285).

Seam C does **not** exist for built-in tools: `PermissionResultAllow` carries
`updated_input` and `updated_permissions` (line 259) — you may rewrite the call,
you may not return a result instead of it. Substitution is possible only for
tools you define yourself through `create_sdk_mcp_server` (`__init__.py` line
491), i.e. never for Bash/Edit/Read, which is where the effects are.

Model config is per-conversation but process-scoped:
`ClaudeAgentOptions.env: dict[str, str]` (`types.py` line 2109) is merged into the
child process environment (`subprocess_cli.py` lines 812–841), so
`ANTHROPIC_BASE_URL` can differ per query. The wire protocol is Anthropic
`/v1/messages`, not OpenAI-compatible — which is the path the README already
flags as untested.

### V17 — Strands has a writable pre-tool event that can both cancel and swap the tool. [T1]

`strands-agents` **1.56.0** (wheel).
`strands/hooks/events.py::BeforeToolCallEvent` (line 208) declares
`selected_tool`, `tool_use`, `invocation_state`, `cancel_tool`, and
`_can_write` returns `name in ["cancel_tool", "selected_tool", "tool_use"]`
(line 231). Setting `cancel_tool` to a string cancels the call and places that
message into a tool result with error status — Seam B. Replacing `selected_tool`
with a stub that returns the recorded observation — Seam C. `tool_use['toolUseId']`
is right there (used at line 243 to build the interrupt id).

Strands is the closest structural match to OpenHands: it has session managers
(`strands/session/file_session_manager.py`, `repository_session_manager.py`) and
an explicit pre-tool checkpoint boundary —
`strands/event_loop/event_loop.py` lines 324–340 emit a checkpoint at position
`"after_model"` *before* `_handle_tool_execution` at line 348, and
`strands/experimental/checkpoint/checkpoint.py::Checkpoint.position` is
`after_model | after_tools`.

### V18 — The OpenHands *application* is not a second agent loop. [T1]

`openhands-ai` **1.11.0** (wheel, PyPI, latest as of 2026-09-20). The package
contains 227 Python files across `openhands/app_server/`, `openhands/server/`,
`openhands/db/`, `openhands/analytics/` — a multi-tenant FastAPI service with
Alembic migrations, GitHub/GitLab/Jira/Bitbucket integrations, recaptcha, and a
web client. Its `Requires-Dist` block is decisive:

```
Requires-Dist: fastapi
Requires-Dist: openhands-agent-server (==1.34.0)
Requires-Dist: openhands-sdk (==1.34.0)
Requires-Dist: openhands-tools (==1.34.0)
Requires-Dist: uvicorn
```

It **pins the SDK to an exact version, and that version (1.34.0) is eleven
releases behind the 1.45.0 this repository targets.** Adopting the application
means running a server, adopting a database, and surrendering control of the SDK
version to someone else's pin. There is no agent loop in it to evaluate: it is
the incumbent, wrapped.

### V19 — Aider is dormant and cannot be installed next to this project. [T1]

`Aider-AI/aider`: last push **2026-05-22** (commit `5dc9490b`), 1,880 open
issues, not archived. Four months without a commit.

Independently fatal: pip's own resolver, run in this repository's Python 3.13
virtualenv, refused every modern release and reported the constraint for each —
`0.83.0`…`0.86.2 Requires-Python >=3.10,<3.13`. The newest installable version
on this machine is **0.16.0**, from 2024. `agentctl` requires `>=3.12` and the
OpenHands SDK requires `>=3.12`; Aider caps at `<3.13`. The viable overlap is
Python 3.12 only, on a dormant codebase. **DROP.**

### V20 — SWE-agent is not installable from PyPI at its current version. [T1]

`pip download sweagent` in this venv resolves to **0.0.1** only
(`pip index versions sweagent` → `Available versions: 0.0.1`), whose contents are
the 2024-era `sweagent/agent/agents.py` + `sweagent/environment/swe_env.py`.
SWE-agent 1.x (tag `v1.1.0`) is installed from a git clone. It is importable, but
it is not a dependency you can pin in `pyproject.toml` by name and version.

### V21 — Per-conversation model configuration is a solved problem everywhere. [T1]

This criterion does not discriminate. All of the following accept an arbitrary
OpenAI-compatible `base_url` + key per instance, at runtime, no config file:

| Candidate | Path from config to HTTP request |
|---|---|
| OpenHands SDK 1.45.0 | `LLM(model=..., base_url=..., api_key=SecretStr(...))` (`llm/llm.py` line 220, fields at 257/292) → `LLM._prepare_transport_kwargs` builds `api_base=provider_info.api_base` (line 2205) → `LLM._transport_call` line 2225 `litellm_completion(**kwargs)`. `provider_info.api_base` is the verbatim `base_url`: `llm/utils/litellm_provider.py::LLMProvider.from_model` returns `api_base=api_base` and the comment at lines 27–32 says LiteLLM's own resolved base is *deliberately discarded* so the user's value is not rewritten. |
| LangChain 1.4.2 | `ChatOpenAI(base_url=..., api_key=...)` per instance; `create_agent(model=...)`. |
| OpenAI Agents 0.22.3 | `OpenAIChatCompletionsModel(model, openai_client=AsyncOpenAI(base_url=..., api_key=...))` (`agents/models/openai_chatcompletions.py` line 60) or `RunConfig(model=..., model_provider=...)` per run (`agents/run_config.py` lines 353–359). |
| pydantic-ai 2.46.0 | `OpenAIProvider(base_url=..., api_key=...)` (`providers/openai.py` lines 77–122) and a per-call override: `agent.run(..., model=<Model>)` (`agent/abstract.py` line 422). |
| smolagents 1.26.0 | `LiteLLMModel(model_id=..., api_base=..., api_key=...)` (`models.py` lines 1227–1241). |
| Strands 1.56.0 | per-model-provider constructors; OpenAI-compatible provider present. |
| mini-swe-agent 2.4.6 | `minisweagent/models/litellm_model.py`, `openrouter_model.py` — LiteLLM under the hood. |
| Claude Agent SDK 0.2.157 | `ClaudeAgentOptions.env` per query (V16) — but Anthropic wire format, not OpenAI-compatible. |

**The existing LiteLLM proxy plugs into every one of these with zero code except
the Claude Agent SDK.** This seam should carry no weight in the decision.

### V22 — Last-commit dates. Nothing here except Aider is abandoned. [T1]

Queried via GitHub API on **2026-09-20**:

| Repo | Last commit | SHA |
|---|---|---|
| openai/openai-agents-python | 2026-09-20 | `f23da767` |
| anthropics/claude-agent-sdk-python | 2026-09-20 | `f7547d72` |
| langchain-ai/langchain | 2026-09-19 | `68754c23` |
| OpenHands/software-agent-sdk | 2026-09-19 | `bd5fff06` |
| pydantic/pydantic-ai | 2026-09-19 | `c4898abb` |
| langchain-ai/langgraph | 2026-09-18 | `aa742fb3` |
| OpenHands/OpenHands | 2026-09-18 | `a0736482` |
| strands-agents/sdk-python | 2026-09-18 | `54ca0bef` |
| SWE-agent/mini-swe-agent | 2026-09-03 | `04d809ce` |
| huggingface/smolagents | 2026-08-22 | `30bb1161` |
| SWE-agent/SWE-agent | 2026-07-16 | `3ea751c0` |
| **Aider-AI/aider** | **2026-05-22** | `5dc9490b` |

### V23 — The incumbent already ships most of what the pivot is asking for. [T1]

Read from the installed 1.45.0 tree:

- **Claude-Code-compatible hooks with a deny channel.**
  `openhands/sdk/hooks/types.py::HookEventType.PRE_TOOL_USE = "PreToolUse"`,
  `POST_TOOL_USE = "PostToolUse"`, and a permission decision enum containing
  `DENY = "deny"` (line 39). `agentctl` does not currently use this at all; it
  uses the event callback + `block_action`. **There is a second Seam B already in
  the box.**
- **Subagents.** `openhands/sdk/subagent/{schema,registry,load}.py`. Agents are
  Markdown files with frontmatter (`name`, `description`, `model`, `tools`,
  `skills`, `max_budget_per_run`, `hooks`, `mcp_servers`, `permission_mode`,
  `condenser`), discovered at project/user/builtin/plugin scope via
  `register_file_agents(work_dir)` (registry.py line 288).
- **Claude Code plugin format.**
  `openhands/sdk/plugin/format/claude_code.py::ClaudeCodePluginFormat` —
  `load_manifest`, `load_mcp_config`, `load_hooks`, `load_agents`,
  `load_commands`. It reads Claude Code's own plugin layout.
- **Routing.** `openhands/sdk/llm/router/` with `base.py` and `impl/`.
- Plus `skills/`, `mcp/`, `context/` condensers, `security/`, `critic/`,
  `marketplace/`, `profiles/`, `credential.py`.

The ask in `docs/0037` — *"a harness that looks like Claude Code, runs on many
APIs, supports multi-agent"* — describes the incumbent.

### V24 — pydantic-ai's DBOS durability memoizes *completed* steps. It does not journal a step before it runs. [T1]

`pydantic_ai/durable_exec/dbos/_operation_backend.py` wraps every I/O operation
as `DBOS.step(name=name, **step_config)(operation_step)` (lines 126–131, and the
same pattern at 139–300 for capability, model, cancel, compact, event, discovery,
MCP-call and dynamic-call operations). Durability is therefore DBOS step
semantics, and pydantic-ai states those semantics in its own shipped docstring —
`durable_exec/dbos/_utils.py::guard_enqueue_in_workflow`, lines 20–22:

> "Recovery replays a step's **recorded output** without re-executing the tool,
> so in-step enqueued messages would be silently dropped."

So a step that **completed** is not re-executed on recovery. That is a real
property — and it is the same property OpenHands already has, by matching an
`ObservationEvent` to its `ActionEvent` [V3].

It is not the property `agentctl` exists for. The window that matters is a crash
**inside** the step, after the side effect and before the output is checkpointed.
For that case the configuration surface says what happens:
`durable_exec/dbos/_utils.py::StepConfig` (lines 8–14) exposes
`retries_allowed`, `interval_seconds`, `max_attempts`, `backoff_rate` — an
incomplete step is **retried from the beginning**. Identical double-execution
window to the incumbent's, relocated, with no ledger to detect it, and requiring
a DBOS runtime (Postgres) that the standing constraint rules out on its own.

**U5 is closed. The verdict is unchanged.**

---

## 3. INFERRED

### I1 — Moving to a write-after-result harness makes the double-execution bug worse, not better.

Chain: (a) `agentctl`'s ledger writes its own PENDING record at Seam B before the
tool runs, so write-ahead durability is supplied by the control plane, not the
harness [VERIFIED in this repo, `agentctl/adapters/openhands/seam_b.py::SeamB._decide`].
(b) But SUBSTITUTE can only be
*delivered* if, on resume, the harness asks the executor for that same call
again. (c) OpenHands does exactly that, by `tool_call_id`, deterministically
[V3]. (d) LangGraph re-runs the *node* from a checkpoint taken before the tool
[V7]; OpenAI Agents re-prompts the model from the last saved turn [V8]. In both,
whether the same `tool_call_id` reappears depends on the model resampling the
same call. (e) Therefore on those harnesses the identity match degrades to
`handoff.py`'s fingerprint fallback *as the primary path*, and if the model
simply does not re-emit the call, the recorded observation is never delivered and
the agent silently proceeds without it.

Confidence: high on (a)–(d), medium on the severity of (e). What would settle it:
run the `docs/0014` experiment against a LangGraph `create_agent` with a
`SqliteSaver` and count effects.

### I2 — The `~150 lines per harness` estimate in `docs/0013` §5 is right for the seams and wrong for the port.

The seam code really does compress: on any of pydantic-ai, LangChain or OpenAI
Agents, `handoff.py` (112 lines) disappears entirely because `tool_call_id` is
available where the executor runs [V13, V14, V15], and Seams B and C collapse into
one wrapper of roughly 120–180 lines. So ~150–200 lines is a fair *seam* estimate.

But `docs/0013` §5 was costing an adapter against a harness that already has an
event log. Three of the four best-scoring challengers do not. The delta is not
adapter lines, it is a new durable journal, a resume driver, and a message-history
reconstructor — the `0006`:76 *"BUILD for multi-agent"* verdict arriving early
and for a different reason. §6 prices it.

### I3 — Strands is the only credible PORT target, and it is not credible enough.

It is the one challenger with a pre-tool checkpoint boundary [V17], writable
pre-tool refusal *and* tool substitution at one event with identity in hand, and
first-class session managers. On the five seams alone it scores level with or
slightly above the incumbent.

Against it: the checkpoint module lives under `strands/experimental/`; the
`Checkpoint.position` granularity is `after_model | after_tools`, so a crash
*during* the tool batch resumes at `after_model` and re-drives — the same shape as
OpenHands, with none of the four crash experiments already run against it; the
coding tools are a separate package; the default model provider is Bedrock; and
nothing in this repository has ever been exercised on it. Porting to it trades a
harness with a *known, reproduced, instrumented* failure mode for one with an
*unknown* failure mode of the same family.

### I4 — The Claude Agent SDK is the right answer to a question the brief did not ask.

It is the only candidate that is literally Claude Code. But it cannot substitute
for Bash/Edit/Read [V16], so adopting it as the loop deletes Seam C, which the
README names as the difference between "fails closed" and "resumes cleanly". It
is, however, a plausible *front end* — a client that drives an `agentctl`-managed
OpenHands conversation — and that is worth a Phase 10.3 note, not a pivot.

### I5 — "Free tier, student budget, Windows dev box" eliminates the container-native candidates on operating cost, independently of the seams.

SWE-agent requires SWE-ReX + Docker; the OpenAI Agents SDK's coding path is a
Docker sandbox whose enablement *disables session persistence* [V8]; the
OpenHands application wants Postgres/Alembic and a server [V18]. On a Windows 11
box that means Docker Desktop running beside the dev loop, and on Linux CI it
means image pulls in every job. The incumbent's `execute_bash` runs on the host —
the README already lists "no sandbox" as its first limitation — which is a
security cost the project has consciously accepted and priced with the 75-command
capability matrix. Reversing that decision is a separate project.

---

## 4. UNKNOWN

- **U1 — Whether LangGraph's `durability="sync"` plus a custom tool node could
  be made write-ahead.** `put_writes` takes writes a task produced [V7], but I
  did not trace whether a node may emit a write *mid-execution* that the
  checkpointer persists before the node returns. *Resolves by:* writing a node
  that calls `get_stream_writer()`/`Command(update=...)` before its side effect
  against `SqliteSaver`, killing the process, and reading the checkpoint table.
- **U2 — Whether the OpenAI Agents SDK's `RunState.to_json`/`from_json`
  (`agents/run_state.py` lines 1784, 2266) re-drives an interrupted tool call
  through `on_invoke_tool` on resume.** The class exists and is clearly built for
  human-in-the-loop approval resume; whether crash-resume re-enters the executor
  for an already-started call I could not establish by reading.
  *Resolves by:* the `docs/0014` experiment with a `SQLiteSession` and a
  `RunState` round-trip.
- **U3 — Strands' `PendingToolExecution.completed_tool_results`
  (`event_loop.py` lines 782, 840–842) looks like a partial effect ledger** — it
  carries already-finished results across an interrupt so a parallel batch is not
  re-run. Whether that structure is *durable* across a process kill, or only
  survives an in-process interrupt, I could not determine.
  *Resolves by:* serialising `agent._interrupt_state` to a session store, `kill -9`,
  restore, and counting effects.
- **U4 — Whether the `claude` binary's own `~/.claude/projects/**/*.jsonl`
  transcript is append-only and fsync'd.** The loop is in a compiled/Node binary,
  so it is not readable from the Python SDK. *Resolves by:* strace/Process Monitor
  during a tool call, or a maintainer statement (T2).
- **~~U5 — pydantic-ai's DBOS backend.~~ RESOLVED during this survey — see V24.
  It does not change the verdict.**
- **U6 — Whether any of these harnesses' seams survive contact with a real
  free-tier provider.** `docs/0023` records that the first real OpenRouter run
  found two bugs that reading could not. Every challenger score here is a
  reading-derived score. That asymmetry favours the incumbent, which has been run.

---

## 5. Mechanism explanation — how the top candidate actually works

*Top candidate is the incumbent. This section is written to the standard of
`docs/0006` §5: data structures and failure modes, at implementer level. The
first part restates 1.45.0-verified internals; the second is new and is the part
that matters for the decision.*

### 5.1 The event log is a directory of fsync'd immutable files

`EventLog` is not a table and not a JSONL stream. It is a directory in which each
event is one file, named `event-<zero-padded-index>-<event-id>.json`, plus a
zero-byte **length marker** whose filename encodes the current count.

`EventLog.append(event)` (event_store.py:188):

1. Acquire a cross-process FileStore lock with `LOCK_TIMEOUT_SECONDS`.
2. If the marker for `self._length` does not exist, another writer may have
   appended — count the files on disk and `_sync_from_disk`. The marker is an
   optimisation whose *false* answer is never trusted ("`False` is not proof of
   divergence").
3. Reject a duplicate `event.id`; reject an event whose `parent_id` is not
   already in `_id_to_idx`. **The log enforces its own DAG integrity on write.**
4. `payload = event.model_dump_json(exclude_none=True)`, then
   `self._fs.write(target_path, payload)` → `atomic_write_text` →
   `write`/`flush`/`os.fsync`/`os.replace`.
5. Update three in-memory indices (`_idx_to_id`, `_id_to_idx`, `_event_cache`),
   increment `_length`, then `_advance_length_marker(idx)`, which **deletes the
   old marker before writing the new one** so an interrupted marker update leaves
   *no* marker rather than a lying one.

Failure modes, precisely:

- **Kill between step 4 and step 5.** The event file is on disk and durable; the
  in-memory indices and the marker are stale. On restart the directory is
  re-scanned, the event is found, the marker is rebuilt. **No loss.**
- **Kill during step 4.** `os.replace` is atomic on both NTFS and POSIX, so the
  reader sees either the old state or the complete new file. A `.event-…` temp
  file may be orphaned. **No torn event.**
- **Kill during step 5's marker delete-then-write.** No marker exists; the next
  `append` falls back to `_count_events_on_disk`. **Costs a directory scan, not
  correctness.**

This is a better durability story than any challenger in the survey [V7–V12], and
it is the foundation the ledger's SUBSTITUTE verdict sits on.

### 5.2 The step, in order, with the crash window named

`ConversationState.append_event` (state.py:315) is the single chokepoint. It
stamps `parent_id` from the active leaf (or `ROOT_PARENT_ID` for a deliberate new
root), appends, and advances `leaf_event_id`. That last assignment is what makes
`fork` and `navigate_to` coherent: HEAD is a pointer into a DAG, and
`state.view` is a lazily-maintained `path_to_root(leaf)` that replays only the new
tail on a linear append (O(k)) and rebuilds fully on a branch switch (O(n)).

One turn, in execution order:

```
Agent.step
  └─ prepare_llm_messages(state.view) ─► LLM._transport_call ─► litellm.completion
  └─ response_dispatch::_handle_tool_calls(message, …)
       ├─ for each tool_call: _get_action_event(...)   ← builds ActionEvent
       │    └─ on_event(action_event)                   ← ██ DURABLE HERE ██
       │         └─ LocalConversation._default_callback ─► state.append_event ─► fsync
       │         └─ ...and every registered callback, including SeamB.__call__
       ├─ if _requires_user_confirmation(...): return   ← pause with intent durable
       └─ _execute_actions(conversation, action_events, on_event)
            └─ _ActionBatch.prepare
                 ├─ _truncate_at_finish
                 ├─ for ae: state.pop_blocked_action(ae.id)  ← ██ SEAM B LANDS HERE ██
                 │     blocked → blocked_reasons; else → executable
                 ├─ executor.execute_batch(executable, tool_runner, …)
                 │     └─ tool.executor(action, conversation)  ← ██ SEAM C ██
                 │          ██ THE CRASH WINDOW: side effect happens inside here ██
                 └─ results_by_id = zip(executable ids, results)
            └─ _ActionBatch.emit   ← ObservationEvent / UserRejectObservation appended
            └─ _ActionBatch.finalize
```

The crash window is the body of `executor.execute_batch`. If the process dies
there, the log holds an `ActionEvent` with no sibling `ObservationEvent`.

### 5.3 Why the bug and the fix are the same mechanism

On restart, `Agent.step` line 646 runs *before anything else*:

```python
pending_actions = ConversationState.get_unmatched_actions(state.active_branch())
if pending_actions:
    self._execute_actions(conversation, pending_actions, on_event)
    return
```

`get_unmatched_actions` walks the branch in reverse, collecting
`observed_action_ids` from `ObservationEvent`/`UserRejectObservation` and
`observed_tool_call_ids` from `AgentErrorEvent` (which lacks `action_id`, so it is
matched on `tool_call_id` — a detail the docstring says exists specifically "for
crash recovery scenarios where an error event is emitted after a server restart").
Anything left over is re-driven.

Naively this is the bug: `git commit` runs twice. `docs/0014` measured it —
1 effect before the crash, 2 after.

But look at what it gives you. The re-drive is **deterministic**, keyed on
`tool_call_id`, and it goes **through the executor**. That means:

1. Seam B's callback fires again on the re-driven `ActionEvent`, with the same
   `tool_call_id`, so the gate can look the call up in the ledger and find
   `COMMITTED`.
2. The gate returns SUBSTITUTE. `SeamB._decide` puts the recorded observation
   into the handoff mailbox and *lets the harness proceed*.
3. `_ActionBatch.prepare` calls the executor. `GatedExecutor.__call__` claims the
   mailbox entry and returns `observation_type.model_validate_json(raw)` —
   the exact observation that was recorded — without touching `self._inner`.
4. `_ActionBatch.emit` appends a perfectly ordinary `ObservationEvent`. The
   orphan is now matched. The message history the model sees is intact: every
   `tool_call` has its `tool_result`. The loop continues as though the crash
   never happened.

**The re-drive is not a bug to be routed around. It is the delivery mechanism.**
A harness that did *not* re-drive would give the gate nowhere to hand the answer
back, and `agentctl` would be stuck blocking — which is the M2a behaviour the
README describes as "still correct, just a rejection where a result was possible."

### 5.4 The one place the incumbent is genuinely worse, and what it costs

`ToolExecutor.__call__(action, conversation)` gets the `Action`, and `Action`
carries no identity. `tool_call_id` lives on the `ActionEvent`, which Seam B sees
and Seam C does not. That gap is why `handoff.py` exists and why it is 112 lines
rather than 12:

- The mailbox is keyed on `id(action)`, because the harness passes the *same
  object* the event carried.
- It holds a **strong reference to the action**, because `id()` is unique only
  among live objects; CPython recycles addresses, and CI on 3.12 caught exactly
  that — an entry keyed on a dead action's address being claimed by an unrelated
  action allocated there (`docs/0028`). 3.13's allocator happened not to recycle,
  which is why it only failed on one runner.
- On read it re-checks `entry[0] is action` (identity, not equality) so a
  recycled address reads as a miss.
- A content fingerprint (`sha256` over canonical `{tool, args}`) is the fallback,
  so a mismatch degrades to a *missed substitution* rather than a *wrong* one.
- Entries are one-shot, so a genuinely repeated call is not short-circuited twice.

In pydantic-ai [V13], LangChain [V14], OpenAI Agents [V15] and Strands [V17],
`tool_call_id` is present at the executor and **all 112 lines of that go away**.
That is the strongest single argument for porting, and it is worth naming
precisely: ~110 lines of subtle, CI-discovered, allocator-dependent code deleted.
§6 weighs it against what replaces it.

### 5.5 What a porter must rebuild, by harness class

Two classes of challenger, two different bills:

**Class A — has an event log, different ordering (LangGraph, OpenAI Agents,
Strands).** The adapter shrinks. But the resume contract changes from
"deterministic re-drive by `tool_call_id`" to "the model may or may not re-emit
the call." `agentctl` must then own reconciliation: after a crash, read the
ledger's PENDING/COMMITTED rows, decide what the harness's restored history is
missing, and *synthesise* the tool-result message into the history before the
next model call — because there is no re-drive to intercept. That is not adapter
code. That is a message-history surgeon, per harness, per provider schema.

**Class B — has no event log at all (pydantic-ai, smolagents).** Everything in
5.1 must be built: append-only storage with fsync, a parent/leaf DAG or at least
a linear sequence, duplicate-id rejection, a resume loader, and the unmatched-
action query. This is `0006`:76's `BUILD for multi-agent` verdict, arriving now,
for single-agent work, as a prerequisite rather than a feature.

---

## 6. Scoring table

**Key.** ✔✔ = present and clean · ✔ = present with a caveat · ~ = possible only
by subclassing/rebuilding · ✘ = absent.
Seam C is weighted highest, per the brief.

| Harness (version, last commit) | 1. Library? Import path that starts a loop | 2. Per-conversation `base_url`+key | 3. **Seam B** — pre-tool refusal | 4. **Seam C** — substitute (highest weight) | 5. Persistence ordering |
|---|---|---|---|---|---|
| **OpenHands SDK 1.45.0** (2026-09-19) | ✔✔ `openhands.sdk::Conversation`, `Agent.step`. Pure library, no server, no container required | ✔✔ `LLM(base_url=…, api_key=…)` → `api_base` → `litellm.completion` [V21] | ✔✔ `ConversationState.block_action` consumed in `_ActionBatch.prepare` **before** `execute_batch` [V4]. Plus unused second channel: `HookEventType.PRE_TOOL_USE` + `DENY` [V23] | ✔✔ `ToolDefinition.executor` replaced; returns recorded observation without calling inner [V5]. **Costs 112 lines of handoff** — no `tool_call_id` at the executor [5.4] | ✔✔ **Append-only, one fsync'd immutable file per event, durable BEFORE execution** [V1,V2]. Resume **does** re-drive unmatched actions [V3] — the bug *and* the delivery mechanism [5.3] |
| **OpenHands application 1.11.0** (2026-09-18) | ✘ FastAPI + Alembic + web client; **pins `openhands-sdk==1.34.0`** [V18] | (inherits SDK) | (inherits SDK) | (inherits SDK) | (inherits SDK, minus version control) |
| **Strands Agents 1.56.0** (2026-09-18) | ✔✔ `strands::Agent(...)` | ✔✔ per-provider constructors | ✔✔ `BeforeToolCallEvent.cancel_tool` (writable) [V17] | ✔✔ swap `selected_tool`; `tool_use['toolUseId']` at the seam — **no handoff needed** | ✔ Session managers + pre-tool checkpoint at `"after_model"` [V17], but `Checkpoint` is `experimental/`; resume-during-batch semantics **U3** |
| **LangGraph 1.2.11 / LangChain 1.4.2** (2026-09-18/19) | ✔ `langchain.agents.factory::create_agent`; `langgraph.prebuilt…::create_react_agent`. Library, but a *chat* agent — coding tools, condenser, subagents not included | ✔✔ `ChatOpenAI(base_url=…)` | ✔✔ `AgentMiddleware.wrap_tool_call` → return a `ToolMessage` [V14] | ✔✔ **Proven in tree**: `LLMToolEmulator.wrap_tool_call` returns without calling `handler` [V14]. `request.tool_call["id"]` present | ✘ **Write-after-result.** `put_writes` takes what a task produced; `_put_checkpoint` runs in `after_tick` [V7]. No durable pre-tool intent. **U1** |
| **OpenAI Agents SDK 0.22.3** (2026-09-20) | ✔✔ `agents::Runner.run` | ✔✔ `RunConfig(model=…)`, `AsyncOpenAI(base_url=…)` [V21] | ✔✔ `ToolGuardrailFunctionOutput.reject_content(message)` [V15] | ✔✔ wrap `FunctionTool.on_invoke_tool`; `ToolContext.tool_call_id` present — **no handoff needed** | ✘ Turn items (call + output together) saved after execution [V8]. **Persistence is skipped when the sandbox is enabled** [V8]. **U2** |
| **pydantic-ai 2.46.0** (2026-09-19) | ✔✔ `pydantic_ai::Agent.run` | ✔✔ `OpenAIProvider(base_url=…)`, plus `agent.run(model=…)` per call [V21] | ✔✔ raise from `WrapperToolset.call_tool`; `ApprovalRequiredToolset` in tree [V13] | ✔✔ **Cleanest in the survey** — return from `WrapperToolset.call_tool` without delegating; `ctx.tool_call_id` present [V13] | ✘ **None.** Caller persists `all_messages()`. Durability only via Temporal/DBOS/Prefect [V12] — and DBOS memoizes a *completed* step, retrying an incomplete one from the start [V24] |
| **Claude Agent SDK 0.2.157** (2026-09-20) | ✘ Spawns the `claude` binary over stdio [V16]; the loop is not in your process | ✔ `ClaudeAgentOptions.env` per query — but **Anthropic `/v1/messages`**, not OpenAI-compatible [V16] | ✔✔ `can_use_tool` → `PermissionResultDeny(message=…)`; `PreToolUse` hook [V16] | ✘ **`PermissionResultAllow` carries `updated_input` only — no way to return a result instead** [V16]. Possible only for your own `create_sdk_mcp_server` tools, never Bash/Edit/Read | **U4** — transcript written by the binary, unreadable from Python |
| **smolagents 1.26.0** (2026-08-22) | ✔✔ `smolagents::CodeAgent/ToolCallingAgent.run` | ✔✔ `LiteLLMModel(api_base=…)` | ✘ `step_callbacks` fire on `ActionStep` *after* the step [V11] | ~ subclass `MultiStepAgent.execute_tool_call` [V11] | ✘ **No persistence, no resume.** `from_dict`/`from_folder` restore config, not state [V11] |
| **SWE-agent v1.1.0** (2026-07-16) | ~ Importable (`sweagent.agent.agents::DefaultAgent.run`) but **not installable from PyPI at current version** [V20]; requires SWE-ReX + Docker | ✔ LiteLLM-backed | ✘ Hooks all return `None`; only a static regex blocklist [V9] | ~ subclass `DefaultAgent.handle_action` | ✘ **Truncating full-file JSON rewrite, after execution** [V9] |
| **mini-swe-agent 2.4.6** (2026-09-03) | ✔✔ `minisweagent.agents.default::DefaultAgent.run` (190 lines) | ✔✔ LiteLLM | ~ override `step`/`execute_actions` (documented as the extension point) | ~ same | ✘ **`path.write_text(json.dumps(...))` after each step** [V10]. No `tool_call_id`, no resume |
| **Aider ≤0.86.2** (**2026-05-22**) | ✘ `Coder` is coupled to terminal I/O; no tool-call seam | ✔ LiteLLM | ✘ | ✘ | ✘ |

### 6.1 Dropped without scoring

**Non-Python** (named in `docs/0037`, out of scope for this part, listed so the
next part does not re-litigate): Cline (TypeScript, VS Code extension), Roo Code
(TypeScript fork of Cline), Goose (Rust), OpenCode (TypeScript), Crush (Go),
Continue (TypeScript), Codex CLI (Rust). None is importable into a Python process;
each would be a subprocess/IPC integration, which is the Claude Agent SDK's
position [V16] with less mature protocol support.

**Abandoned:** Aider (2026-05-22, plus a hard `python<3.13` cap [V19]).

**Considered and not worth a row:** CrewAI, AutoGen/AG2, Agno, Google ADK — all
are multi-agent *orchestration* frameworks whose unit of composition is the agent,
not the tool call; none persists a tool call before executing it, and all of them
inherit whatever loop their underlying model client provides. Adding them would
lengthen the table without moving the verdict.

### 6.2 Port cost, measured against the existing 688 lines

Existing: `__init__.py` 137 · `handoff.py` 112 · `seam_b.py` 236 · `seam_c.py` 203.

| Target | Adapter lines | vs 688 | New non-adapter code required | Honest total |
|---|---|---|---|---|
| **Stay (OpenHands)** | 688 (unchanged) | — | 0 | **0 lines, 0 tests invalidated** |
| **pydantic-ai** | ~180 (one `WrapperToolset`; `handoff.py` deleted; `__init__` wiring ~90) | **−508** | Everything in §5.1: append-only fsync'd store, sequence/DAG, duplicate-id rejection, resume loader, `get_unmatched_actions` equivalent, message-history reconstruction. **450–700** | **~630–880 lines**, of which the new half has zero test coverage |
| **LangChain / LangGraph** | ~200 (one `AgentMiddleware`; `handoff.py` deleted) | **−488** | Write-ahead intent layer (checkpointer writes after the task), plus the §5.5 Class-A history surgeon because resume does not re-drive. **300–500**. Plus a coding-tool suite, condenser and subagent story the SDK gives free. | **~500–700 lines** + rebuilding the harness itself |
| **OpenAI Agents SDK** | ~170 (`ToolInputGuardrail` + `on_invoke_tool` wrap) | **−518** | Same Class-A surgeon, **300–500**; and the sandbox/persistence mutual exclusion [V8] must be resolved | **~470–670 lines** |
| **Strands** | ~160 (one `BeforeToolCallEvent` hook) | **−528** | Durability of `_interrupt_state` (**U3**) and promoting `experimental/checkpoint` reliance. **150–400** | **~310–560 lines**, on an experimental API |
| **Claude Agent SDK** | n/a | — | Seam C cannot be built [V16] | **Not portable without losing Seam C** |

`docs/0013` §5's ~150-lines-per-harness estimate is **confirmed for the seams and
refuted for the port**: the seam layer really does land at 160–200 lines on the
best targets, but only pydantic-ai/LangChain/OpenAI-Agents-class ports also carry
a 300–700 line journal/reconciliation bill that `0013` did not price [I2].

### 6.3 What the pivot costs in already-verified work

Not asked for in this part, but it falls out of the table and Phase 10.4 will need
it. On any port:

- The **nine-point chaos suite** is written against the OpenHands crash window
  (§5.2). Its nine points are positions in *that* step ordering. On a
  write-after-result harness the ordering has fewer positions and different ones;
  **the suite does not transfer, it is re-derived.**
- The **four end-to-end crash experiments** (`docs/0014` and successors) measure
  effects across an OpenHands resume. They stop being meaningful the moment
  `Agent.step`'s re-drive is not the resume path.
- The **kernel** (ledger, gate, classifier, reconcile, probes) and
  `tests/test_boundaries.py` transfer intact — that is what the kernel/adapter
  split bought, and it works.
- `agentctl/adapters/openhands/` (688 lines) is rewritten, by design.

So the portable fraction of the 502 tests is high; the *decisive* fraction — the
chaos suite and the crash experiments — is not.

---

## 7. Verdict — **STAY**

Stay on `openhands-sdk`, raise the floor of the pin to `>=1.45.0,<2` and track
1.49.x, and spend the pivot budget on capabilities the incumbent already ships
that `agentctl` has not wired up [V23].

**The evidence that decides it** is one property, not a score total: OpenHands is
the only Python harness surveyed that makes a tool action durable before it runs
*and* re-drives the unmatched action through the executor on resume [V1,V2,V3].
The project's headline correctness claim — "crash it and re-run with `--resume`;
work already done is not repeated, and the agent receives *the result*" — is not
portable to a harness that lacks the second half. Moving deletes 112 lines of
genuinely nasty handoff code and buys, in exchange, 300–700 lines of untested
durability plumbing, a re-derived chaos suite, and four invalidated experiments
[6.2, 6.3]. For one developer on a student budget, that is the wrong trade by a
wide margin.

### 7.1 The losing option's strongest argument, stated fairly

**PORT to pydantic-ai (or LangChain) is a better long-run bet, and here is the
honest case for it.**

`handoff.py` is the worst code in the adapter and it exists only because
OpenHands hands the executor an `Action` with no identity [5.4]. It was broken in
CI by a CPython allocator detail (`docs/0028`) — the class of bug that costs a
weekend and teaches nothing. On pydantic-ai, `WrapperToolset.call_tool` receives
`ctx.tool_call_id` [V13]; the entire mailbox, the strong-reference trick, the
identity re-check and the fingerprint fallback evaporate, and Seams B and C
become one method with one obvious contract. That is a real, permanent reduction
in the project's hardest-to-reason-about surface, and it would make the
multi-agent work of Phase 10.2 — where two agents' actions interleave and
identity matters more, not less — materially safer.

Further: the argument that "OpenHands gives you a durable journal for free" is
the argument that the project has **outsourced its most important invariant to
someone else's library**. `docs/0006`:76 already carries the verdict
*BUILD for multi-agent*. If that build is coming anyway, doing it now against a
harness with a clean tool seam is cheaper than doing it later against a harness
whose ordering you must reverse-engineer at each release.

**Why it still loses here.** All of that is an argument about the *shape* of the
code. The standing constraint is a budget and a working correctness core. The
port's benefit is ~110 lines of elegance; its cost is the only part of the system
that has been *proved by execution rather than by reading* — and `docs/0023`'s
record is that every milestone was finished by a bug only execution could find.
Trading measured behaviour for unmeasured elegance is the specific mistake the
project's own method section exists to prevent.

The strongest version of this argument was that pydantic-ai's `durable_exec`
backends might already implement the write-ahead-then-execute semantics this
project hand-rolled, which would have inverted §6.2. **I checked, and they do
not** [V24]: DBOS memoizes a *completed* step's output — the case OpenHands
already covers — and retries an *incomplete* step from the beginning, which is
the double-execution window verbatim, minus a ledger to detect it, plus a
Postgres dependency. The port's best remaining case is aesthetic, and it is a
good one, but it is not worth the chaos suite.

### 7.2 What to do instead of porting

Cheaper than a port and aimed at the thing actually asked for:

1. **Wire `HookEventType.PRE_TOOL_USE` + `DENY`** [V23] as a second Seam B. It is
   Claude-Code-shaped, it is already in the SDK, and it gives the gate a refusal
   channel that does not depend on `block_action`'s state field.
2. **Use the subagent registry** [V23] for Phase 10.2 rather than designing
   multi-agent from scratch. Markdown `AgentDefinition` files already carry
   `max_budget_per_run` — which is the hook the policy compiler's per-task cap
   needs.
3. **Read `plugin/format/claude_code.py`** before building any plugin surface.
   The "looks like Claude Code" requirement is partly already met.
4. **Bump the pin** from `>=1.45.0` to a bounded `>=1.45.0,<2` and add a CI
   assertion on the three seam symbols (`block_action`, `get_unmatched_actions`,
   `ToolDefinition.executor`), so a future SDK release that moves them fails the
   build rather than the ledger. V6 says they are stable; the assertion is what
   keeps that true.

---

## 8. Sources, tiered and dated

### T1 — source code read directly

**Installed in this repository's virtualenv** (`C:\Users\csdee\openhands\.venv\Lib\site-packages\`),
dist-info `openhands_sdk-1.45.0`; upstream tag `v1.45.0` =
`49ea74587c376b90700f6eff128c3d9b57585d27`, tagged **2026-09-07**:
- `openhands/sdk/conversation/event_store.py::EventLog.append` (188–238),
  `_marker_matches_length`, `_advance_length_marker`
- `openhands/sdk/utils/files.py::atomic_write_text` (6–22)
- `openhands/sdk/io/local.py::LocalFileStore.write` (63–74)
- `openhands/sdk/conversation/state.py::ConversationState.append_event` (315),
  `::block_action` (650), `::pop_blocked_action` (654),
  `::get_unmatched_actions` (677–716)
- `openhands/sdk/agent/agent.py::_ActionBatch.prepare` (228–265), `::emit` (310+),
  `::Agent._execute_actions` (571), `::Agent.step` (634–652),
  `::Agent._get_action_event` (1199)
- `openhands/sdk/agent/response_dispatch.py::_handle_tool_calls` (143–186)
- `openhands/sdk/llm/llm.py::LLM` (220), fields `api_key` (257) / `base_url` (292),
  `::_prepare_transport_kwargs` (2195–2215), `::_transport_call` (2217–2240),
  `::_litellm_call_kwargs` (2087)
- `openhands/sdk/llm/utils/litellm_provider.py::LLMProvider.from_model` /
  `::as_litellm_call_kwargs` (33–82)
- `openhands/sdk/hooks/types.py::HookEventType` (9–13), permission decision `DENY` (39)
- `openhands/sdk/subagent/{schema,registry,load}.py`; `registry.py::register_file_agents` (288)
- `openhands/sdk/plugin/format/claude_code.py::ClaudeCodePluginFormat` (43)

Verified unchanged at tag **v1.49.2** (fetched from GitHub 2026-09-20):
`conversation/state.py` 650/677, `agent/agent.py` 654/660.

**Wheels/sdists downloaded from PyPI on 2026-09-20** and read from the extracted
archive:
- `openhands_ai-1.11.0-py3-none-any.whl` — `METADATA` Requires-Dist block;
  `openhands/app_server/**` (227 files)
- `langgraph-1.2.11-py3-none-any.whl` — `langgraph/pregel/_loop.py::PregelLoop.tick`
  (599–681), `::after_tick` (682–723), `::put_writes` (415–545);
  `langgraph/types.py::Durability` (89); `langgraph/pregel/main.py` (2552–2735)
- `langgraph_prebuilt-1.1.0-py3-none-any.whl` —
  `langgraph/prebuilt/chat_agent_executor.py::create_react_agent` (278);
  `tool_node.py::ToolNode` (622)
- `langchain-1.4.2-py3-none-any.whl` —
  `langchain/agents/middleware/types.py::AgentMiddleware.wrap_tool_call` (674);
  `middleware/tool_emulator.py::LLMToolEmulator.wrap_tool_call` (145);
  `agents/factory.py::create_agent` (772)
- `openai_agents-0.22.3-py3-none-any.whl` —
  `agents/tool_guardrails.py::ToolGuardrailFunctionOutput` (60–117);
  `agents/lifecycle.py::RunHooks.on_tool_start` (70); `agents/tool.py` (468);
  `agents/run.py` (930–1075); `agents/run_internal/agent_runner_helpers.py` (555–620);
  `agents/run_internal/run_loop.py` (400–430); `agents/memory/sqlite_session.py` (211–338);
  `agents/run_config.py::RunConfig` (350–380);
  `agents/models/openai_chatcompletions.py::OpenAIChatCompletionsModel` (55–67);
  `agents/run_state.py::RunState` (764, 1784, 2266); `agents/sandbox/**`
- `pydantic_ai_slim-2.46.0-py3-none-any.whl` —
  `pydantic_ai/toolsets/wrapper.py::WrapperToolset.call_tool` (66–70);
  `toolsets/abstract.py::AbstractToolset.call_tool` (257–268);
  `toolsets/approval_required.py::ApprovalRequiredToolset.call_tool` (26–31);
  `_run_context.py::RunContext.tool_call_id` (174);
  `providers/openai.py::OpenAIProvider` (77–122);
  `agent/abstract.py` model-per-run overload (422);
  `durable_exec/dbos/_operation_backend.py` (126–300),
  `durable_exec/dbos/_utils.py::StepConfig` (8–14) and
  `::guard_enqueue_in_workflow` (17–26),
  `durable_exec/dbos/_durability.py::DBOSDurability` (31–45)
- `strands_agents-1.56.0-py3-none-any.whl` —
  `strands/hooks/events.py::BeforeToolCallEvent` (205–243), `::AfterToolCallEvent` (248);
  `strands/event_loop/event_loop.py` (268–348, 782, 840–842);
  `strands/experimental/checkpoint/checkpoint.py::Checkpoint` (46–64);
  `strands/session/{file,repository}_session_manager.py`
- `smolagents-1.26.0-py3-none-any.whl` —
  `smolagents/agents.py::MultiStepAgent._setup_step_callbacks` (416–434),
  step-callback invocation (623), `::from_dict` (1011), `::from_folder` (1119),
  `::execute_tool_call` (1453); `smolagents/models.py` (1227–1280)
- `mini_swe_agent-2.4.6-py3-none-any.whl` —
  `minisweagent/agents/default.py::DefaultAgent.run` (88–124), `::step` (126),
  `::execute_actions` (154), `::save` (183–190)
- `claude_agent_sdk-0.2.157.tar.gz` —
  `src/claude_agent_sdk/types.py` (250–295, 2109);
  `src/claude_agent_sdk/_internal/transport/subprocess_cli.py::_find_cli` (248–320),
  env merge (812–841); `src/claude_agent_sdk/__init__.py::create_sdk_mcp_server` (491)
- `sweagent-0.0.1-py3-none-any.whl` — PyPI placeholder; contents are 2024-era

**Fetched from GitHub on 2026-09-20:**
- `SWE-agent/SWE-agent` @ `3ea751c0` (last commit **2026-07-16**) —
  `sweagent/agent/agents.py::DefaultAgent.handle_action` (936–1000),
  `::save_trajectory` (779–787), `::step` (1235–1263), run loop (390–433);
  `sweagent/agent/hooks/abstract.py::AbstractAgentHook`
- `repos/*/commits?per_page=1` last-commit dates for all twelve repos in V22
- `repos/Aider-AI/aider` metadata: `pushed_at` 2026-05-22, 1880 open issues,
  `archived: false`

**PyPI resolver output** (`pip index versions`, `pip download`, run 2026-09-20 in
this repo's Python 3.13 venv): `aider-chat` Requires-Python bounds for 0.16.1–0.86.2;
`sweagent` available versions `[0.0.1]`; `openhands-sdk` latest 1.49.2, installed 1.45.0;
`openhands-ai` latest 1.11.0.

**This repository:**
- `agentctl/adapters/openhands/{__init__,handoff,seam_b,seam_c}.py` (137/112/236/203)
- `agentctl/runtime/runner.py` (LLM construction, line 187)
- `pyproject.toml` (`openhands = ["openhands-sdk>=1.45.0"]`)
- `README.md` "How it works"; `docs/0006` §5, §8; `docs/0037`

### T2 — maintainer statements
None load-bearing. Docstrings quoted above are T1 (they ship in the source).

### T3 — third party
None used. No claim in this document rests on a blog post, tutorial or summary.

### Staleness flags
Nothing cited is older than 12 months except:
- **Aider** — last commit 2026-05-22 (4 months). Flagged and dropped [V19].
- **SWE-agent** — last commit 2026-07-16 (2 months). Not stale, but slowing; the
  PyPI package at `0.0.1` is from 2024 and is stale by any measure [V20].
- `docs/0006` (Sept 2026) traced OpenHands at `main ~5aa48d4`/`885408f`. This
  document re-verified the same mechanisms against the pinned 1.45.0 build and
  against v1.49.2. **`0006`'s V1/V2 findings still hold.**

---

## 9. The decision this forces

**Keep `openhands-sdk` as the agent loop, and close Phase 10.1a without a port.**

The evidence that decides it: write-ahead durability plus deterministic re-drive
on resume [V1, V2, V3] is unique to the incumbent among Python harnesses, and it
is the precondition for the SUBSTITUTE verdict that distinguishes this project
from a policy layer. Ten alternatives were scored; none has it.

**There is no open item that would re-open it.** The one candidate — whether
pydantic-ai's DBOS backend journals a tool call before invoking it — was checked
during this survey and does not [V24]. The remaining unknowns (U1–U4, U6) are all
about *challengers being worse than I could prove*, not better; closing any of
them can only strengthen STAY.

What the DECISION document should record as accepted risk: this survey scored ten
harnesses by reading and one by having run it. `docs/0023` says every milestone so
far was finished by a bug only execution could find, so the challengers' scores
are systematically optimistic relative to the incumbent's. That asymmetry is an
argument for STAY, and it is also the reason not to treat these scores as
transferable if the constraints ever change.
