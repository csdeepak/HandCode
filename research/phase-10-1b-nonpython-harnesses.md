---
Number:        —  (unnumbered until filed; see CONVENTIONS.md)
Title:         Phase 10.1b — Non-Python Harness Survey
Type:          RESEARCH
Status:        FROZEN
Created:       2026-09-20
Depends-on:    0005, 0006, 0008, 0010, 0013, 0037
---

# Phase 10.1b — Non-Python Harnesses: can any of them host this kernel?

Executes `docs/0037` Phase 10.1, non-Python candidate set.
All source read at the pinned commits in §8. Nothing here is described from a
blog post; every behavioural claim carries a `file::symbol` and a line number.

---

## 1. Executive answer

**Three of the eight candidates expose a boundary at which an external Python
process can observe a tool action, block it, and substitute a recorded result —
but only one does it without a rewrite, and it is not OpenCode.** Goose runs an
Agent Client Protocol server over stdio (`goose acp`), and when the connected
ACP *client* declares `fs.readTextFile` / `fs.writeTextFile` / `terminal`
capabilities, Goose stops executing its own `write`, `edit` and `shell` tools
and sends each one to the client as a JSON-RPC request whose response *becomes
the tool result* — that is Seam C, verbatim, across a language-neutral pipe.
**Every other candidate tops out at Seam B**: OpenCode, Crush, Cline and Codex
all fire a pre-execution hook that can veto and rewrite arguments, but none of
them has a field in which a hook can hand back a result, so a blocked call
reaches the model as a *rejection*, never as the recorded output — which is
precisely the M2a-vs-M2b distinction the README already draws, and it costs
clean resume. **Wispr is not a harness at all**: the owner means Wispr Flow, a
voice-dictation product, and it is irrelevant to this decision (§4.1).
**Roo Code is archived** (2026-05-15) and **Continue is effectively dormant**
(3 commits on `main` since April 2026); both are dropped. The honest headline
is narrower than "stay on Python": the kernel does not have to be rewritten,
but *every* non-Python option costs a new out-of-process adapter far larger
than the ~150 lines `0013` §5 assumed, and only Goose buys full Seam C for it.

---

## 2. VERIFIED

Claims below were read directly from source at the pinned commits. Every line
number is from that commit.

### 2.1 The cross-language seam — Goose has one, at ACP

**V1. Goose delegates its own effect-bearing tools to the ACP client.**
`crates/goose/src/acp/fs.rs::AcpTools::call_tool` (lines 411-441) intercepts
four tool names before they reach the real executor:

```rust
match name {
    "read"  if self.fs_read  => self.acp_read(arguments, ctx).await...,
    "write" if self.fs_write => self.acp_write(arguments, ctx).await...,
    "edit"  if self.fs_read && self.fs_write => self.acp_edit(...).await...,
    "shell" if self.terminal => self.acp_shell(arguments, ctx).await...,
    _ => self.inner.call_tool(ctx, name, arguments, cancellation_token).await,
}
```

`self.inner` is the real in-process `DeveloperClient`. The four intercepted
names never reach it.

**V2. The flags come from the client's own `initialize` handshake.**
`crates/goose/src/acp/server.rs:1092-1126`. Goose reads
`args.client_capabilities.fs.read_text_file`, `.write_text_file` and
`args.client_capabilities.terminal` (set at `server.rs:1797-1798`), and if any
is true *and* the `developer` extension is enabled, it **replaces the developer
extension's MCP client with `AcpTools`**:

```rust
fs_read:  client_fs_capabilities.read_text_file,
fs_write: client_fs_capabilities.write_text_file,
terminal: client_terminal,
...
agent.extension_manager.add_client("developer".into(), developer_config, client, info).await;
```

A Python client turns Seam C on simply by declaring those capabilities. No
patch, no fork, no config file.

**V3. The client's response *is* the tool result — this is substitution, not
just a veto.** For shell, `AcpTools::acp_shell` (`acp/fs.rs:249-315`) sends
`terminal/create` with the command, then `terminal/wait_for_exit` and
`terminal/output`, and builds the `CallToolResult` **entirely from what the
client returned**:

```rust
let exit_code = output_res.exit_status.and_then(|s| s.exit_code).unwrap_or_default();
let content = vec![ visible_text(format!("exit code: {exit_code}")),
                    visible_text(output_res.output) ];
if exit_code != 0 { Ok(CallToolResult::error(content)) }
else              { Ok(CallToolResult::success(content)) }
```

