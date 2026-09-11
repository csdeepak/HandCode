# AI Agent Control Plane

Making long-running LLM agent work **recoverable, measurable, and
cost-efficient** across changes of provider, account, and model.

> The model/provider endpoint can change; the logical agent work must remain
> recoverable, measurable, and cost-efficient.

**Status: the correctness core works.** M0, M2a, M4 and M2b are complete and
verified. 184 tests — including a nine-point chaos suite with real process
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

---

## Use it

```bash
agentctl run "add type hints to utils.py" --workspace ./myproject
```

Real tools (bash, read, write), a real model, every effect classified and
ledgered. Crash it and re-run with `--resume <id>`: work already done is not
repeated.

Two safety properties, deliberately separate — the **gate** stops an effect
happening *twice*; `--confirm-destructive` (on by default) stops a dangerous one
happening *at all* without a human saying yes.

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

- **`EXTERNAL` effects need an idempotency key.** With one declared, a retry is
  safe (`docs/0020`). Without one — `send_email` and friends — they still fail
  closed, correctly: there is no safe retry.
- **Only two effect kinds are chaos-tested** (git commit, file append). The
  nine crash points are covered for those; `EXTERNAL` is tested separately.
- **A non-compliant remote voids the guarantee.** We trust the server to honour
  the key, and nothing local can detect that it did not.
- **Single process.** Fencing is implemented and tested; multi-host is not
  exercised.
- **No policy compiler, no cache affinity, no dashboard.** M6 onward.
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
tests/            184 tests, including the nine-point chaos suite
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
