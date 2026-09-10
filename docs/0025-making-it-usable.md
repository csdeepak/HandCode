---
Number:        0025
Title:         Making It Usable — Real Tools and `agentctl run`
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-11
Supersedes:    —
Superseded-by: —
Depends-on:    0018, 0021, 0023
---

# 0025 — Making It Usable

Everything in `experiments/` proves the system. Nothing in it *used* the system.
`agentctl run` does.

**184 tests passing.** Code: `agentctl/runtime/`.

---

## 1. The gap

`openhands-sdk` is a library, not an application — there is no `openhands`
command anywhere on the system. Every experiment so far drove it with a scripted
toy tool. To do actual work an agent needs real tools, and there were none.

## 2. Why not `openhands-tools`

A dry run showed it would install **55 packages** — browser-use, three model
SDKs, Google API clients — and **downgrade `mcp` below what the SDK needs**,
which is the exact hazard `docs/0021` §7 recorded when `litellm[proxy]` did the
same thing and `pip check` reported nothing.

Three tools written directly cost **zero new dependencies**, and they are
already the names `control/matrix/data/tools.yaml` classifies. The gate became
meaningful the moment they ran:

```
bash        PURE_READ    COMMITTED     <- ls, cat, git status
bash        EXTERNAL     COMMITTED
read_file   PURE_READ    COMMITTED
bash + "rm -rf /x"   ->  DESTRUCTIVE
```

That is the capability matrix reclassifying a single tool per-command, on real
work, exactly as designed. The `bash: {alias: execute_bash}` entry also earned
itself — the SDK normalises the registered name, so the matrix sees `bash`.

## 3. Two bugs, one of them a repeat

**`content` is a reserved field name.** `ReadObservation` declared
`content: str`, shadowing the base `list[TextContent | ImageContent]`. It
validated fine at construction and produced **326 validation errors** later,
during message assembly, in a different component.

That is `docs/0018` §4 C1 verbatim. Documented, then repeated four milestones
later. Writing a rule down is not the same as being unable to break it, so there
is now a test that fails if any `Observation` subclass defines `content`.

**`agent_observation` is not an SDK hook.** The SDK renders an observation
through `to_llm_content`, which reads the base `content` field. Observations
that stored their text anywhere else rendered as `[no text content]`, and the
agent replied:

> *"I couldn't retrieve any contents from utils.py, so I can't safely add type
> hints."*

The model behaved perfectly on empty input. Nothing errored. The tool "worked"
and returned nothing — the same silent-failure shape as `docs/0021` §4 and
`docs/0024`, where the observable outcome looked like a decision.

Every observation now populates `content` through a `make()` classmethod, and
`test_the_model_actually_sees_the_output` asserts `to_llm_content` is non-empty
for each. **It tests what the model sees, not what the object holds.**

## 4. Replay safety is not authorization

Worth stating plainly, because the distinction is easy to lose once a gate
exists and appears to be protecting you:

* The **gate** stops an effect happening *twice*.
* Nothing in the gate stops an effect happening *at all*.

A first-time `rm -rf` is not a replay, so the ledger admits it. `agentctl run`
therefore adds `--confirm-destructive` (**on by default**), which prompts before
a `DESTRUCTIVE` effect executes for the first time. It wraps `guard.gate.guard`
rather than living inside the gate, so the two properties stay separable and the
kernel keeps exactly one job.

## 5. It works

```
$ agentctl run "add type hints to both functions in utils.py" --workspace ./demo

  decisions     {'EXECUTE': 4}
  cache hit     96.34%

- def add(a, b):
+ def add(a: int, b: int) -> int:
- def greet(name):
+ def greet(name: str) -> str:
```

A real model, real files, real edits, every tool call classified and ledgered.

## 6. What it still is not

- **Free-tier models are unreliable.** One run died on *"Upstream error from
  Nvidia: Service temporarily overloaded"*. Point `--base-url` at the LiteLLM
  proxy for a pool with failover — which is what the proxy was built for.
- **Three tools, not a full suite.** No browser, no MCP, no targeted multi-edit.
- **No sandbox.** `execute_bash` runs on the host, in the workspace directory.
  For untrusted tasks that is not enough.
- **Iteration limits bite.** The default is 30; a first attempt with 8 ran out
  mid-task and looked like a failure.

## 7. Consequences

- `docs/0012` §5.1 → `content` is reserved on `Observation` subclasses, and the
  rule is now enforced by a test rather than by memory.
- `docs/0018` §4 → its lesson recurred; the guard is a test, not a note.
- `README` → `agentctl run` is the entry point for real work.