Nothing runs locally. A Python client holding a recorded observation returns
the recorded `output` and `exit_code` and the agent continues as though the
command had executed — which is exactly what `seam_c.py::GatedExecutor._revive`
does today, expressed over JSON-RPC instead of a Python call.
For reads, `acp_read` (lines 140-160) returns
`CallToolResult::success(vec![visible_text(content)])` where `content` is the
client's string, verbatim.

**V4. The boundary is stdio.** `crates/goose/src/acp/server.rs::run`
(lines 2707-2726): `info!("listening on stdio")`, `tokio::io::stdin()` /
`stdout()`. The CLI subcommand is `Acp { builtins, enable_scheduler }`
(`crates/goose-cli/src/cli.rs:830-843`), dispatched at `cli.rs:2807`. So the
integration is: Python spawns `goose acp --with-builtin developer`, speaks ACP
JSON-RPC over the pipe, and is the executor.

**V5. Coverage is complete for effects.** `DeveloperClient::get_tools`
(`crates/goose/src/agents/platform_extensions/developer/mod.rs:108-185`)
declares exactly five tools: `write`, `edit`, `shell`, `tree`, `read_image`.
The ACP override covers `write`, `edit`, `shell` — **all three effect-bearing
ones** — plus a `read` tool that `AcpTools::list_tools` injects (lines 396-409).
`tree` and `read_image` fall through to `self.inner`, and both are read-only
(`ToolAnnotations` `read_only(true)` at lines 168 and 178 respectively).

**V6. Goose's builtins are *not* separately interceptable.** I tested the
obvious alternative first and it fails. `crates/goose/src/agents/extension_manager/builtin.rs::connect`
uses `tokio::io::duplex(65536)` — an **in-process** pipe pair — for every
builtin outside Docker. And `goose mcp <server>` only serves four extensions
(`crates/goose-mcp/src/mcp_server_runner.rs::McpCommand`: `AutoVisualiser`,
`ComputerController`, `Memory`, `Tutorial`) — `developer` is *not* among them,
because `developer` is now a `Platform` extension, documented at
`crates/goose/src/agents/extension.rs:193` as running "in the agent process".
**ACP is the only boundary that works.** Third-party `stdio` MCP extensions
(`extension.rs:157-177`) remain proxyable by a Python middleman, but that only
covers tools the owner adds, not Goose's own.

### 2.2 The other four: Seam B and arg-rewrite, never Seam C

**V7. Crush — external-command PreToolUse hook, no result field.**
`internal/agent/hooked_tool.go::hookedTool.Run` is a near-exact structural twin
of `seam_c.py::GatedExecutor.__call__`, and the comparison is instructive:

```go
result, err := h.runner.Run(ctx, hooks.EventPreToolUse, sessionID, call.Name, call.Input)
if result.Decision == hooks.DecisionDeny || result.Halt {
    reason := fmt.Sprintf("Tool call blocked by hook. Reason: %s", result.Reason)
    resp := fantasy.NewTextErrorResponse(reason)   // <-- an ERROR, not a result
    resp.StopTurn = result.Halt
    return resp, nil
}
if result.UpdatedInput != "" { call.Input = result.UpdatedInput }   // <-- arg rewrite works
resp, err := h.inner.Run(ctx, call)                                 // <-- always executes
```

The hook is an ordinary shell command, so **a Python script can be the hook
directly** — no shim language. `hooks.HookResult`
(`internal/hooks/hooks.go:67-74`) is the complete contract:
`Decision`, `Halt`, `Reason`, `Context`, `UpdatedInput`. **There is no output
field.** `Context` is appended to the result *after* `h.inner.Run` returns
(`hooked_tool.go:91-96`). Exit code 2 blocks the call, 49 halts the turn
(`hooks.go:18-21`).

**V8. Cline — subprocess hooks, same ceiling.** `HookControl`
(`sdk/packages/shared/src/hooks/contracts.ts:1-9`) is
`{cancel, review, context, overrideInput, systemPrompt, appendMessages, replaceMessages}`.
The tool-call path consumes it at
`sdk/packages/core/src/hooks/hook-file-hooks.ts:540-564`, producing
`{stop, reason, input, appendContext}` — block ✓, arg-rewrite ✓
(`result.input = control.overrideInput`), **no result field**. Hooks may be
subprocesses (`sdk/packages/core/src/hooks/subprocess.ts`, `HookOutputSchema`
at lines 74-84), so Python can be the hook.

