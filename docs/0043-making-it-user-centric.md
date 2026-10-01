---
Number:        0043
Title:         Making It User-Centric — The Plan
Type:          DECISION
Status:        DRAFT
Created:       2026-10-01
Supersedes:    —
Superseded-by: —
Depends-on:    0013, 0025, 0031, 0041, 0042
---

# 0043 — Making It User-Centric

The owner's statement: *we are not able to build and use it correctly.* The
goal now is to make `agentctl` easy for someone who is not its author. Open
sourcing comes after this, and so does deploying it.

This document is a plan. **Nothing in it is built.** The friction list in §2
comes from reading the code, not from watching a user. That is why Phase 0
exists: to confirm the list or correct it.

---

## 1. Who the user is

**The recommendation:** the primary user is a developer with **one API key for
any provider** who wants to run a coding agent on their own repository and not
lose work or double-commit when the run is interrupted.

The multi-account free-tier pool stays. It becomes a **power feature**, opt-in,
and no longer the path every command assumes. There are three reasons:

1. **The safety core is the differentiator, and it works with one key.** No
   duplicate effects, resume after a crash, fail-closed with a human decision.
   None of that needs a pool.
2. **The pool's premise is unverified.** OpenRouter's limits page says extra
   accounts do not change rate limits (`0042` §4.C). No provider's terms of
   service have been read. A public project should not lead with it.
3. **Most people have one key.** A first run that needs 24 accounts and a
   separately started proxy loses almost everyone before the first task.

**The owner decides this** (§8, D1). The phases below assume the
recommendation. If the owner picks the pool-first user instead, Phases 0, 1 and
5 stay the same and Phase 2 changes most.

### The promise to that user

Each item can be checked, and §7 measures them.

| # | Promise |
|---|---|
| P1 | Install to first successful run in **≤ 5 minutes with one key**, in **3 commands** |
| P2 | Every run ends by telling you: **did it work, what changed, what it used, what needs you** |
| P3 | An interrupted run costs nothing. `agentctl resume`, with no id to copy |
| P4 | Normal work does not trip the safety layer. Edit → test → re-test is not blocked |
| P5 | It never hangs waiting for a keypress nobody will make, and never silently refuses |
| P6 | You can try it with **no key and no cost** before you commit to anything |

---

## 2. Friction, as the code stands (`c0a681e`)

