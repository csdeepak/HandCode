# AI Agent Control Plane

Making long-running LLM agent work **recoverable, measurable, and
cost-efficient** across changes of provider, account, and model.

> The model/provider endpoint can change; the logical agent work must remain
> recoverable, measurable, and cost-efficient.

**Status: the correctness core works.** M0, M2a, M4 and M2b are complete and
verified. 123 tests — including a nine-point chaos suite with real process
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
network, no tokens. Takes about three minutes.

Requires Python ≥ 3.12 (the OpenHands SDK does) and `git` on PATH.

---

## Use it

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

There is no "probably fine" — `resolve` requires an explicit choice.

---

## How it works

Three seams with unequal powers, and that inequality is the whole design:

| Seam | Where | Can block | Can substitute |
|---|---|---|---|
| **A** | LiteLLM `CustomLogger` | yes | n/a |
| **B** | Event callback + `block_action` | yes | **no** |
| **C** | `ToolDefinition.executor` wrap | yes | **yes** |

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

- **`EXTERNAL` effects have no probe.** HTTP POSTs, emails and webhooks still
  fail closed. The idempotency-key probe is unwritten.
- **Only two effect kinds are chaos-tested** (git commit, file append). The
  nine crash points are covered for those; `EXTERNAL` effects are not.
- **Single process.** Fencing is implemented and tested; multi-host is not
  exercised.
- **No cost ledger, no routing, no policy compiler.** M5 onward.

---

## Repository

```
agentctl/         the code
  kernel/         in-band, must not fail. No network, no harness imports.
  control/        out-of-band, may fail. Never imported by the kernel.
  adapters/       harness-specific. The portability cost lives here.
docs/             the numbered document stream. Highest number is newest.
experiments/      reproducible crash experiments, zero cost
tests/            123 tests, including the nine-point chaos suite
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

This is deliberately its own git repository. The parent directory
`C:\Users\csdee\` is itself a repo with an unrelated remote, and keeping this
separate stops its files being swept into that one. Consider also adding
`openhands/` to the home directory's `.gitignore`.