**V9. Codex — `Denied { rejection: String }` is a message channel, not a
result.** `ReviewDecision` (`codex-rs/protocol/src/protocol.rs:4145-4175`):
`Approved`, `ApprovedForSession`, `…PolicyAmendment`, `Denied { rejection }`,
`TimedOut`. The doc comment on `Denied` is explicit: *"the agent should not
execute it, but it should continue the session and try something else."* You
could stuff a recorded stdout into `rejection`, but the model receives it
framed as a refusal, with no exit code and no stdout/stderr structure. That is
Seam B with a note attached — the README's M2a row, not M2b.

**V10. OpenCode — `tool.execute.before` cannot substitute.** The hook's output
object is `{ args: any }` and it returns `Promise<void>`
(`packages/plugin/src/index.ts:266-269`). The call site settles the question
(`packages/opencode/src/session/tools.ts:105-114`):

```ts
yield* plugin.trigger("tool.execute.before", { tool: item.id, sessionID, callID }, { args })
const result = yield* item.execute(args, ctx)     // unconditional
yield* plugin.trigger("tool.execute.after", { ... }, output)
```

`item.execute` is called unconditionally; there is no branch a hook can take.
Blocking works only by throwing — confirmed by OpenCode's own test using
`Effect.die` at `packages/opencode/test/tool/code-mode.test.ts:431`.
`tool.execute.after` *can* mutate `{title, output, metadata}`, but that is
after the effect landed and is therefore worthless for this kernel.

**V11. OpenCode has a second, better path — full tool replacement.** A plugin
may register tools via `Hooks.tool` (`packages/plugin/src/index.ts:225-227`).
These are collected into `custom` (`packages/opencode/src/tool/registry.ts:199-203`)
and `all()` returns `[...s.builtin, ...s.custom]` (line 258). Because
`session/tools.ts:100` assigns into an object keyed by tool id
(`tools[item.id] = tool({...})`), **a plugin tool named `bash` overwrites the
built-in**. The plugin's own `execute` then *is* the executor, giving genuine
substitution — but in TypeScript, and the plugin must reimplement whatever it
overrode (`PluginInput.$: BunShell`, `index.ts:62`, makes that feasible for
shell). This is a real Seam C at the cost of a TS shim plus reimplementation.

### 2.3 Model configuration — all four live candidates take a LiteLLM proxy

| Harness | Symbol | Verdict |
|---|---|---|
| Codex | `ModelProviderInfo { base_url, env_key, wire_api, http_headers }`, `codex-rs/model-provider-info/src/lib.rs:134-171` | cleanest; purpose-built for this |
| Crush | `config.BaseURL` (`internal/config/config.go:97`) → `p.APIEndpoint` (`internal/config/load.go:231-232`) | works |
| OpenCode | `providerConfig?.options?.endpoint ?? providerConfig?.options?.baseURL` → `providerOptions.baseURL`, `packages/opencode/src/provider/provider.ts:362-365` | works |
| Goose | `OpenAiCompatibleProvider` (`crates/goose-providers/src/openai_compatible.rs:31-47`) + declarative providers; `OPENAI_HOST` / `OPENAI_BASE_PATH` (`openai.rs:645-652`) | works |

All four accept an arbitrary OpenAI-compatible `base_url` + key. **The existing
LiteLLM proxy plugs into any of them with zero code.** That column does not
discriminate.

### 2.4 Liveness

| Harness | Last commit on default branch | Commits since 2026-08-01 | Status |
|---|---|---|---|
| Codex | 2026-09-20 | 2239 | very active |
| Crush | 2026-09-20 | 245 | active |
| OpenCode | 2026-09-19 | 496 | very active |
| Goose | 2026-09-19 | 487 | very active |
| Cline | 2026-09-19 | 567 | very active |
| Continue | 2026-07-20 | **0** | dormant (see §3) |
| Roo Code | 2026-05-15 | **0** | **ARCHIVED** (GitHub API `archived: true`) |

Roo Code: `https://api.github.com/repos/RooCodeInc/Roo-Code` returns
`"archived": true`, `"pushed_at": "2026-05-15T18:08:47Z"`. Its final commit is
`Remove roocode.com web app (#12375)`. **Dropped.**

---

## 3. INFERRED

**I1. Continue is being wound down.** Chain: commits on `main` by month in 2026
are Jan 349, Feb 214, Mar 252, Apr 10, May 0, Jun 21, Jul 3, Aug 0, Sep 0. The
final commit (`5522c6f`, 2026-07-20) is `docs: remove Sign in link (login flow
retired)`. `git branch -r` shows only `origin/main`, yet the GitHub API reports
`pushed_at: 2026-09-20` — so *something* is still pushed (tags or CI refs)
while the code branch is static. Confidence: high that it is unsuitable to
build on; I did not find a formal deprecation notice, so the *reason* is
inferred, not the inactivity. **Dropped** either way — the seam analysis
(a TypeScript library with in-process tool execution) puts it in the same class
as Cline at best, with none of Cline's momentum.

