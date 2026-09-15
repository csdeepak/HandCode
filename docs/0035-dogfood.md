---
Number:        0035
Title:         The Agent Fixed Its Own Repository, and Broke the Diff Doing It
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-15
Supersedes:    —
Superseded-by: —
Depends-on:    0026, 0031, 0034
---

# 0035 — The Agent Fixed Its Own Repository

`agentctl run` pointed at this codebase, given a real documented gap, graded
objectively. **PASS** — and the run exposed a defect in the tool it was using.

**497 tests passing** (was 480). Fix in `runtime/tools.py`.

---

## 1. The task, and why it was self-grading

`docs/0026` §6 admitted: *"Windows shells are unhandled. No `Remove-Item`, no
`del`, no `rd /s`."* Still true — all four classified `EXTERNAL`, so
`--confirm-destructive` never fired for any of them.

The harness checks the four become `DESTRUCTIVE`, **and** that `dir`,
`Get-ChildItem`, `ls`, `cat` and a redirect keep their current classes, **and**
that the other 413 tests still pass. No judgement call anywhere: a "fix" that
makes everything destructive protects nothing and would otherwise sail through.

Graded before the run: **FAIL on exactly the four.**

## 2. What it produced

```yaml
- match: '^\s*(del|erase)\b'        class: DESTRUCTIVE
- match: '^\s*(rd|rmdir)\b'         class: DESTRUCTIVE
- match: '^\s*Remove-Item\b'        class: DESTRUCTIVE
- match: '^\s*format\s+[A-Za-z]:'   class: DESTRUCTIVE
```

Eight lines, in the right section, matching the file's style. It added `erase`
and `rmdir` — aliases the task did not name — and left the listing commands
alone. All ten checks green, 413 tests still passing.

A free-tier model, $0.00, on a codebase it had never seen.

## 3. The diff was 149 lines for an 8-line change

`git diff` showed the entire file rewritten. `write_file` writes `\n`; the
committed file used `\r\n`. Every line counted as changed.

That is not cosmetic. It makes a review impossible, it buries the real change,
and on any repository checked out on Windows **every edit the agent makes looks
like a full rewrite** — so nobody can tell an eight-line fix from a
reformatting accident.

`WriteExecutor` now reads the file's existing convention and preserves it. The
dominant ending wins rather than the first one seen, so a file with a couple of
stray endings does not flip wholesale to match its own typo.

Content is normalised to `\n` **first**, in both directions. Only converting
toward CRLF leaves an LF file holding whatever the model happened to send, and
replacing `\n` without stripping `\r` first turns `\r\n` into `\r\r\n`. The
second case was in the first version of the fix, and the test caught it.

## 4. The ledger recorded a failure as a failure

```
COMMITTED  IDEMPOTENT_WRITE   1
COMMITTED  PURE_READ          3
FAILED     PURE_READ          1
```

That `FAILED` is `docs/0031` §9 working in production. Before that fix a tool
that ran and failed was recorded `COMMITTED`, and a resume would have treated
work that never happened as done.

First time the correctness core has been observed doing its job on a real task
rather than in a chaos harness.

## 5. What dogfooding was worth

The milestones, the chaos suite, CI on two operating systems and 480 tests did
not surface the line-ending defect. One real edit did, immediately, and it
would have affected every subsequent edit.

This is the same lesson as `docs/0031` §10 and it keeps being true: **a suite
built from the inside tests the parts you thought of.** The tests drove
`write_file` with synthetic content into fresh files, and a fresh file has no
existing convention to preserve, so the question never came up.

## 6. M6 caught the fix

`verify.py` dropped from 10/10 to `INCONCLUSIVE` on the replay check, naming
`turn 2: message 5 (tool)`. The write observation the model reads had gone from
`written (107 bytes)` to `written (111 bytes)` — the four carriage returns this
fix restores.

That is record/replay doing the job it was built for, on a change nobody
flagged as risky. 497 tests passed; only the cassette noticed the agent now
sees something different. It was re-recorded and committed with the fix.

## 7. Consequences

- `docs/0026` §6 → the Windows gap is closed, and the corpus grew by ten cases
  covering it. 90 commands now.
- `docs/0012` §6 → new rule: a tool that rewrites a file must preserve what it
  did not change, line endings included.
- The eight rules in `tools.yaml` were written by the agent. The line endings
  were restored by hand before committing, because the fix for that landed in
  the same session.
