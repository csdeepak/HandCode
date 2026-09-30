---
Number:        0044
Title:         Phase 0 — What a New User Hits, Measured
Type:          EXPERIMENT
Status:        DRAFT
Created:       2026-10-01
Supersedes:    —
Superseded-by: —
Depends-on:    0041, 0042, 0043
---

# 0044 — Phase 0: What a New User Hits, Measured

`0043` Phase 0 has now run. It used a fresh clone from GitHub, a fresh venv, a
fake home directory with no keys file and no `~/.agentctl`, and **one
OpenRouter key** (the D1 user). The README was followed word for word. At
every stop, the recovery was the one a user would plausibly find.

**Headline.**
- **The product worked.** Two real tasks were done correctly, and a hard-killed
  run resumed with no duplicate commit.
- **Getting there took 17½ minutes and 9 commands.** It hit four dead ends and
  two false "it will not work" verdicts.
- **Both successful tasks ended with exit code 1** and "effect(s) need you".

---

## 1. Setup

| | |
|---|---|
| Machine | Windows 11, PowerShell 5.1, Git Bash; WSL Ubuntu for the Linux leg |
| Source | `git clone https://github.com/csdeepak/HandCode` → `6870711` |
| Installed (unpinned, as the README says) | openhands-sdk **1.50.1**, litellm **1.103.1**, mcp **1.30.0**, fastmcp 3.4.7 |
| Isolation | `HOME` and `USERPROFILE` → an empty scratch directory; key removed for the offline steps |
| Key | `OPENROUTER_API_KEY`, free tier |
| Project | A two-file git repo: `divide()` with no zero check, plus one test |
| Quota used | About 35 requests, counted from the persisted conversations (10 + 25). After Phase 0 the key reports **0 of 50** left for today |

## 2. Timeline

| Clock | Step | Result |
|---|---|---|
| 02:29 | `git clone` | 2 s. GitHub is **2 commits behind** local `main` (N1) |
| 02:29 | README: `python -m venv .venv && .venv/Scripts/activate` | `python` is 3.11 on this PATH; the venv is created with `bin/`, not `Scripts/` (MSYS2 Python, specific to this machine) |
| 02:30 | README: `pip install -e ".[dev,openhands]"` on 3.11 | Fails after a wall of `Requires-Python >=3.12` lines, and **never says "your Python is too old"** (N2) |
| 02:30 | Recovery: `py -3.12 -m venv` | OK |
| 02:30–02:34 | Install | **Fails after 3m44s**: Windows' 260-character path limit. The venv adds 139 characters, so the clone path has to stay under about 120 (N3) |
| 02:34–02:39 | Re-clone at a short path, install | **4m20s**, OK |
| 02:39–02:44 | README: `python verify.py` | **5m24s, 8/10, exit 1.** Two checks are INCONCLUSIVE ("a broken harness"). They need the proxy extra, which the README's install step leaves out, and neither says so (N7) |
| 02:45 | `keys --init`, `keys` | OK. It writes a stray `.gitignore` into the cwd (N8), and urges a second account at the same provider (N9) |
| 02:45 | `keys --check` | **"0 provider(s) can serve a request right now."** The key is fine; the test model is gone (N6) |
| 02:45 | `doctor --workspace ./myproject` | **"1 blocking problem(s). Fix these before running."** The blocker is false (N5) |
| 02:46 | `run "<task>" --workspace ./myproject` | **Task done in 38 s**, 2 tests pass. Exit **1**: one effect "needs you" (N15) |

**Install to first finished task: 17½ minutes** of wall clock including the
dead ends. On a clean happy path (right Python, short path) it would be about
**11 minutes**, and 10 of those are install plus `verify.py`.

## 3. What worked

- **Both tasks were solved correctly on a free model.**
  - Task 1 added a zero check and a test.
  - Task 2 added `multiply`, tests, and a commit.
- **Crash and resume.**
  - The run was hard-killed (`SIGKILL`) 30 s into task 2, then resumed with
    `agentctl run '' --resume <id>` from inside the workspace.
  - Result: **exactly one** `add multiply` commit, tests passing.
  - This is the first time `run --resume` has been driven end to end against a
    real provider. `0042` §1.1 listed it as mock-only.
  - **Caveat:** the kill landed before any effect of that run had executed, so
    this is *resume continuity*. It is not *crash-after-effect*, which I-04 and
    I-07 still need to test.
- The agent's final message **is** shown, printed by the SDK. `0043` F6 was
  partly wrong and is corrected in §5.