**I2. OpenCode's plugin-tool override works for `bash` specifically.** I
verified the registry mechanics (V11) by reading, not by running. The
last-write-wins behaviour follows from `tools[item.id] = ...` over a list that
places `custom` after `builtin`; I did not execute OpenCode with an overriding
plugin to confirm no earlier filter rejects a duplicate id. `validateName` in
the v2 registry (`packages/core/src/tool/registry.ts:88`) does check names, but
the v1 path that `session/tools.ts` uses does not appear to. Confidence:
medium-high. Running one plugin would settle it.

**I3. Goose's ACP route re-drives on resume the same way OpenHands does, so the
double-execution bug is *the kernel's to prevent*, not Goose's to avoid.** ACP
sessions are resumable (`session/load` exists in the protocol and Goose
implements session persistence), and nothing in `acp/fs.rs` records that a
`terminal/create` was issued before issuing it. That is the correct division of
labour for this project — it is exactly the gap `agentctl`'s ledger fills — but
it means the persistence-ordering property has to be re-established on the
Python side, not inherited. I did not trace Goose's session-resume code far
enough to state the ordering as VERIFIED.

**I4. Port cost, priced against `agentctl/adapters/openhands/` (137 + 112 + 236
+ 203 = 688 lines).** `0013` §5's ~150-lines-per-harness estimate is wrong for
every non-Python target, because the adapter stops being a set of function
wraps and becomes a protocol server:

| Target | What the adapter must be | Estimate |
|---|---|---|
| Goose (ACP) | A full ACP **client**: JSON-RPC framing over stdio, `initialize` with capabilities, `session/new`, `session/prompt`, streaming `session/update` notifications, and handlers for `fs/read_text_file`, `fs/write_text_file`, `terminal/create`, `terminal/wait_for_exit`, `terminal/output`, `terminal/release`, `terminal/kill`, `session/request_permission`. Seams B and C both land in the terminal/fs handlers. No Python ACP library exists — hand-rolled. | **900–1,400 lines** Python + a chaos-suite rewrite |
| Crush / Cline | A hook executable (small) — but **Seam C is unavailable**, so the system degrades to M2a permanently and the substitution half of the ledger goes unused. | 200–350 lines, buys less |
| OpenCode | TS plugin shim + Python IPC server + reimplementation of each overridden tool. Two languages to maintain. | 400–700 lines TS+Py |
| Codex | Approval client over app-server JSON-RPC; Seam C unavailable. | 400–600 lines, buys less |

Basis: the OpenHands adapter is 688 lines *given* an in-process SDK that hands
it typed events and executors. An out-of-process adapter must additionally own
framing, handshake, lifecycle, reconnection, and observation (de)serialisation
across a language boundary — the work `openhands-sdk` currently does for free.
Confidence: medium; these are structural estimates, not measured ports.

---

## 4. UNKNOWN

**4.1 Wispr — resolved, and it is not what the owner thinks.** VERIFIED as far
as it goes: **Wispr Flow (wisprflow.ai) is an AI voice-dictation product** —
speech-to-text that cleans up disfluencies and types into any app, ~$10-12/mo,
macOS/Windows/iOS/Android. It is **not a coding harness and has no agent loop,
no tool execution, and no seams**. It is irrelevant to this decision. There is
a plausible source of the confusion: a separate project spelled **Wisp**
(`Pepewitch/wisp`) is a *harness-independent coding-agent task manager* that
gives each task a git worktree and drives Claude Code / Codex / OpenCode from
outside — an orchestrator, not a harness, and therefore also not a candidate to
host this kernel (though it is arguably a competitor to what `agentctl run`
already does). What remains UNKNOWN is **which of the two the owner meant**.
That matters only for Phase 10.3's UX question, not for this one. Resolving it:
ask him whether he was describing a *voice* input surface (Flow) or a
*worktree-per-task* surface (Wisp).

**4.2 Whether Goose's ACP client can decline a write without the agent
misreading it.** `acp_write` (`acp/fs.rs:162-196`) treats any non-error
response as success and then synthesises its own text — `"Wrote {path} ({n}
lines)"` — and it calls `path.exists()` to choose between "Wrote" and
"Created". A Python client that suppresses the write (substitution for an
already-landed effect) will cause Goose to report a write that this run did not
perform. That is *correct* for the resume case and *wrong-looking* for any
other. What would resolve it: a spike that runs `goose acp` against a stub
Python client and reads the resulting transcript.

