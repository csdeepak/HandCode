---
Number:        0049
Title:         Stopping, Coming Back, and Deciding
Type:          DECISION
Status:        ACCEPTED
Created:       2026-10-04
Supersedes:    —
Superseded-by: —
Depends-on:    0013, 0042, 0043, 0044, 0046, 0048
---

# 0049 — Stopping, Coming Back, and Deciding

`0043` Phase 4, with `0042` I-17 (the run index), I-06 (approvals that do not
stop the run) and the wait-only half of I-05.

**The test, from `0043`:** whether a run is killed, left unattended or
rate-limited, it ends with **one** command that continues it.

---

## 1. What changed

| | Before | After |
|---|---|---|
| Finding a run | Each run wrote `<ws>/.agentctl/ledger.db`; `status`, `blocked`, `resolve` and `dash` read `./ledger.db` (`0044` F4) | `~/.agentctl/runs.db` records every run attempt. `status` lists recent runs; `blocked`, `show`, `resolve`, `approve` and `deny` search every indexed ledger. An explicit `--ledger` still wins |
| A run that died | Invisible | A `running` row whose process is gone shows as **died**. Writing the start first is what makes a missing end evidence |
| Continuing | `run "" --workspace X --resume <uuid>` (F5) | **`agentctl resume`**: the last run here, else anywhere, or `resume <prefix>`. It keeps the model and the pool, and an ambiguous prefix is refused |
| Ctrl-C | A traceback; state wherever it fell | The first Ctrl-C pauses after the current step, through the SDK's `pause()`. The second stops at once. The report says `paused by you. Continue: agentctl resume <id>` |
| A dangerous action, no terminal | `input()`: hung when unattended, EOF-refused when detached (F7) | **Queued**: recorded BLOCKED and awaiting approval, and the agent is told it did not run and not to repeat it. A closed terminal mid-question also queues |
| Answering it | — | `agentctl approve` or `deny <id>`. The record becomes FAILED ("did not run"); the decision is kept by intent hash. On `resume` the agent is told; an approved action runs **once** without asking again; a denied one never runs |
| A refusal at the terminal | Left an INTENT record, which a later identical call would treat as a crash to reconcile | Recorded FAILED, "refused by the operator" |
| A rate limit | The run ended with advice | It ends with `agentctl resume <id>`. With **`--wait 30m`** it waits for the provider's reset time (or backs off 60 s, 120 s, … when there is none) and resumes the same conversation, bounded by the duration and by five attempts |
| The report's last line | A 3-flag command with a full UUID | `resume <id8>`, or `then agentctl resume …` when approvals are waiting |

**Two questions, two commands.** "Did this ambiguous effect land?" is answered
with `resolve --landed/--retry`. "May this dangerous action run?" is answered
with `approve`/`deny`. `blocked` shows them separately, and `approve` refuses
an effect that is not awaiting approval, pointing at `resolve`.

## 2. Live evidence (the `0041` rule)

**Unattended approval.** A run with no terminal on stdin; the task was
"delete the stale `build/`".
- **Run.** `rm -rf build` was **queued**, and `build/` was untouched. The
  agent replied *"I've queued the command `rm -rf build` for your
  approval"*. The report listed it with both commands and `then agentctl
  resume 85844aa8`.
- **`agentctl status`** showed the run as `needs_you` and "1 action(s) need
  you".
- **`agentctl approve call-b75e533`** answered it.
- **`agentctl resume`** (no arguments) printed *"approved earlier by you:
  bash: rm -rf build"*. The deletion ran with no prompt, `build/` was gone,
  the report said "needs you nothing", and it exited 0.

**Ctrl-C.** `CTRL_BREAK_EVENT` was sent to a real run, in its own process
group, partway through a five-file task, while `a.txt` was being written.
- The run printed *"pausing after the current step"*, finished the step in
  flight (`b.txt`), and reported *"paused by you. Continue: agentctl resume
  0b5a9f8a"*.
- **`agentctl resume`** wrote `c.txt` through `e.txt`, nothing twice, and
  exited 0.

**Not shown live:** `--wait`. Forcing a real rate limit means spending a
day's quota on purpose. It is unit-tested for the reset header, the doubling
backoff, the duration bound and the five-attempt bound.

## 3. Found on the way

- **On Windows, a stdin redirected from `NUL` reports itself as a terminal.**
  So the wrapper asked `allow? [y/N]`, read EOF, and fell back to queueing,
  which is why EOF queues rather than refuses. A pipe reports "not a
  terminal" and queues directly. The stray prompt is cosmetic.
- **The Bash tool used to drive this work collapses backslashes** in inline
  heredocs. Two edits produced a real line break inside an f-string. Both
  were caught by parsing before any test ran. Edits with escapes now go
  through script files.

## 4. Evidence

| | |
|---|---|
| `tests/test_interruptions.py` | 27 tests. The index: start/end, died, workspace preference, prefix ambiguity, never breaking a run. Approvals through a real gate and ledger: queue, three re-issues alias to **one** record, approve runs once, deny never, refusal recorded, EOF queues, the resume message is told once. The CLI with no paths: `approve`, a refused `approve` of a non-awaiting effect, `blocked`, `status`, `resume`. `--wait` in five cases. Ctrl-C pause, then stop, then handler restored |
| Updated | `test_paths.py`: the prompt tests say they are interactive. `test_report.py`: the new needs-you lines |
| Suite | 820 passed, 2 skipped. `verify.py` 10/10 |

## 5. Left open

- **`dash` still reads one ledger.** `status` covers "what happened while I
  was away" for now; the dashboard should iterate the index (I-17's other
  consumer, then I-19).
- **No notification hook** for a queued approval. Both analysts said defer
  it.
- **An approved action's pre-state is not recaptured** at execution
  (`0042` I-06's concern). It runs through the gate as a fresh call, so
  `write_intent` fingerprints it then, which covers the case for these
  probes.
- **The `pip install` hazard from `0047`** is unchanged. Package installs are
  still not "dangerous", so they do not queue. For I-26.
- **Phase 5 of `0043` is next**: `agentctl demo` (a recorded crash-and-resume
  at $0, no key) and a user guide.