- `keys` never printed a value, and neither did anything else.

## 4. Findings

The N-numbers are new. The F-numbers refer to `0043` §2.

| # | Finding | Evidence | Severity for a new user |
|---|---|---|---|
| N1 | GitHub `main` is 2 commits behind local. Users get neither the policy fix (`c0a681e`) nor `0042` | `git status -sb`: ahead 2 | high, trivial fix |
| N2 | The required Python is not surfaced. On 3.11, pip lists 100 versions and never names the cause. On Ubuntu, `python` does not exist, and `python3 -m venv` needs `sudo apt install python3.12-venv` | §2; WSL leg | high |
| N3 | Windows' path limit breaks the install when the clone path exceeds about 120 characters. The README is silent | pip `OSError` + long-path hint | medium |
| N4 | Dependencies drift unpinned, and CI last ran on 2026-09-21. SDK 1.45 → 1.50.1, litellm 1.100 → 1.103.1, mcp now 1.30 while the README says the SDK "needs `mcp>=2`" | `pip show`; `gh run list` | high: it is the cause of N5 |
| N5 | `doctor` fails a fresh install on a hard-coded `mcp >= 2` rule, while its own next line says the SDK imports cleanly. The run then works | `runtime/doctor.py:147` | **high: tells the user to stop** |
| N6 | `keys --check` tests only the first registry model, `nex-agi/nex-n2.5-pro:free`, chosen 2026-09-21 and gone by 2026-10-01. A working key reads as "cannot serve" | `control/providers.py:77` | **high: tells the user it will not work** |
| N7 | `verify.py`, which the README tells you to run, exits 1 on the README's own install. INCONCLUSIVE for "proxy never came up", with no mention of the proxy extra | `verify.log` | medium |
| N8 | `keys --init` writes its ignore rules to `.gitignore` in **the current directory**, not next to the keys file. Run inside a project, it edits that project's `.gitignore` unasked | `p0/.gitignore` | low |
| N9 | `keys`, `doctor` and `dash` all tell a one-key user to add "a second key, even at the same provider". That is the unverified premise (`0042` §4.C), with terms of service unchecked | outputs | medium: contradicts D1 |
| N10 | Every run prints the SDK's whole system prompt, so a 38-second run produced 687 lines. The SDK banner prints on every command unless `OPENHANDS_SUPPRESS_BANNER=1` | `run1.log` | medium |
| N11 | The workspace's `.agentctl/` (ledger, conversations with task text and tool output) shows as untracked in the user's repo, one `git add -A` from being committed | `git status` | medium |
| N12 | With no git identity, the agent ran `git config user.name "openhands"` in the user's repo **without being asked**, and the commit is authored as `openhands@all-hands.dev`. Triggered here by the fake home, but a fresh machine or container behaves the same | `.git/config`; `git log` | medium |
| N13 | One free key = **about 2–3 small tasks a day**: 35 requests for two tasks, against a 50-request cap. Nothing shows the remaining count unless you run `dash --refresh-quota`. Direct runs (no proxy) write no telemetry, so `cost` has no data at all | event count; `dash` | high for D1 |
| N14 | `agentctl policy` outside a clone fails, and its hint (`agentctl policy compile <file>`) names a subcommand that does not exist | output | low |
| N15 | **Live I-01, both tasks.** Task 1: the agent ran `python -c "divide(1, 0)"` to *show* the new error, and that deliberate failure became a BLOCKED effect "awaiting your decision". Task 2: `git commit` failed (no identity), the agent fixed the cause and re-issued the **identical** command, the gate refused it **twice**, and the agent had to reword the command to get past it. Both successful runs exited 1 | ledger; `run3.log` lines 378, 533, 718 | **high: the product's own safety layer is the most visible friction** |

## 5. `0043` §2, row by row