**4.3 Whether Goose's ACP session resume re-drives an unmatched tool call.**
See I3. Resolving it: crash a `goose acp` session between `terminal/create` and
`terminal/output`, resume, and observe whether a second `terminal/create`
arrives for the same logical action. This is the `docs/0014` experiment,
re-run against Goose — and it is the single highest-value thing to measure
before committing to a port.

**4.4 Whether `session/request_permission` fires for the ACP-delegated tools.**
Goose has the machinery (`crates/goose/src/acp/common.rs:55-98`,
`RequestPermissionOutcome`), but I did not confirm whether a delegated `shell`
also raises a permission request — which would give Python *two* interception
points and possibly a cleaner Seam B than the terminal handler.

**4.5 Mid-conversation model switching, structurally.** VERIFIED that the
affordance exists: Goose `/model` (`crates/goose-cli/src/session/input.rs:230`),
Codex `SlashCommand::Model` (`codex-rs/tui/src/slash_command.rs:129`), OpenCode
`packages/tui/src/component/dialog-model.tsx`, Crush
`internal/ui/dialog/models.go`. What is UNKNOWN is what each does to tool-call
history recorded in the previous provider's schema when the new provider is a
different wire format. That is `0037` Phase 10.3's question and I did not
answer it here.

---

## 5. Mechanism — how Goose's ACP delegation actually works, at implementer level

This is the section to read if the port happens.

**Startup.** Python spawns `goose acp --with-builtin developer`. Goose logs
`listening on stdio` and serves ACP over the pipe
(`acp/server.rs::run`, 2707-2726).

**Handshake — this is where Seam C is switched on.** Python sends `initialize`
with:

```json
{ "clientCapabilities": { "fs": { "readTextFile": true, "writeTextFile": true },
                          "terminal": true } }
```

Goose stores these (`acp/server.rs:1797-1798`). At session creation it checks
them (`server.rs:1092-1097`), checks `developer` is enabled (1099-1106),
constructs `AcpTools` wrapping the real `DeveloperClient` as `inner`
(1118-1126), and **swaps it in as the `developer` extension's client**
(`add_client("developer".into(), …)`, 1138-1140). From here Goose's own
`write`/`edit`/`shell` are Python's to answer.

**Per tool call.** `AcpTools::call_tool` matches on name (411-441):

- `shell` → `acp_shell` (249-315). Python receives **`terminal/create`**
  carrying `{command, cwd, env:[AGENT_SESSION_ID], outputByteLimit}`
  (`create_terminal_request`, 74-82). **This is the observation point, and it is
  before anything runs.** Python then answers three more requests:
  `terminal/wait_for_exit`, `terminal/output` (returning `{output,
  exitStatus:{exitCode}}`), and `terminal/release`. Goose assembles the tool
  result from those two fields alone.
  - *Execute*: Python actually runs the command and returns the real output.
  - *Block*: return a non-zero `exitCode` with an explanatory `output` — Goose
    emits `CallToolResult::error`, and the agent sees a failed command.
  - *Substitute*: return the **recorded** `output` and `exitCode` without
    running anything. The agent cannot tell.
  - *Idempotency-key stamping*: Python holds the command string before
    execution, so it can rewrite it — the same power
    `seam_c.py::_stamp_idempotency_key` needs.
- `write` → `acp_write` (162-196): Python receives `fs/write_text_file`
  `{path, content}`. Executing, blocking (error response) and suppressing all
  work; see §4.2 for the caveat on Goose's synthesised success text.
- `edit` → `acp_edit` (199-247): Goose reads via the client, does the
  `string_replace` **in Rust**, then writes via the client. Python sees both
  halves but not the match logic.
- `read` → `acp_read` (140-160): Python's returned string becomes the result
  verbatim.
- anything else → `self.inner` — in-process Rust, invisible to Python.

**The mapping onto the existing kernel.** `handoff.py`'s whole reason for
existing — that `ToolExecutor.__call__` receives an *action* carrying no
identity, so the seam that can identify a call is not the seam that can
substitute for it — **disappears** here. ACP's `terminal/create` request
arrives with its own JSON-RPC request id and the tool call is already
correlated, so Seam B and Seam C collapse into one handler. The
`SubstitutionHandoff` mailbox, the `id()`-recycling hazard documented in
`docs/0028`, and the fingerprint fallback all become unnecessary. That is the
one genuine architectural *simplification* a port would buy, and it is worth
saying out loud alongside the costs.

