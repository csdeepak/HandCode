# AI Agent Control Plane

[![CI](https://github.com/csdeepak/HandCode/actions/workflows/ci.yml/badge.svg)](https://github.com/csdeepak/HandCode/actions/workflows/ci.yml)

Making long-running LLM agent work **recoverable, measurable, and
cost-efficient** across changes of provider, account, and model.

> The model/provider endpoint can change; the logical agent work must remain
> recoverable, measurable, and cost-efficient.

**Status: the correctness core works.** M0, M2a, M4 and M2b are complete and
verified. 623 tests — including a nine-point chaos suite with real process
death — plus four end-to-end crash experiments. All green.

---

## The problem, in one example

An agent runs `git commit`. The process dies before the result is recorded. On
resume, OpenHands re-drives the pending action through the real executor — and
commits again.

That is not a hypothesis. `docs/0014` reproduces it: **1 effect before the
crash, 2 after resume.**

With this layer installed:

| | M2a | M4 | M2b |
|---|---|---|---|
| Duplicate effect | none | none | none |
| Ledger state | `BLOCKED` | `COMMITTED` | `COMMITTED` |
| Human needed | yes | no | no |
| Agent receives | rejection | rejection | **the result** |

---

## Verify it yourself

```bash
python -m venv .venv && .venv/Scripts/activate     # bin/activate on Unix
pip install -e ".[dev,openhands]"
python verify.py
```

**Zero cost** — everything runs against a local mock provider. No API key, no
network, no tokens. Takes about four minutes.

Requires Python ≥ 3.12 (the OpenHands SDK does) and `git` on PATH.

If a dependency has since shipped something incompatible, install the exact set
that is known to pass:

```bash
pip install -e ".[dev,openhands]" -c constraints.txt
```

CI runs both forms on Linux and Windows, and runs `verify.py` itself — so the
badge above means the correctness claim reproduces on a machine that is not
mine, which is the only version of that claim worth anything.

### The proxy extra needs two steps

`litellm[proxy]` declares `mcp<2.0`; the OpenHands SDK needs `fastmcp` and so
needs `mcp>=2`. They are incompatible on paper and work in practice, so the
override is explicit rather than hidden in a version range pip would refuse:

```bash
pip install -e ".[dev,openhands,proxy]"
pip install --upgrade "mcp>=2.2.0" "fastmcp>=4.0.3"
```

`fastmcp` is named explicitly because the proxy install leaves only
`fastmcp-slim`, which has no client support — and the SDK does
`from fastmcp import Client` on nearly every import path.

Only Seam A and the full-stack demo need this. Everything else — including the
whole correctness core — runs without the proxy.

---

## Set up your keys

```bash
agentctl keys --init      # writes keys.env listing every provider + how to get one
agentctl keys             # what is set, and where to get the rest
agentctl keys --install-hook  # refuse any commit containing one of your keys
agentctl keys --check     # does every key actually work? costs no tokens
agentctl dash             # failover, effects, spend, policy on one screen
```

`keys.env` is gitignored **before** it is written, and no command ever prints a
value. If it ever becomes tracked by git, every command says so loudly and
tells you to rotate — a `.gitignore` entry added after a file is tracked does
nothing (`docs/0032`).

**Multiple accounts per provider** is the point. A free-tier cap is usually
per account, so a second key at the *same* provider buys a second quota:

```
OPENROUTER_API_KEY=sk-or-v1-...      # first account
OPENROUTER_API_KEY_2=sk-or-v1-...    # second, separate quota
GEMINI_API_KEY=...                   # different provider, survives an outage too
```

Any suffix works (`_2`, `_ALT`, `_WORK`), and each becomes its own deployment
in the pool. `agentctl dash` says which of four states you are actually in
(`docs/0033`).

## Use it

```bash
agentctl doctor --workspace ./myproject     # check BEFORE you spend
agentctl run "add type hints to utils.py" --workspace ./myproject
```

`doctor` checks packages, the SDK import chain, git, your provider keys, the
policy, and whether the workspace has uncommitted changes the agent is about
to edit.

> **Correction (2026-09-21).** This paragraph used to say OpenRouter exposes no
> remaining-free-request counter on any endpoint (`docs/0031`). That is false.
> `GET /api/v1/key` returns `free_model_daily_requests` with `used`, `limit`
> and `remaining`, and it costs nothing — measured against six live accounts,
> all reporting `limit=50`. `probe.py` was already calling the sibling endpoint
> `/api/v1/auth/key` the whole time. `docs/0038` §9.4 records the measurement;
> surfacing it is scheduled work.

Real tools (bash, read, write), a real model, every effect classified and
ledgered. Crash it and re-run with `--resume <id>`: work already done is not
repeated.

### Run it again for nothing

```bash
agentctl run "..." --workspace ./app --record session.jsonl   # once, for real
agentctl run ""    --workspace ./app --replay session.jsonl   # $0.00, offline
```

`--replay` serves every completion from the recording: no API key, no network,
no tokens, no sampling. A request the cassette does not contain is answered
with a 502 naming the turn that diverged, never with a plausible-looking
completion — a replay that cannot fail would not be worth running.

Replay pins the model, not the world: tool output feeds the next request, so
the workspace has to start where the recording did (`docs/0029`).

Two safety properties, deliberately separate — the **gate** stops an effect
happening *twice*; `--confirm-destructive` (on by default) stops one happening
*at all* without a human saying yes. It asks on two grounds: the effect is
destructive, **or** it writes outside the workspace. `echo x > ~/.bashrc` is an
ordinary idempotent write that is simply none of the agent's business
(`docs/0027`).

### Or embed it

```python
from agentctl.adapters.openhands import protect

guard = protect(
    ledger="./ledger.db",
    conversation_id=str(conversation_id),
    tools={"commit": CommitTool},      # gated at Seam C
    repo_root="./workspace",           # for the git probe
    takeover=resuming_after_a_crash,   # a dead process cannot free its lease
)

conv = Conversation(agent=agent, callbacks=[guard.seam_b], ...)
guard.attach(conv)                     # required, or the gate is inert
```

Omit `tools` to run Seam B only: still correct, but an already-landed effect is
blocked rather than resumed cleanly.

### Failing over

```bash
agentctl proxy --out ./proxy --verify   # skips providers that cannot serve
bash ./proxy/start.sh 4000              # or ./proxy/start.ps1 on Windows
agentctl run "..." --model openai/pool --base-url http://localhost:4000
```

A pool over **one** provider key survives a transient upstream overload and a
per-model limit. It does **not** survive an account-wide daily cap — three
`:free` models on one key share one quota. The command counts credentials, not
deployments, and says so.

### Choosing one source

```bash
agentctl models                        # every source, and what choosing it costs
agentctl run "..." --source gemini --base-url http://localhost:4000
```

`pool` is the default and the widest thing you can ask for. A source group is
narrower **on purpose**, so every row says what it gives up:

```
  pool                    48 deployments  24 accounts   the default
     pool-openrouter      18 deployments   6 accounts   gives up 30 of 48
     pool-gemini           6 deployments   6 accounts   gives up 42 of 48
```

That line is the feature. Narrowing to one source means an account-wide daily
cap has less to fail over to — the exact failure the multi-account design
exists to escape (`docs/0033`). `--verify` marks which sources can actually
serve, which is not the same as which ones you hold keys for.

### Delegating a read

```bash
agentctl subagent --init               # writes an example definition
agentctl subagent reviewer "what does the gate do?"
```

Claude Code's Markdown frontmatter format, loaded through the SDK's own
`AgentDefinition`. A subagent may hold **`read_file` and nothing else** — no
shell, no writes, no MCP.

That is not a starter limitation, it is the whole safety argument. Multi-agent
is skipped because four correctness mechanisms assume a single writer
(`docs/0038` §4.2); a subagent that cannot produce an effect needs none of
them. So the restriction is enforced twice — the definition is validated, and
the tool list handed to the agent is built from a constant rather than from
the definition, because a property that depends on one function returning
correctly is one refactor from gone.

### Installing a plugin, one capability at a time

```bash
agentctl plugins ./some-plugin         # the audit. Installs nothing.
```

A Claude Code plugin can carry agents, hooks, commands, skills and MCP
servers. **Five of those six are refused**, and each refusal is counted:

```
  ADMITTED  1 read-only agent(s)
  REJECTED  1 agent(s) that could change the world
  REFUSED   mcp_config  2 declared
            commands    1 declared
```

"declines MCP servers" is a policy; "2 declared" is a fact about the thing in
front of you, and only the second tells you whether refusing it matters. A
broker that silently dropped half a plugin would leave you believing you had
installed something you had not.

### Policy

```bash
agentctl policy policy.yaml            # compile, then show what it says
agentctl run "..." --policy policy.yaml
```

Compiling is a separate step on purpose. Every error a policy can contain —
an undefined pool, a daily cap below the per-task cap, a misspelled effect
class — surfaces there, where you are watching, rather than mid-run where the
only safe response is to stop. A typo like `desctructive` would otherwise
compile into an artifact where `DESTRUCTIVE` has no rule at all, and the file
would still read like protection.

The cap is enforced *before* the run starts, because a budget check that runs
after the work is an audit:

```
refusing to start: budget exceeded: $1.5000 of $1.00 (daily)
```

### When something blocks

The gate fails closed when it cannot tell whether an effect happened. That
needs a human, so it needs an interface:

```bash
agentctl status                       # what is in the ledger
agentctl blocked                      # effects awaiting a decision
agentctl show <tool_call_id>          # everything known about one
agentctl resolve <id> --landed        # it did happen; do not re-run it
agentctl resolve <id> --retry         # it did not; allow a retry
```

### Checking usage

```bash
agentctl ingest hook_telemetry.json   # load Seam A telemetry
agentctl cost --by-deployment         # spend, with pricing coverage
agentctl cost --conversation <id>     # cost per completed task
```

LiteLLM reports `0.0` for endpoints it cannot price, so a total is never shown
without the share of calls it actually covers. `$0.0042 + unknown (1/3 priced)`
is the honest answer, and the ledger will not print a bare number instead.

There is no "probably fine" — `resolve` requires an explicit choice.

---

## How it works

Three seams with unequal powers, and that inequality is the whole design:

| Seam | Where | Can block | Can substitute |
|---|---|---|---|
| **A** | LiteLLM `CustomLogger` | yes | n/a |
| **B** | Event callback + `block_action` | yes | **no** |
| **C** | `ToolDefinition.executor` wrap | yes | **yes** |

Seam C also stamps idempotency keys — it is the only place a call can be
modified before it executes, which is what makes remote effects retry-safe.

Every decision is made by the gate and enforced at Seam B. **Seam C is not a
second gate** — it exists only to honour the one verdict Seam B cannot deliver:
handing back a recorded result instead of a refusal.

The consequence is graceful degradation. Lose Seam C and the system still fails
closed correctly; it only loses clean resume.

```
AGENT HARNESS ──▶ [Seam B: block] ──▶ [Seam C: substitute] ──▶ tool
      │                   │
      │            EFFECT LEDGER   SQLite · WAL · fsync · fenced
      ▼
LLM DATA PLANE ──▶ providers
      │  telemetry
      ▼
CONTROL PLANE   out-of-band · may fail
```

Full reasoning: [`docs/0008`](docs/0008-system-architecture-v1.md).
Diagrams: [`docs/0011`](docs/0011-request-flow-architecture.md).

---

## What it does not do yet

Stated plainly, because a safety layer that oversells itself is worse than none:

- **No sandbox.** `execute_bash` runs on the host. The capability matrix stands
  in for one, and a 75-command corpus keeps it honest (`docs/0026`) — but it is
  regex over a command string, not a shell parser, and an interpreter
  (`python -c "..."`) is opaque to it by construction. Not enough for untrusted
  tasks. Listed first because it is the limitation the others assume away.
- **`EXTERNAL` effects need an idempotency key.** With one declared, a retry is
  safe (`docs/0020`). Without one — `send_email` and friends — they still fail
  closed, correctly: there is no safe retry.
- **Only two effect kinds are chaos-tested** (git commit, file append). The
  nine crash points are covered for those; `EXTERNAL` is tested separately.
- **A non-compliant remote voids the guarantee.** We trust the server to honour
  the key, and nothing local can detect that it did not.
- **Single process.** Fencing is implemented and tested; multi-host is not
  exercised.
- **No cache affinity, no dashboard.** The policy compiler landed in M7;
  `pools` and `tiering` are declarations the LiteLLM proxy would act on,
  not things `agentctl run` routes by (`docs/0030` §6).
- **One real provider only.** Verified against OpenRouter free-tier models
  (`docs/0023`); it found two real bugs on the first attempt. Anthropic's
  `/v1/messages` path and paid pricing coverage remain untested.

---

## Repository

```
agentctl/         the code
  kernel/         in-band, must not fail. No network, no harness imports.
  control/        out-of-band, may fail. Never imported by the kernel.
  adapters/       harness-specific. The portability cost lives here.
docs/             the numbered document stream. Highest number is newest.
experiments/      reproducible crash experiments, zero cost
tests/            623 tests, including the nine-point chaos suite
verify.py         one command that proves all of the above
```

The kernel/control boundary is enforced by a test
([`tests/test_boundaries.py`](tests/test_boundaries.py)). That single test is
what stops the architecture rotting.

**Start with [INDEX.md](INDEX.md)** — every document, numbered, newest last.
[`docs/0001`](docs/0001-project-charter.md) is the charter,
[`docs/0009`](docs/0009-open-questions-register.md) says what is still open.

---

## Method

Research before building. Falsify before committing. Every component got a
BUILD / CONFIGURE / SKIP verdict backed by primary sources before any code was
written — and Phase 0 deleted two components and downgraded two more, which was
the point of running it.

Every milestone so far has been finished by a bug only *execution* could find:
cp1252 output on Windows, a crashed process holding its own lease, CRLF
breaking the append probe, and an observation shape that validated on
assignment then failed three components later. None were visible by reading.

That is why `verify.py` costs nothing to run.

---

## A note on this repository's location

This is deliberately its own git repository. It was developed inside a
directory whose *parent* was already a repo with an unrelated remote, and
keeping it separate is what stopped its files being swept into that one.

If you clone into a similar layout, check `git rev-parse --show-toplevel`
before your first commit. The git probe learned the same lesson the hard way
(`docs/0019`): it now records the toplevel it was configured with and refuses
to act on a different one.

---

## License

MIT. See [LICENSE](LICENSE).