> **Phase 0 has run (`0044`).** It confirms most of these rows and corrects F6
> (the SDK does print the agent's final message). It also adds fifteen findings
> of its own, and a zero-quota Phase 0.5 before Phase 1. Row-by-row status:
> `0044` §5.

Each row is a place a new user stops. Rows marked *confirm* are inferred from
the code, and Phase 0 has to confirm them by running it.

| # | Friction | Where | Promise |
|---|---|---|---|
| F1 | Install means clone, then `pip install -e ".[dev,openhands]"`. Not on PyPI. The proxy extra needs a second, manual `pip install --upgrade` because `litellm[proxy]` and the SDK disagree on `mcp` | README; `pyproject.toml` | P1 |
| F2 | The default model is one hard-coded OpenRouter free model. Anyone else's key needs a LiteLLM model string they have to know already | `cli.py:923` | P1 |
| F3 | The pool path is three commands and two flags: `proxy --out`, `start.sh`/`start.ps1`, then `--model openai/pool --base-url …` | README "Failing over" | P1 |
| F4 | `status`, `blocked`, `dash` and `cost` read `./ledger.db` and `./cost.db` in the cwd. Runs write `<ws>/.agentctl/ledger.db`. Every follow-up command needs `--ledger` | `cli.py:43-44`; `runner.py:130` | P2, P3 |
| F5 | Resume means copying a UUID: `run '' --workspace X --resume <uuid>` | `cli.py:325` | P3 |
| F6 | A run ends with verdict counts. It prints no outcome, no files changed, no cost and no final message from the agent | `cli.py:294-328` | P2 |
| F7 | Confirmations call `input()`. Unattended, the run hangs. Detached, EOF becomes "refuse", silently | `runner.py:330, 428` | P5 |
| F8 | An identical re-run of a command gets stale output (SUBSTITUTE) or is BLOCKED, and the test loop is exactly that (I-01) | `gate.py:67-102` | P4 |
| F9 | `agentctl policy` defaults to a path relative to the repository, so it fails outside a clone | `cli.py:1041` — *confirm* | P1 |
| F10 | Output speaks the internal vocabulary: EXECUTE, SUBSTITUTE, PURE_READ, Seam B. The README leads with seams | runner, README | P2 |
| F11 | Through the proxy, `cost --conversation` is empty (23/23 `unknown:`, I-09), and free calls carry list prices (I-10) | `hook.py:151`; `ledger.py:113` | P2 |
| F12 | A dead proxy gives a traceback rather than a sentence | `runner.py:436+` returns `None` | P5 |
| F13 | Three names for one thing: repo `HandCode`, package `agentctl`, README "AI Agent Control Plane" | — | P1 |
| F14 | No way to try it without a key. Replay exists (M6), but nothing ships a cassette to replay | `docs/0029` | P6 |

---

## 3. The phases

The order follows one rule: **fix what makes it wrong before what makes it
awkward.** A user who sees a false BLOCK stops trusting the tool, however good
the onboarding is.

Every phase ends the way `0041` requires: **one live run against a real
provider**, recorded in the phase's commit message.

### Phase 0 — Watch a new user (baseline, ~0–30 requests)

- **What.** A clean environment with no keys file, no `~/.agentctl` and a fresh
  venv. Follow the README word for word, on Windows and then on Linux (WSL or a
  CI runner). Log every stop: the command, the error, what the user needed to
  know, and the minutes lost.
- **If at all possible, a second person** does the same with no help. `0031`
  shows why: a real user found six flaws in an hour, two of them correctness
  bugs.
- **Output.** The confirmed F-table, plus baseline numbers for §7.
- **Done when** every row in §2 is confirmed, corrected or struck, and the
  baseline is recorded.

### Phase 0.5 — Quick fixes (added by `0044`, done)

Nine zero-quota fixes, each for something that stopped the Phase 0 user.
Listed in `0044` §9; what changed and how it was checked is in `0044` §10.

### Phase 1 — Stop the safety layer getting in the way (zero quota)

> **Done.** I-01 in `0045`, I-02 in `0046`. Phase 2 is next.

Already the next Stage 1 work in `0042`. It is restated here because it is the
most user-visible defect.

- **I-01**, `OBSERVED`: a repeat the model issues after seeing the result is
  intentional, not a replay. Add P1 as a regression test, and the tenth chaos
  point. Fixes F8.
- **I-02**, one driver: `resume` refuses a live lease and names its holder, with
  an explicit `--takeover`. P3 needs this, because making resume easy also
  makes it easy to run twice.
- **Plain-language BLOCK messages.** Say what happened, why the tool stopped,
  and the exact command that answers it.
- **Done when** E-01, E-02 and E-16 (fail-first-then-pass tasks) show zero false
  interventions, the chaos suite is green, and one live run is done.

### Phase 2 — One key, three commands (the install path)

> **Built (`0047`), except publishing.** `init`, config precedence, and the
> managed pool are live-verified. The PyPI name is the owner's decision, since
> `agentctl` is taken.

- **Packaging.**
  - Publish to PyPI, so `pipx install agentctl` or `uv tool install agentctl`
    works. Check the name is free first (D3).
  - Settle the `mcp` conflict **structurally**. The proxy is already a separate
    process, so it can live in its own environment, created and managed by
    `agentctl proxy`. The user's install then never contains `litellm[proxy]`.
    Fixes F1.
- **`agentctl init`.**
  - Finds keys already in the environment or in `keys.env`, and checks them at
    zero tokens (the `keys --check` path).
  - Picks a default model **for the provider you have**, taken from the
    provider registry (`control/providers.py`) rather than a string in
    `cli.py`.
  - Writes `~/.agentctl/config.toml` holding the default model, the base URL and
    the source.
  - Interactive when there is a TTY. Flags when there is not (for CI).
  - Fixes F2.
- **Config precedence:** flag > environment > config file > built-in default.
  With it, `agentctl run "task"` in a repository needs no flags at all.
- **The pool, opt-in and managed.**
  - `agentctl run --pool` starts the proxy if it is not running, health-checks
    it, and reuses it on the next run.
  - `agentctl proxy up | down | status` replaces the start scripts. It is
    cross-platform and written in Python.
  - Fixes F3 and F12, since a dead proxy becomes a named state rather than a
    traceback.
- **Paths.** `policy` and every other default resolve against `~/.agentctl` or
  the package, never the cwd of a clone. Fixes F9.
- **Done when** a clean machine goes from `pipx install` to a finished task in 3
  commands, with one key.

### Phase 3 — A run you can read (P2)

- **An end-of-run report**, replacing the verdict counts (F6):

  ```
  outcome     PASS  (pytest -q, run by agentctl after the agent finished)
  changed     2 files  +14 −3        git diff --stat against the start
  agent said  "Added the zero check and a test for it."
  used        11 requests · $0.00 (free, per proxy config) · 2m 40s
  safety      14 actions: 6 reads, 2 writes, 6 commands · 0 repeats prevented
  needs you   nothing
  ```

- **`--accept "<cmd>"`**, the first half of I-20. The harness runs the check
  outside the agent's loop and records PASS or FAIL. Without it, the report
  says `outcome  not checked`, never an implied success.
- **A live progress line per turn**: turn number, the model that served it, the
  tool, and what kind of action it was, in plain words. Internal terms move to
  `--verbose` and `show`. Fixes F10.
- **A vocabulary map**, written once and used everywhere:

  | Internal | User-facing |
  |---|---|
  | SUBSTITUTE | already done; reused the recorded result |
  | BLOCK | paused; needs your decision |
  | PURE_READ / IDEMPOTENT_WRITE / EXTERNAL / DESTRUCTIVE | read / write / command / dangerous |

- **Numbers that are true:** I-09 (read the session id where the proxy puts
  it) and I-10 (known-free as a third cost state). The report's `used` line is
  worthless until both land. Fixes F11.
- **Done when** a user can answer the four questions from the report alone,
  without opening the ledger.

### Phase 4 — Interruptions and decisions (P3, P5)

- **A run index** (I-17), `~/.agentctl/runs.db`. `status`, `blocked`, `dash` and
  `cost` read it, and no follow-up command needs `--ledger`. Fixes F4.
- **`agentctl resume`**, with no argument, continues the last run in this
  workspace. `resume <prefix>` continues a specific one, with prefixes
  resolved the way `0041` §2.3 resolves effect ids. Fixes F5.
- **Ctrl-C pauses cleanly** through the SDK's `pause()`, verified callable in
  `0042` §8.2, and prints `agentctl resume`.
- **Approvals.**
  - **With a TTY**, ask as now.
  - **Without one**, queue the effect as awaiting approval (I-06) and tell the
    agent not to repeat it. Never EOF-as-refuse.
  - The new commands are `agentctl approve` and `deny`. Fixes F7.
- **On a rate limit**, the wait-only half of I-05. Print when the limit resets
  and the exact command that resumes, or wait if `--wait` was given.
- **Done when** a run can be killed, left unattended, or rate-limited, and in
  every case it ends with one command that continues it.

### Phase 5 — Try it before you trust it (P6), and docs for users

- **`agentctl demo`**:
  - It ships a small sample repository and a recorded cassette.
  - It replays a real task at **$0, with no key and no network** (M6).
  - It then kills the run mid-task and resumes it, so the user **sees** the one
    thing this project exists for: the commit that did not happen twice.
  - Fixes F14.
- **The README, reordered.** The quickstart comes first, then the demo, then
  "what it protects you from" in plain words. The seam design and the research
  history move behind a link.
- **A user guide in `guide/`**, separate from the numbered stream, which stays
  the project's memory. It covers the quickstart, concepts in plain words,
  troubleshooting indexed by the **exact error text** the tool prints, and a
  FAQ.
- **One name** (D4). Fixes F13.
- **Done when** a second person completes the demo and one real task from the
  guide, without asking the author.

---

## 4. What this plan deliberately leaves out

| Left out | Why |
|---|---|
| A hosted or multi-user service | `execute_bash` runs on the host with no sandbox. Hosting needs a sandbox first, and I-26 has to measure the injection risk. That is the deploy goal, and it comes after this one |
| Routing work (I-11 to I-15) | It makes the pool better. It does not make the tool easier. After the pool premise is checked |
| Multi-agent, `batch`, `ask_scout` | SKIP stands (`0038` §4) |
| A web dashboard (I-18, I-19) | Phase 3's report and Phase 4's index come first. A web page over wrong numbers is worse than a correct terminal line |

One small exception: **E-12**, the OpenRouter cross-account check, costs a
handful of requests. It decides how the pool is described in Phase 5's docs.
Run it during Phase 2.

---

## 5. Order and rough size

| Phase | Size | Quota | Depends on |
|---|---|---|---|
| 0 Baseline | ½–1 day | ≤ 30 req | — |
| 1 Correctness users feel | 1–2 days | ~30 req | — |
| 2 Install path | 2–3 days | ~20 req | 1 (resume must be safe before it is easy) |
| 3 Readable run | 2 days | ~30 req | 1; I-09/I-10 |
| 4 Interruptions | 2–3 days | ~30 req | 1, 3 |
| 5 Demo and docs | 1–2 days | 0 (replay) | 2, 3, 4 |

Phases 2 and 3 can run in parallel once Phase 1 has landed.

---

## 6. Risks

- **Easy resume makes double drivers easy.** That is why I-02 is a hard
  prerequisite for Phase 4, not a suggestion.
- **Friendlier output can hide the truth.** The project's history (`0039`) is
  confident wrong answers. Every plain-language line has to be derived from the
  same record as the precise one, and `show` stays exact. "Not checked" is
  never shown as success.
- **A managed proxy environment is a new moving part.** It has to fail loudly,
  with `proxy status` naming the state, and never fall back silently to a
  direct call.
- **The cassette in the demo pins the model, not the world** (`0029`). The demo
  has to reset its sample repository before every replay.

---

## 7. How success is measured

The Phase 0 protocol is re-run after each phase, against the same checklist.

| Measure | Baseline | Target |
|---|---|---|
| Minutes from install to first finished task, one key | Phase 0 | ≤ 5 |
| Commands to first finished task | Phase 0 | 3 |
| Flags needed for resume / blocked / cost | ≥ 2 each (F4, F5) | 0 |
| False interventions on fail-then-pass tasks (E-16) | > 0 (P1 probe) | 0 |
| Unattended runs that hang or silently refuse | yes (F7) | 0 |
| A second person completes demo + one task unaided | not tried | yes |
| Chaos suite and `verify.py` | green | still green |

---

## 8. Decisions for the owner

| # | Decision | Recommendation |
|---|---|---|
| D1 | Primary user: a one-key developer, or the free-tier pooler | **One-key developer**, with the pool opt-in (§1) |
| D2 | `init`: an interactive wizard, or a config file only | **Both.** Interactive on a TTY, flags otherwise |
| D3 | PyPI name: `agentctl` may be taken | Check before Phase 2. Fall back to the project name from D4 |
| D4 | One name for repo, package and README | Pick one before Phase 5's docs |
| D5 | Who is the second person for Phases 0 and 5 | Anyone who has not read this repository |