**What a port does NOT get for free:** the ordering guarantee. `docs/0006` V1
gives this project OpenHands' contract that the `ActionEvent` is persisted and
callbacks fire before the tool executes. Under ACP, **Python is the one holding
that ordering** — it must write the ledger row and fsync *before* replying to
`terminal/create`. That is strictly easier to get right than auditing someone
else's loop, but it is a property that must be rebuilt and re-chaos-tested, not
inherited. The nine-point chaos suite would need its crash points redefined
around the JSON-RPC exchange rather than around Python function boundaries.

---

## 6. Scoring — the five seams, plus model-selection UX

Weights per `0037`: Seam C highest. `~` = partial.

| Harness (lang) | 1. Library/app — entry point | 2. Model config: runtime `base_url`+key | 3. Seam B (observe+block) — symbol | 4. **Seam C (substitute)** | 5. Persistence ordering | Model-selection UX | Last commit |
|---|---|---|---|---|---|---|---|
| **Goose** (Rust) | **Yes** — `goose acp` over stdio, `acp/server.rs::run`; also `goose serve` (HTTP/WS) | Yes — `OpenAiCompatibleProvider`; declarative providers; `OPENAI_HOST` | **Yes** — the ACP request itself (`terminal/create`, `fs/write_text_file`) arrives pre-execution | **YES** — `AcpTools::acp_shell` / `acp_read` build the result from the client's reply | **UNKNOWN** (I3/4.3) — but ordering becomes Python's to own, which is the right place | `goose configure` + `/model` mid-session; config.yaml | 2026-09-19 |
| **OpenCode** (TS) | **Yes** — `cli/cmd/serve.ts` + `server/server.ts` HTTP API + published SDK | Yes — `provider.options.baseURL` (`provider.ts:362-365`) | **Yes** — `tool.execute.before` (throw to veto), `permission.ask` | **~** — *not* via hooks (`{args}` only); **yes** via `Hooks.tool` override (V11), needs a TS shim + reimplementation | Unknown; not traced | **Best in class** — models.dev registry + `dialog-model.tsx` picker; mid-session switch | 2026-09-19 |
| **Codex** (Rust) | **Yes** — app-server JSON-RPC (`codex-rs/app-server`), `codex mcp-server`, `sdk/` | **Yes, cleanest** — `ModelProviderInfo{base_url, env_key, wire_api}` | **Yes** — `ExecCommandApproval` / `ApplyPatchApproval` → `ReviewDecision` | **NO** — `Denied{rejection:String}` is a refusal with a note (V9) | Not traced | `/model` slash command; `config.toml` profiles | 2026-09-20 |
| **Crush** (Go) | Partial — `internal/server`, but TUI-first | Yes — `config.BaseURL` → `APIEndpoint` | **Yes** — `hooks.EventPreToolUse`, **an external command**, so Python directly; `+ UpdatedInput` arg-rewrite | **NO** — `HookResult` has no output field (V7) | Not traced | `internal/ui/dialog/models.go` picker; `crush.json` | 2026-09-20 |
| **Cline** (TS) | **Yes** — `@cline/core` SDK, `apps/cli` | Yes — `@cline/llms` provider config | **Yes** — `HookControl{cancel, overrideInput}`, subprocess hooks | **NO** — no result field (V8) | Not traced | Settings UI / CLI config | 2026-09-19 |
| **Continue** (TS) | Yes — `core` is an npm lib | Yes | Not investigated | Not investigated | — | Config-file `models:` block | 2026-07-20 — **DORMANT** |
| **Roo Code** (TS) | — | — | — | — | — | — | 2026-05-15 — **ARCHIVED** |
| **Wispr Flow** | **Not a harness** — voice dictation product (§4.1) | n/a | n/a | n/a | n/a | n/a | n/a |

Two candidates I looked for and did not add: **Pi** (`pi-mono`) and **Wisp**
(`Pepewitch/wisp`) surfaced during the Wispr search. Wisp is an orchestrator
over other harnesses, not a harness — out of scope. Pi I did not evaluate; it
appears only in T3 listings and I will not score a candidate I have not read.
Flagged as a gap, not a recommendation.

---

## 7. Verdict

**Is any non-Python harness reachable from this Python kernel? YES — exactly
one, and the boundary is named.**