| F | Status after Phase 0 |
|---|---|
| F1 install | **Confirmed**, and worse: N2, N3, N4 |
| F2 default model | Worked for the OpenRouter user. Not tested for other providers |
| F3 pool path | Not exercised (D1 user) |
| F4 wrong ledger path | **Confirmed.** Inside the workspace, `status`, `resolve` and `dash` all say `no ledger at ledger.db`. The `resolve` hint the tool prints fails when copied verbatim |
| F5 resume | **Confirmed.** The README's wording, `run --resume <id>`, is an argparse error; the form that works is `run '' --resume <uuid>` |
| F6 end-of-run report | **Partly corrected.** The final message is printed by the SDK. Still missing: files changed, an outcome check, requests used |
| F7 `input()` | Not exercised; no confirmation was triggered |
| F8 identical re-run | **Confirmed live** (N15) |
| F9 policy path | **Confirmed**, plus a wrong hint (N14) |
| F10 vocabulary | **Confirmed.** The BLOCK reason is a raw traceback, and `NON_IDEMPOTENT_WRITE` is shown to the user |
| F11 cost | **Confirmed, and wider:** a direct run records nothing at all (N13) |
| F12 proxy traceback | Not exercised |
| F13 names | **Confirmed**: clone `HandCode`, command `agentctl`, banner "OpenHands" |
| F14 no-key trial | **Confirmed.** A cassette exists (`experiments/0008-m6-replay/session.jsonl`, and verify's M6 replays it) but nothing points a user to it |

## 6. Baseline against `0043` §7

| Measure | Baseline | Target |
|---|---|---|
| Minutes from install to first finished task | **17½** with dead ends; about 11 happy path | ≤ 5 |
| Commands to first finished task | **9** by the README; 4 at the minimum | 3 |
| Flags for resume / blocked / cost | resume: `run '' --resume <uuid>`; blocked/resolve: `--ledger <path>` even inside the workspace; cost: no data | 0 |
| False interventions on successful tasks | **1 and 4** (task 1; task 2: 3 BLOCK + 1 blocked). Exit 1 both times | 0 |
| Readiness checks that lied | **2 of 2** (`keys --check`, `doctor`) | 0 |
| Unattended hang | not exercised | 0 |
| Second person | not done (D5 open) | yes |

## 7. The Linux leg

It stopped at step 1. That is itself the finding for Ubuntu users.
- `python`: command not found.
- `python3 -m venv`: fails, because stock Ubuntu leaves out `ensurepip`, and
  the fix needs `sudo apt install python3.12-venv`.

I cannot enter a sudo password, so the install and `verify.py` did not run
there. The last CI run on Linux passed, but that was on 2026-09-21 and against
older dependencies (N4).

## 8. Caveats on the method

- One command (`dash`) was run once **without** the isolated `USERPROFILE` and
  read the owner's real keys file. It printed key lengths only, and wrote
  nothing. It was re-run isolated, and the isolated output is what §4 uses.
- The fake home had no git identity. That caused task 2's first commit failure
  and N12. The gate's behaviour after it (N15) does not depend on the cause.
- The long scratch path made N3 visible. The ~120-character threshold is a
  property of the dependency, not of this test.
- The MSYS2 Python on this `PATH` is specific to this machine. Python.org
  installs put `py` on PATH, which is why the recovery was `py -3.12`.
- n = 2 tasks, one model. The friction findings do not depend on n; the quota
  arithmetic (N13) is indicative only.
- Artifacts, left for inspection: `%TEMP%\p0\` (clone, logs, workspace with its
  ledger and conversations) and `/tmp/p0l` in WSL.

## 9. What this changes in `0043`

**A new Phase 0.5: quick fixes, zero quota, a day or less.** Every item below
made a user stop, and none needs design work:

1. Push `main` (N1).
2. `doctor`: stop enforcing `mcp >= 2`. The import checks already test what
   matters. Add a CI job that runs on a **schedule** against unpinned
   dependencies, so drift shows up before a user finds it (N4, N5).
3. `keys --check`: try the registry's models in order until one serves, and
   report "key OK, model X gone" rather than "cannot serve" (N6).
4. `verify.py`: report the proxy checks as SKIPPED, naming the extra to
   install, rather than as INCONCLUSIVE (N7).
5. The workspace's `.agentctl/` writes its own `.gitignore` containing `*` (N11).
6. The README: `py -3.12` on Windows; `python3` plus `python3.12-venv` on
   Ubuntu; the path-length note; `run '' --resume` (N2, N3, F5).
7. `keys --init`: put the ignore rules next to the keys file (N8). Fix the
   `policy` hint and default path (N14).
8. Suppress the SDK banner, and the system-prompt dump by default (N10).
9. Drop the "second key at the same provider" nudge for one-key users (N9).

**Phase 1 (I-01) is confirmed as the right next step after that.** N15 is its
defect happening in the first two real tasks a new user runs, not in a probe.

**The success-only exit code** (N15's exit 1) and **N12** (the agent setting
git identity unasked) go into Phase 3 and Phase 4 respectively.
