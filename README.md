# HandCode

[![CI](https://github.com/csdeepak/HandCode/actions/workflows/ci.yml/badge.svg)](https://github.com/csdeepak/HandCode/actions/workflows/ci.yml)

**HandCode keeps a coding agent's work safe across crashes, restarts and
provider switches.** Its command is `agentctl`.

When an agent's process dies in the middle of a task and you resume it, the
agent framework re-runs whatever was in flight, so a commit can happen twice.
agentctl records every action before it runs. A resumed run never repeats one
that already happened, and when agentctl cannot tell whether it did, it stops
and asks you instead of guessing.

It wraps the [OpenHands](https://github.com/OpenHands/software-agent-sdk)
agent SDK and works with any provider LiteLLM supports, free tiers included.

## See it in a minute

```bash
agentctl demo          # no API key, no network, $0
```

```
  1. Plain OpenHands, no agentctl
     the agent committed, then its process was killed ... 1 new commit
     resumed ............................................ 2 new commits   <- the same commit, twice

  2. With agentctl
     the agent committed, then its process was killed ... 1 new commit
     resumed ............................................ 1 new commit    <- once
     the ledger: the commit is OBSERVED (git probe: LANDED) · 0 waiting on you
```

Real git, real process death and the real SDK. Only the model is scripted,
which is what makes it free and identical on every OS.

## Quickstart

Python 3.12+, `git`, and one API key (a free OpenRouter or Gemini key works).

```bash
git clone https://github.com/csdeepak/HandCode && cd HandCode
python3 -m venv .venv && source .venv/bin/activate     # Windows: see guide/quickstart.md
pip install uv && uv pip install -e ".[openhands]"     # uv: seconds, where pip takes minutes

agentctl demo                                          # see what it is for
agentctl init                                          # one key, one checked default model
cd ../your-project
agentctl run "fix the failing date test" --accept "python -m pytest -q"
```

Every run ends with a report of what was checked, what changed, what it cost,
and what needs you:

```
  outcome     PASS   `python -m pytest -q` exited 0 (run by agentctl after the agent finished)
  changed     1 file  +5 -1
  used        9 requests · 43.7K tokens · $0.00 (free-tier model) · 12s
  actions     8 actions: 3 reads, 3 file writes, 2 commands
  needs you   nothing
```

The **[user guide](https://github.com/csdeepak/HandCode/blob/main/guide/README.md)** covers the
[quickstart](https://github.com/csdeepak/HandCode/blob/main/guide/quickstart.md) step by step (Windows included),
[concepts in plain words](https://github.com/csdeepak/HandCode/blob/main/guide/concepts.md),
[troubleshooting by the exact text you see](https://github.com/csdeepak/HandCode/blob/main/guide/troubleshooting.md), and an
[FAQ](https://github.com/csdeepak/HandCode/blob/main/guide/faq.md).

## What it protects you from

| | Without agentctl | With it |
|---|---|---|
| The process dies mid-action, then you resume | The in-flight action runs again | It runs at most once. If it already landed, the agent gets its result back |
| You cannot tell whether something happened | It is guessed | It is checked (did HEAD move?), or you are asked |
| Ctrl-C, a closed laptop, a killed terminal | Start again | `agentctl resume` |
| A rate limit mid-task | The run dies | `--wait 30m` waits it out and resumes, or `--pool` routes to another provider |
| A dangerous command with nobody watching | It runs, or the run hangs on a prompt | It is queued for `agentctl approve` / `deny` |
| "Done!" from the agent | Taken on trust | `--accept` runs your tests and reports PASS or FAIL |
| Two terminals resuming the same run | Both drive it | The second is refused and told which process holds it |

**What it does not do:** it is not a sandbox. Commands run on your machine.
agentctl stops actions repeating and asks before dangerous ones, but it does
not contain what an allowed command does. For a task you would not trust your
shell with, run it in the [container image](https://github.com/csdeepak/HandCode/blob/main/guide/quickstart.md#6-run-it-in-a-container-recommended-for-tasks-you-would-not-trust-your-shell-with),
where only the mounted repository is reachable
([concepts](https://github.com/csdeepak/HandCode/blob/main/guide/concepts.md#what-agentctl-does-not-do)).

**On GitHub.** Type a task in your repository's Actions tab and get a pull
request back, with the report as its description. Your key stays in your
repository's secrets, and the job that runs the agent holds no token that can
write ([the GitHub Action](https://github.com/csdeepak/HandCode/blob/main/guide/github-action.md)).
It has run on GitHub with a scripted model; a run with a real model is next.

**Status.** 879 tests, including a chaos suite that kills the process at ten
points in the protocol, plus `verify.py`'s end-to-end crash experiments. All
run at no cost, on Linux and Windows in CI. Every feature here has also been
run at least once against a real provider, except the GitHub Action (above). The design history, with what was
measured and what was found, is the numbered [`docs/`](https://github.com/csdeepak/HandCode/blob/main/INDEX.md) stream.

---

# Reference

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
| Ledger state | `BLOCKED` | `COMMITTED` | `OBSERVED` |
| Human needed | yes | no | no |
| Agent receives | rejection | rejection | **the result** |

---

## Verify it yourself

Requires **Python ≥ 3.12** (the OpenHands SDK does) and `git` on PATH. On an
older Python the install fails with a long list of `Requires-Python >=3.12`
lines that never names the cause, so check first.

**Windows** (PowerShell):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,openhands]"
python verify.py
```

Clone into a short path such as `C:\src\HandCode`. One file the install
unpacks sits 139 characters deep inside `.venv`, so a clone path longer than
about 120 characters hits Windows' 260-character limit and pip fails partway
(`docs/0044` N3).

**macOS / Linux:**

```bash
python3 -m venv .venv          # Ubuntu: sudo apt install python3.12-venv first
source .venv/bin/activate
pip install -e ".[dev,openhands]"
python verify.py
```

**Zero cost** — everything runs against a local mock provider. No API key, no
network, no tokens. Takes about five minutes. With this install, two of the
ten checks (Seam A and the full stack) are **SKIPPED**, because they need the
proxy extra below; that is expected, and `verify.py` says how to run them.

If a dependency has since shipped something incompatible, install the exact set
that is known to pass:

```bash
pip install -e ".[dev,openhands]" -c constraints.txt
```

CI runs both forms on Linux and Windows, and runs `verify.py` itself — so the
badge above means the correctness claim reproduces on a machine that is not
mine, which is the only version of that claim worth anything.

### The proxy extra needs two steps (only if you run the proxy yourself)

`agentctl run --pool` and `agentctl proxy up` do not need any of this: they
keep LiteLLM in a separate environment of their own. The steps below are for
running the full-stack checks in `verify.py`, or a proxy by hand.

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

**One key is enough to start.** A daily cap on it stops work until it resets;
a key at a **second provider** survives that, and survives an outage too:

```
OPENROUTER_API_KEY=sk-or-v1-...      # one provider
GEMINI_API_KEY=...                   # a second provider
```

Extra keys at the *same* provider are accepted with any suffix (`_2`, `_WORK`)
and each becomes its own deployment in the pool (`docs/0033`). **Whether that
is a separate quota is unverified**: OpenRouter's own limits page says extra
accounts do not change rate limits. Pooling several free accounts may also be
against a provider's terms. Check both before relying on it (`docs/0042`
§4.C). `agentctl dash` says which state you are actually in.

## Use it

```bash
agentctl init                                # once: one key, one checked default model
cd myproject
agentctl run "add type hints to utils.py"    # no flags needed
```

`init` uses a key you already have in the environment or a keys file, or asks
for one and stores it in `~/.agentctl/keys.env`, outside every repository and
never echoed. It then sends **one** completion and records the model that
actually answered in `~/.agentctl/config.toml`. A paid provider is not called
unless you pass `--check-paid`.

`run` takes its model from `--model`, then `AGENTCTL_MODEL`, then that config,
then the first provider you hold a key for, and prints which one it used.

Every run ends with a report:

```
  outcome     PASS   `python -m pytest -q` exited 0 (run by agentctl after the agent finished)
  changed     1 file  +5 -1
                stats.py  +5 -1
  agent said  "The median function in stats.py has been fixed to correctly handle..."
  used        9 requests · 43.7K tokens · $0.00 (free-tier model) · 12s
  actions     8 actions: 3 reads, 3 file writes, 2 commands
  needs you   nothing
```

- **`outcome` is only what was checked.** Pass `--accept "<command>"` (your
  test suite, usually) and agentctl runs it itself once the agent has
  finished, outside the agent's loop: exit 0 is PASS. Without it the outcome
  reads `not checked`, never an implied success.
- **`changed`** is measured with git against where the run started, commits
  included.
- **`used`** says what a cost figure can be trusted for. Free-tier models read
  `$0.00`, and list prices that a free key is not billed are labelled as such.
- **The exit code is 0** when nothing failed a check and nothing is waiting on
  you, and 1 otherwise.

```bash
agentctl doctor --workspace ./myproject     # check everything BEFORE you spend
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
ledgered. Crash it and re-run with the conversation id the run printed at the
start. Work already done is not repeated:

```bash
agentctl run "" --workspace ./myproject --resume <conversation-id>
```

The task is `""` because the conversation already holds it.

Only one process may drive a conversation. If the run that held it crashed on
this machine, `--resume` sees that it is gone and takes over. If it is still
running, `--resume` refuses and names it, because two drivers of one
conversation is exactly what the ledger exists to prevent. `--takeover`
overrides that, for a holder you know is dead but this machine cannot check
(`docs/0046`).

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

"Twice" means *by replay*. Once a result — success or failure — is in the
history the model reads, an identical later call is the model deciding to run
it again: the edit, test, re-test loop. It runs. A crash still never causes a
repeat (`docs/0045`).

### Or embed it

```python
from agentctl.adapters.openhands import protect

guard = protect(
    ledger="./ledger.db",
    conversation_id=str(conversation_id),
    tools={"commit": CommitTool},      # gated at Seam C
    repo_root="./workspace",           # for the git probe
    takeover=previous_holder_is_dead,  # NEVER for a live one (docs/0046)
)

conv = Conversation(agent=agent, callbacks=[guard.seam_b], ...)
guard.attach(conv)                     # required, or the gate is inert
```

Omit `tools` to run Seam B only: still correct, but an already-landed effect is
blocked rather than resumed cleanly.

### Failing over

```bash
agentctl run "..." --pool               # starts the managed pool if it is not running
agentctl proxy status                   # running? answering? where is its log?
agentctl proxy down                     # stop it
```

`--pool` (or `agentctl proxy up`) runs LiteLLM in **its own environment**,
`~/.agentctl/proxy-env`, created the first time (a few minutes) and reused
after that. Your install never needs the proxy extra.
- It verifies every model id with one completion and leaves out what cannot
  serve, naming it.
- It runs in the background and outlives the command that started it.

`agentctl proxy --out ./proxy` still writes a config and start scripts, if you
would rather run the proxy yourself (`docs/0047`).

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

### Stopping, coming back, and deciding

Every run is recorded in `~/.agentctl/runs.db`, so none of these needs a path
or an id copied out of the scrollback (`docs/0049`):

```bash
agentctl status                       # recent runs: done, died, paused, waiting on you
agentctl resume                       # continue the last run here (or: resume <id prefix>)
agentctl blocked                      # everything waiting on you, in every workspace
```

- **Ctrl-C** pauses after the current step, and the report says how to
  continue. A second Ctrl-C stops at once. Either way nothing is lost: the
  ledger reconciles whatever was in flight on resume.
- **A run that died** (a killed terminal, a closed laptop) shows as `died`,
  and `agentctl resume` continues it.
- **`--wait 30m`** on `run` or `resume` waits out a rate limit and resumes
  the same conversation, up to that long and at most five times. Without it,
  the run ends with the command that continues it.

**Approvals.** A dangerous action (`rm -rf`, or a write outside the
workspace) asks first. With nobody at a terminal, it is **queued** rather
than refused: the agent is told it is waiting and not to repeat it.

```bash
agentctl approve <id>                 # let it run: the agent is told on resume
agentctl deny <id>                    # refuse it: likewise
agentctl resume                       # the approved action runs without asking again
```

**Unknown outcomes.** The gate fails closed when it cannot tell whether an
effect happened. That is a different question, with a different command:

```bash
agentctl show <id>                    # everything known about one
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

Full reasoning: [`docs/0008`](https://github.com/csdeepak/HandCode/blob/main/docs/0008-system-architecture-v1.md).
Diagrams: [`docs/0011`](https://github.com/csdeepak/HandCode/blob/main/docs/0011-request-flow-architecture.md).

---

## What it does not do yet

Stated plainly, because a safety layer that oversells itself is worse than none:

- **No sandbox.** `execute_bash` runs on the host. The capability matrix stands
  in for one, and a 75-command corpus keeps it honest (`docs/0026`) — but it is
  regex over a command string, not a shell parser, and an interpreter
  (`python -c "..."`) is opaque to it by construction. Not enough for untrusted
  tasks. Listed first because it is the limitation the others assume away.
- **`EXTERNAL` effects need an idempotency key.** With one declared, a retry is
  safe (`docs/0020`). Without one — `send_email` and friends — a crash with the
  outcome unknown still fails closed: there is no safe retry. But a model that
  *saw* a failure and retries it is not stopped (`docs/0045` §4).
- **Only two effect kinds are chaos-tested** (git commit, file append). The
  ten crash points are covered for those; `EXTERNAL` is tested separately.
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
  gha.py          the GitHub Action's logic; standard library only
action.yml        the GitHub Action's run job; publish/ is its second job
docs/             the numbered document stream. Highest number is newest.
examples/         a workflow to copy into your repository
experiments/      reproducible crash experiments, zero cost
guide/            the user guide
tests/            879 tests, including the ten-point chaos suite
verify.py         one command that proves all of the above
```

The kernel/control boundary is enforced by a test
([`tests/test_boundaries.py`](https://github.com/csdeepak/HandCode/blob/main/tests/test_boundaries.py)). That single test is
what stops the architecture rotting.

**Start with [INDEX.md](https://github.com/csdeepak/HandCode/blob/main/INDEX.md)** — every document, numbered, newest last.
[`docs/0001`](https://github.com/csdeepak/HandCode/blob/main/docs/0001-project-charter.md) is the charter,
[`docs/0009`](https://github.com/csdeepak/HandCode/blob/main/docs/0009-open-questions-register.md) says what is still open.

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

MIT. See [LICENSE](https://github.com/csdeepak/HandCode/blob/main/LICENSE).