**The boundary:** Goose's Agent Client Protocol server, `goose acp`, with the
Python process acting as the ACP *client* and declaring
`fs.readTextFile` + `fs.writeTextFile` + `terminal` capabilities. At that
boundary Python observes every `write`, `edit` and `shell` before it happens,
can refuse it, and can return a recorded result in its place. All three
powers, across a language-neutral stdio pipe, with no fork and no patch.
This is the only non-Python candidate that reproduces `seam_c.py` rather than
degrading to `seam_b.py`.

**The cost, priced honestly:**

- **900–1,400 lines** of new Python — a hand-rolled ACP client (no Python ACP
  library exists), covering framing, handshake, session lifecycle, streaming
  updates, and seven request handlers. Against the current 688-line OpenHands
  adapter, and against `0013` §5's ~150-line estimate, which this falsifies by
  roughly an order of magnitude.
- **The nine-point chaos suite must be redesigned.** Its crash points are
  defined around Python function boundaries inside one process; under ACP they
  have to be redefined around the JSON-RPC exchange. The *property* being
  tested survives; the tests do not.
- **§4.3 is unresolved and is a go/no-go.** If Goose's ACP resume re-drives an
  unmatched tool call, the ledger handles it exactly as designed. If Goose does
  something else, the design has to absorb it. **Measure this before writing
  any adapter code** — it is a one-afternoon spike (stub ACP client, crash
  between `terminal/create` and `terminal/output`, resume, count the effects)
  and it is the `docs/0014` experiment pointed at a new target.

**What the owner gives up if he picks OpenCode anyway** — and he named it, so
this needs saying plainly. OpenCode has the best model-selection UX of the set
by a clear margin (models.dev registry, real picker, mid-session switching)
and it is the most active project here. But its hook system **cannot substitute
a result**, so the only route to Seam C is overriding built-in tools from a
TypeScript plugin and reimplementing them — which means maintaining an adapter
in two languages, and owning a reimplementation of `bash` that must not drift
from OpenCode's. That is a worse deal than Goose's, and the thing he actually
liked about OpenCode — the models UX — is a *UI question* that `agentctl dash`
can answer on its own, against the LiteLLM proxy's `/v1/models`, without
adopting OpenCode's agent loop at all. **The interaction model he wants and the
harness he runs are separable, and separating them is the cheap move.**

**What I am not recommending.** Nothing here justifies a port on its own.
Every live candidate accepts the LiteLLM proxy with zero code, so the
multi-API requirement — the thing that prompted the pivot — **is not a reason
to leave OpenHands**. `agentctl run --model openai/pool --base-url
http://localhost:4000` already does it. The only defensible reason to move is
if OpenHands' *harness features* (TUI, multi-agent, model UX) are judged worth
900+ lines of new adapter and a chaos-suite rewrite, and that is a Phase
10.2/10.4 judgement, not this document's. On the evidence here the
recommendation to carry into the DECISION is **STAY, and build the model-selection
surface against the proxy** — with Goose held as the one credible PORT target
should that judgement go the other way, and §4.3 as the gate on it.

---

## 8. Sources — tiered, dated, version-pinned

All repositories cloned and read 2026-09-20. All are T1 (source code).
Permalinks are `https://github.com/<repo>/blob/<sha>/<path>#L<line>`.

**T1 — source code, read directly**

