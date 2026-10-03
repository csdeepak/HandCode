---
Number:        0050
Title:         Try It Before You Trust It
Type:          DECISION
Status:        ACCEPTED
Created:       2026-10-04
Supersedes:    —
Superseded-by: —
Depends-on:    0014, 0029, 0043, 0044, 0049
---

# 0050 — Try It Before You Trust It

`0043` Phase 5, the last phase of the plan. It covers `agentctl demo`, a user
guide, and a README that opens with what a newcomer needs.

---

## 1. `agentctl demo`

```
  1. Plain OpenHands, no agentctl
     the agent committed, then its process was killed ... 1 new commit
     resumed ............................................ 2 new commits   <- the same commit, twice

  2. With agentctl
     the agent committed, then its process was killed ... 1 new commit
     resumed ............................................ 1 new commit    <- once
     the ledger: the commit is OBSERVED (git probe: LANDED) · 0 waiting on you
```

**What it runs.** Two arms, each in its own process:
1. Make a real `git commit`.
2. Kill the process (`kill`, not a shutdown) inside the window after the
   commit lands and before its result is recorded.
3. Resume, and count the commits.

The bare arm is plain OpenHands. The guarded arm adds agentctl through
`protect()`, the public embed API the README documents, not a demo-only path.
Its resume takes over the dead holder's lease the way `0046` describes.

**What is scripted, and why.** Only the model is scripted: a local mock that
asks for the commit once and then stops. A recorded cassette of a real model
was the obvious alternative, and could not work:
- **It is platform-bound.** The SDK writes the shell name into the system
  prompt, so a Windows recording misses on turn 0 on macOS or Linux
  (`0029` §6), where most users are.
- **Exact replay needs byte-identical tool output.** Commit hashes, `ls -la`
  timestamps and pytest timings change on every run, and each change is a
  miss, which is the point of a cassette (`0029`).

The mock makes the demo free, offline, deterministic and the same on every OS,
and the demo says plainly that the model is scripted.

**It cannot claim what it did not show.**
- It exits 0 only if the bare arm made at least two commits and the guarded
  arm exactly one.
- If the guarded arm ever duplicates, it prints *"The demo did NOT show what
  it claims"* with the logs, and exits 1. A test pins that branch.
- A broken install reports as a broken demo, never as a result.

**Self-contained.**
- It uses its own temporary repositories with a local git identity, so it
  neither needs nor touches the user's.
- It keeps a private run index, so its runs do not appear in `agentctl
  status`.
- It cleans up unless `--keep` is given.
- It ships in the package (`agentctl/demo/`), not in `experiments/`.

**Evidence.**

| | |
|---|---|
| Dev venv (SDK 1.45.0) | exit 0, 52 s: bare 1→2, guarded 1→1, `OBSERVED (git probe: LANDED)` |
| **From an installed wheel**, outside the repository, SDK 1.50.1 (what a fresh install resolves) | exit 0, 56 s, same result |
| `tests/test_demo.py` | Runs it end to end and asserts the counts from the repositories, not from its printout, so CI runs the demo on Linux and Windows |
| Guard that caught a defect | `test_tool_concurrency_pin` failed the first version, which built an `Agent` directly and so bypassed the `tool_concurrency_limit=1` pin (`0038` §4.3). The demo now goes through `runner._build_agent` like everything else |

## 2. The user guide, `guide/`

Separate from `docs/`, which stays the project's memory. `CONVENTIONS.md` now
says so: the guide describes the tool as it is, and is edited in place.

| Page | What |
|---|---|
| `quickstart.md` | Install on Windows and Unix, `demo`, `init`, a run with `--accept`, what to do when a run stops, the pool |
| `concepts.md` | The ledger's four answers in a table; kinds of action; the two questions (approve vs resolve); one driver; what it does **not** do |
| `troubleshooting.md` | Indexed by the **exact text** agentctl prints, taken from the code rather than paraphrased |
| `faq.md` | Cost, privacy, multiple keys (with the unverified-premise caveat), sandboxing, where everything lives |

Two messages changed to match what the guide says to do:
- The rate-limit advice used to say `run offline: agentctl run '' --replay
  <cassette>`, which re-runs a recording and does not continue the task. It
  now says `--wait 30m` or `--pool`.
- The overload advice pointed at `--base-url` with a hand-run proxy. It now
  says `--pool`.

## 3. The README

It now opens with:
1. what agentctl is, in a paragraph;
2. the demo;
3. a quickstart;
4. a "what it protects you from" table;
5. the not-a-sandbox limit, stated up front.

Everything that was there before is kept, under `# Reference`: the original
problem example, `verify.py`, keys, every command, the seams, the
limitations, method, location. Nothing was deleted.

## 4. What `0043` set out to do, and where it stands

| Promise (`0043` §1) | Status |
|---|---|
| P1: install to first run in 3 commands with one key | `init` + flagless `run` (`0047`). Live: 16 s + 57 s after install. **Install itself is the open cost**: 4–13.5 minutes measured, and the PyPI name is undecided |
| P2: every run says did it work, what changed, what it used, what needs you | `0048`, live |
| P3: interruptions cost nothing; `agentctl resume` | `0049`, live (Ctrl-Break, died, queued approval) |
| P4: normal work does not trip the safety layer | `0045` (I-01), live |
| P5: never hangs on a prompt, never silently refuses | `0049`, live |
| P6: try it with no key and no cost | This document |

**Not done, and not mine to do.**
- **D3/D4, the package name.** `agentctl` is taken on PyPI (`0047` §5).
- **Publishing**, which needs the owner's PyPI account.
- **D5, the second person.** `0043`'s Phase 0 and 5 exit criteria both ask
  for someone who has not read the repository. Nothing here substitutes for
  that, and nobody has done it yet.

## 5. Left open

- **The install time.** It was 4 m 20 s in Phase 0 and 13.5 minutes for a
  clean wheel install in `0047`. Neither was investigated. It is now the
  largest single cost against P1.
- **`dash` still reads one ledger** (`0049` §5).
- **The `pip install` hazard** is unchanged (`0047` §5; for I-26).
- **`--wait` has not been run against a real rate limit** (`0049` §2).