| Repo | Pinned commit | Date | Files read |
|---|---|---|---|
| `block/goose` | `2090ad1c65ddb39497601a936a9fe17d66254bfe` | 2026-09-19 | `crates/goose/src/acp/fs.rs` (`AcpTools::call_tool`, `acp_read`, `acp_write`, `acp_edit`, `acp_shell`, `run_terminal_to_completion`, `create_terminal_request`); `crates/goose/src/acp/server.rs` (:1092-1140, :1797-1798, `run` :2707-2726); `crates/goose/src/acp/common.rs`; `crates/goose/src/agents/extension.rs` (`ExtensionConfig` :156-236); `crates/goose/src/agents/extension_manager/builtin.rs` (`connect`); `.../stdio.rs`; `crates/goose/src/builtin_extension.rs`; `crates/goose-mcp/src/lib.rs`; `crates/goose-mcp/src/mcp_server_runner.rs` (`McpCommand`); `crates/goose/src/agents/platform_extensions/developer/mod.rs` (`get_tools` :108-185); `crates/goose-cli/src/cli.rs` (:830-843, :2807); `crates/goose-providers/src/openai_compatible.rs`; `crates/goose-providers/src/openai.rs` |
| `sst/opencode` | `ebb7b76eca82342642c78645109e865614533827` | 2026-09-19 | `packages/plugin/src/index.ts` (`Hooks` :222-330, `PluginInput` :56-68); `packages/plugin/src/tool.ts` (`ToolDefinition`, `ToolResult`); `packages/opencode/src/session/tools.ts` (:85-135); `packages/opencode/src/session/prompt.ts` (:290-400); `packages/opencode/src/tool/registry.ts` (:180-210, :255-340); `packages/core/src/tool/registry.ts`; `packages/opencode/src/provider/provider.ts` (:362-365); `packages/opencode/test/tool/code-mode.test.ts` (:431) |
| `openai/codex` | `5c5308fc9a9ee789049d646ef11e5400384b9c6f` | 2026-09-20 | `codex-rs/protocol/src/protocol.rs` (`ReviewDecision` :4145-4175); `codex-rs/model-provider-info/src/lib.rs` (`ModelProviderInfo` :134-174); `codex-rs/app-server-protocol/src/protocol/common.rs` (:1815-1823); `codex-rs/tui/src/slash_command.rs` (:129) |
| `charmbracelet/crush` | `0bca9525d5f89c6cae830beff0cfbbff77d10c13` | 2026-09-20 | `internal/hooks/hooks.go` (complete); `internal/agent/hooked_tool.go` (complete); `internal/config/config.go` (:97); `internal/config/load.go` (:231-232); `internal/ui/dialog/models.go` |
| `cline/cline` | `9a2512bb9835869d74774da99708a7f9d80b0fe8` | 2026-09-19 | `sdk/packages/shared/src/hooks/contracts.ts` (`HookControl`); `sdk/packages/shared/src/hooks/events.ts`; `sdk/packages/core/src/hooks/hook-file-hooks.ts` (:540-585); `sdk/packages/core/src/hooks/subprocess.ts` (:67-84); `sdk/ARCHITECTURE.md` |
| `RooCodeInc/Roo-Code` | `b867ec9145750d0ae1ff7f02d35406e9bf2a0b16` | 2026-05-15 | liveness only — **archived** |
| `continuedev/continue` | `5522c6f44ca0ac3528b37244818fbfa39b5af470` | 2026-07-20 | liveness only — dormant |

**T1 — official API**

- GitHub REST API `/repos/{owner}/{repo}`, queried 2026-09-20: Roo Code
  `archived: true`, `pushed_at: 2026-05-15T18:08:47Z`, 24,302 stars;
  OpenCode `pushed_at: 2026-09-20T12:43:40Z`, 208,796 stars;
  Continue `pushed_at: 2026-09-20T09:45:41Z`, 35,960 stars.

**T1 — this repository**

- `agentctl/adapters/openhands/seam_c.py` (203 lines), `seam_b.py` (236),
  `handoff.py` (112), `__init__.py` (137), read 2026-09-20.
- `README.md` "How it works"; `docs/0037-harness-pivot-research-brief.md`.

**T3 — used only to locate candidates, decided nothing**

- Web search for "Wispr", 2026-09-20 → `wisprflow.ai`, Wikipedia "Wispr Flow",
  Google Play / App Store listings: voice-dictation product. Corroborating and
  mutually consistent across vendor and encyclopedic sources, but the product
  claim is **not load-bearing for any seam verdict** — it only establishes that
  Wispr is out of scope.
- `github.com/Pepewitch/wisp` README (via search result), 2026-09-20 — used
  only to note the Wisp/Wispr name collision. Not scored.
- Listicles (`awesome-cli-coding-agents`, dev.to, pinggy.io), 2026-09-20 —
  used only to check whether a candidate had been missed. Surfaced "Pi", which
  I declined to score without reading its source (§6).

**Staleness.** No source used here is older than 2026-05-15, and every scored
claim comes from a commit dated 2026-09-19 or 2026-09-20. Nothing is flagged
stale. The corollary is that all five live candidates are moving fast enough
that **these seam findings have a short shelf life** — OpenCode shipped 496
commits in the last seven weeks, and a `tool.execute.before` that gains a
result field would change this document's verdict outright.

---

## 9. Decision I am asking you to make

**Decide whether the harness's user-facing features are worth 900+ lines of new
out-of-process adapter and a redesigned chaos suite — knowing that the
multi-API requirement that prompted this pivot does not require a port at all.**

The evidence that decides it: §2.3 — all four live candidates accept the
LiteLLM proxy with zero code, and so does the incumbent. The pivot's original
justification therefore evaporates. What remains is a UX preference (OpenCode's
models picker) that §7 argues is separable from the agent loop, and a
multi-agent ask that Phase 10.2 has not yet costed.

If the answer is "yes, port anyway", the target is **Goose via ACP** and the
first action is the §4.3 spike, not adapter code.
