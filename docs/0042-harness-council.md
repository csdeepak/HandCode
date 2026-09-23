---
Number:        0042
Title:         The Harness Council — What to Build and Test Next
Type:          RESEARCH
Status:        DRAFT
Created:       2026-09-24
Supersedes:    —
Superseded-by: —
Depends-on:    0001, 0009, 0013, 0023, 0030, 0033, 0038, 0039, 0040, 0041
---

# 0042 — The Harness Council

The owner's gap statement: the practical harness layer has not really been
worked on. That covers the real work the harness does, the dashboard and how it
drives the harness, API shifting on rate limits, experiments that could show
whether the harness adds value at all, real-world use cases, and the capabilities
that extend naturally from what exists. Generic agent features are out of scope.

This document is the output of a three-member council convened to answer that.
Each member worked in isolation. **Nothing here has been implemented.** No
member spent live quota. Every "live" claim below is a proposal, not a result.

---

## 0. How this was produced

| Phase | Member | Inputs | Constraints |
|---|---|---|---|
| 1 | **Architect** (Opus 5.5) | The repository: `docs/0041` first, then README, INDEX, 0001, 0009, 0013, 0021, 0023, 0030, 0032–0041, and every module in `agentctl/` | No web research, so the ideas arrived without evidence attached. Read-only. No quota. Ran three local probes (P1–P3) against scratch ledgers |
| 2 | **Analyst A** (Sonnet) | Phase 1's final output and the repository | Isolated from Analyst B. Web research allowed. Every claim tagged VERIFIED / INFERRED / UNVERIFIED |
| 2 | **Analyst B** (Sonnet) | Same as A | Isolated from Analyst A. Same tagging rule |
| 3 | Orchestrator | The three final outputs only | Synthesis, plus the verification pass described below |

**Isolation.**
- Each analyst saw only the Phase 1 file, wrote to its own file, and was told not
  to open anything else in the council directory. Both report that they complied.
- Both analysts started at the same moment.
- The Architect finished before either analyst existed, so no analyst influenced
  the idea generation.

**Verification pass during synthesis.** Claims that changed a conclusion are marked **[verified in synthesis]**.
- **Architect claims.** Fourteen mechanical code claims were checked by a free
  model running under `opencode` (13 TRUE, 1 PARTLY: a line range was off, the
  substance was right). I then spot-checked the ones used here.
- **Probes.** I re-ran P1, P2 and P3 against the working tree. All three
  reproduce exactly. The repository was left untouched apart from this document.
- **External sources.** I re-fetched every load-bearing external source myself.
  Two analyst claims failed that check (the Groq TPM figure and the status of
  litellm issue #19806, both in §6). One analyst finding became the most
  consequential fact in this document (the OpenRouter multi-account sentence, §4.C).

**Raw outputs**, preserved verbatim and frozen: `research/phase-11-council/`.
- `phase1-architect-opus.md`
- `phase2-analyst-a-sonnet.md`
- `phase2-analyst-b-sonnet.md`
- `probes/p1_identical_rerun.py`, `probes/p2_zombie_fresh_intent.py` (both need
  env var `S` set to a writable scratch directory)

**Read this before trusting the verdicts.** Neither analyst rejected a single
idea out of 27. There are two ways to read that, and both are partly true:
1. **The ideas rest on verified premises.** The analysts independently checked
   about 60 of the Architect's `path:line` and `docs/` citations and found two
   off-by-a-few-lines errors. They independently recomputed five telemetry
   numbers, and all five matched.
2. **Both analysts read the same framing.** Their independence is independence of
   *evidence*, not of *ideas*. What they contributed was additions and corrections,
   not rejections.

So read PURSUE as *"the premise is real and the idea is coherent"*. It does not
mean *"this is proven valuable"*. Value is what the experiments in §3 exist to
measure, and several of them are designed to come out against the project.

---

## 1. Current project state

What `agentctl` is, restated from the code rather than the docs:
- **Size:** 16 CLI subcommands, 45 modules.
- **Tests:** 643 passing, 1 skipped (459 `test_` functions, parametrised).
- **`verify.py`:** 10 checks, all against a mock provider.

### 1.1 What is real, by tier

**(a) Built and run against a real provider**
- `agentctl run` end to end through the proxy (`docs/0041`, `0036`, `0035`). All
  three live tasks were one-file toy fixes.
- Gate verdicts on live traffic: 14 effects in `0041`.
- Crash-and-resume with no duplicate commit (`0023` §5). This ran through an
  experiment script, not `agentctl run --resume`.
- Seam A capturing deployment ids.
- The proxy generator, with verification on by default plus `retry_policy` and
  `allowed_fails_policy` (12/12 through six dead deployments).
- Source groups, `keys --check`, the OpenRouter free-quota read, `doctor`,
  record/replay (a 3-turn cassette replayed in CI), the read-only subagent, the
  `recon` fan-out, and the keys pre-commit hook.

**(b) Built, only mock- or locally tested**
- `agentctl run --resume` as a CLI path. No test drives `runner.run`. The only
  test reads its source text (`tests/test_runtime_tools.py:245-252`).
- Cross-model intent-hash aliasing.
- Account-wide daily-cap failover (mock 429s only).
- `--confirm-destructive` and escaping-write authorization.
- The filesystem, idempotency-key and Seam C key-stamping paths.
- The policy compiler.
- Short-id prefix resolution.
- The recon citation checker.
- Fencing across hosts.

**(c) Declared but inert**
- `TurnAffinity` pins the model *group* name, and only when `mid_turn` is true,
  which it was in 0 of 23 live calls (`agentctl/kernel/hook.py:86-146`).
- Policy `pools` and `escalate_to` rules: no caller routes by them.
- USD budgets. `accumulated_cost` is 0.0 on unpriced endpoints.
- `EffectState.OBSERVED`. `store.observed()` has **zero callers**.
- Lease `renew()` and `release()`: **zero callers**, with a 60 s TTL.
- `http_request`/`send_email` rows in the capability matrix, with no tool behind
  them.
- `AGENTCTL_TELEMETRY` set in a process that never reads it.
- `cost_per_task`, with no definition of a completed task.

**(d) Docs only**
- The free-tier consumption model (`0013` §2).
- Dashboard Panels 2–4 (`0013` §3).
- `why`, `cost today`, push notifications.
- Cache affinity (Q4).
- Speculative execution (gated on Q9).
- The capability broker.
- Recon build steps 5, 7 and 8.
- Worktree-per-worker multi-agent.

### 1.2 The facts every idea below leans on

| Fact | Source | Status |
|---|---|---|
| Default `pool` = 48 deployments: 18 OpenRouter, 12 Mistral, 12 Groq, 6 Gemini, `routing_strategy: simple-shuffle` | `agentctl/control/proxy.py:222-231,303`; `docs/0038` §9.4 | verified in code |
| Live pooled telemetry: 250 records, 22 of them agent turns | `hook_telemetry.json` (uncommitted, written 2026-09-21 after `6870711`) | recomputed by Analyst B |
| 23 of 23 pre-call records have `trace_id = unknown:…` | same | recomputed by B **[verified in synthesis]** |
| `mistral-small-latest`: 0 successful records of 250 | same | recomputed by B **[verified in synthesis]** |
| 154 of 250 records carry a list price although every deployment is free-tier | same | recomputed by B |
| One conversation hopped 11 deployments and 3 models; cache-hit 32.7%, against 94.93% single-model (`0036` §1) | same | recomputed by B |
| Agent-capable daily allowance ≈ 550 requests (OpenRouter 6×50 + Gemini 250) ≈ 39 tasks at 14 req/task | `docs/0038` §4.1, `0040` §6 | **the OpenRouter half is now in question (§4.C)** |

### 1.3 The gap, stated structurally

1. **The real work is mishandled by the gate.** Edit → run tests → re-run the
   *same* command is the most common loop. The second run gets the stale output
   back, or is BLOCKED (P1).
2. **Nothing defines "done".** No task success signal exists anywhere in code.
3. **Unattended runs cannot exist.** Confirmations call `input()`, and pool
   exhaustion exits and waits for a human.
4. **The dashboard is a snapshot pointed at the wrong files.** It reads
   `./ledger.db` while runs write `<ws>/.agentctl/ledger.db`.
5. **Routing is uniform shuffle.**
   - Seam A records only successes.
   - A quarter of the pool (Groq) cannot carry turn 2.
   - The one routing rule the project wrote (turn affinity) is inert.
6. **No comparative claim in the charter has ever had a baseline arm.**

---

## 2. Proposed ideas

### 2.0 Verdict table

| ID | Idea | Kind | Analyst A | Analyst B | Council position |
|---|---|---|---|---|---|
| I-01 | Tell a replay from a repeat (`OBSERVED`) | both | PURSUE | PURSUE | **Agreed.** Defect reproduced. Do first |
| I-02 | One driver per conversation, enforced | both | PURSUE | PURSUE | **Agreed.** Defect reproduced. Do first |
| I-03 | What does the gate cost? (+ Q9 tally) | experiment | PURSUE | PURSUE | Agreed. The latency half is an expected null |
| I-04 | Resume vs restart, crash at turn k | both | PURSUE | PURSUE | Agreed. Can falsify the core claim |
| I-05 | Supervisor: wait or shift on exhaustion | both | EXP. FIRST | EXP. FIRST | Agreed. Both split it: wait-only first |
| I-06 | Approvals that do not stop the run | feature | PURSUE | PURSUE | Agreed |
| I-07 | Cross-model resume drill | experiment | PURSUE | PURSUE | Agreed. Cheap, central |
| I-08 | Seam A records failures; append-only telemetry | feature | PURSUE | PURSUE* | Agreed. *Resolve callback semantics offline first |
| I-09 | Conversation attribution through the proxy | both | PURSUE | PURSUE | Agreed. Live defect |
| I-10 | Known-free ≠ unpriced ≠ priced | feature | PURSUE | PURSUE | Agreed. Zero quota |
| I-11 | A pool fit for agent turns | both | PURSUE | PURSUE | Agreed. Try litellm's own pre-call check first |
| I-12 | Sticky vs shuffled vs single source | both | PURSUE | PURSUE | Agreed. Needs session-id wiring (§6) |
| I-13 | Quota ledger + pre-run admission | both | PURSUE† | EXP. FIRST | **Split on the label.** Both say measure before building |
| I-14 | Scarcity-weighted pool | both | EXP. FIRST | EXP. FIRST | Agreed. Simulate first |
| I-15 | Pool simulator | both | PURSUE | PURSUE | Agreed. Gated on a backtest it cannot run yet |
| I-16 | A policy for the real pool, in a unit that binds | feature | PURSUE | PURSUE | **Agreed.** Defect reproduced |
| I-17 | Run index | feature | PURSUE | PURSUE | Agreed. Precondition for the dashboard |
| I-18 | Live turn stream + `agentctl why` | feature | PURSUE | EXP. FIRST | **Split.** Value over "print more" unproven |
| I-19 | Resolve/approve from the dashboard | feature | PURSUE | PURSUE | Agreed |
| I-20 | `--accept` + `agentctl bench` | feature | PURSUE | PURSUE | Agreed. Substrate for everything; use repeated trials |
| I-21 | Cassette corpus as regression suite | both | PURSUE | PURSUE | Agreed. The cross-OS check gates trust |
| I-22 | Are the scouts right? | experiment | PURSUE | PURSUE | Agreed |
| I-23 | `ask_scout` tool inside a run | both | EXP. FIRST | EXP. FIRST | Agreed. Likely to fail its own test |
| I-24 | `agentctl batch` on isolated worktrees | both | EXP. FIRST | EXP. FIRST | Agreed. Quota, not wall time, binds |
| I-25 | Merchant sandbox: idempotency end to end | both | PURSUE | PURSUE | Agreed. Strongest real-world case |
| I-26 | Prompt-injection canaries | experiment | PURSUE | PURSUE | Agreed |
| I-27 | Pool vs one key, tasks per day | experiment | PURSUE (last) | PURSUE (last) | Agreed, last. **Premise check first (§4.C)** |

† A: PURSUE, but the first work item is a cross-account independence check, not the module.

---

### I-01 · Tell a replay from a repeat: use the unused `OBSERVED` state

**Kind** feature + experiment · **Area** safety, the real work

- **What it is.** Any identical non-replay-safe call in a conversation is aliased
  by intent hash to its earlier twin, so the agent either gets the twin's **old
  observation** (SUBSTITUTE) or is **BLOCKED** if the twin failed. That covers
  every test runner, `python app.py`, `git commit`, and `>>`.
  - Proposal: mark a record `OBSERVED` once Seam B has delivered its observation
    to the model.
  - `find_by_intent` then ignores OBSERVED twins, because a repeat the model makes
    after seeing the result is intentional.
  - A failed call whose error was delivered stops being an end-of-run "needs you".
  - The crash cases are untouched: an INTENT twin, or a COMMITTED twin with no
    observation.
- **Why it fits.**
  - Aliasing: `agentctl/kernel/gate.py:67-77`. Substitution: `:99-102`. Blocking
    every non-replay-safe failure: `record_tool_error`, `:282-315`.
  - Every interpreter classifies `EXTERNAL`.
  - The state and the `COMMITTED → OBSERVED` transition already exist
    (`agentctl/kernel/ledger/models.py:65,77`). `store.observed()`
    (`store.py:349`) has zero callers.
- **To build.** ~60–120 lines in `gate.py`, `store.py`, `schema.sql`,
  `seam_b.py` and `runner.py`, with P1 as a regression test.
- **Experiment.**
  - Zero quota: P1 as a test, then the nine-point chaos suite and experiments
    0001–0003. No duplicate may appear.
  - Live, ~30 requests: tasks seeded to fail first and pass after a fix, run with
    and without the change.
  - Measure false BLOCKs, stale SUBSTITUTEs, the end-of-run blocked count, and
    success.
- **Expected result.** Without the change, the re-run is blocked or substituted.
  With it, there are zero such events and the chaos suite stays green.
  - Falsified if any chaos point duplicates, meaning OBSERVED is not a sound
    "model saw it" signal.
  - Also falsified if live agents almost never re-issue byte-identical commands.
- **Architect's reasoning.** Aliasing was built for one case: a call re-minted by
  a different model after a crash. It fires on every identical call in the whole
  history, which captures the normal test loop. The ledger already has the state
  that separates replay from repeat, unused. It is small and kernel-local, and it
  removes false interventions that would contaminate every later experiment.
- **Analyst A.**
  - VERIFIED zero callers by grep, and that the code path produces P1's result.
  - Proposes a **tenth chaos point**, between `_close`'s ledger write and its
    return to the SDK. That is the new failure surface OBSERVED introduces.
  - Notes that `0041` itself is internally inconsistent: "1 BLOCK" in the table,
    "the two blocked effects" in the text. So `0041` cannot confirm this idea.
- **Analyst B.**
  - VERIFIED the same, and independently proposes the same tenth chaos point.
  - Adds a caution: I-01 does **not** touch the exact-argument fragility of intent
    hashing. A cross-model resume that rewords the call still duplicates silently.
    I-07 tests that.
- **Concerns.**
  - Soundness depends on the order in which OpenHands persists events and fires
    callbacks.
  - It permits a *deliberate* true duplicate (the model re-commits the same
    message). That moves a line `0023` §4 drew "deliberately conservative".
- **[verified in synthesis]** P1 re-run output: `run 2 (after COMMITTED):
  SUBSTITUTE … b'{"output":"1 failed"}'` and `run 2 (after failing run): BLOCK |
  the tool reported failure …`.
- **Implementation relevance.** Kernel fix, zero quota. Must land before any
  experiment that counts interventions (I-03, I-04, I-20, I-27).

### I-02 · One driver per conversation, enforced

**Kind** feature + experiment · **Area** recovery, single writer

- **What it is.** Three gaps combine into two live drivers of one conversation:
  1. The lease is never renewed (`renew()` has no callers; the TTL is 60 s).
  2. `--resume` always steals the lease (`takeover=bool(resume)`,
     `agentctl/runtime/runner.py:212`), even from a live run.
  3. `write_intent` checks the fence only when a record already exists
     (`store.py:282-285`), so a superseded holder's **fresh** call passes.

  Proposal:
  - renew on every gate decision;
  - `--resume` refuses a live lease and names the holder;
  - an explicit `--takeover` flag;
  - fresh intents check the lease table's current fence.
- **Why it fits.** "Zero duplicate side effects" is charter criterion 1. The
  single-writer invariant is what `0038` §4.2 and §10.3 use to SKIP multi-agent
  "at any budget". The fencing test covers only an existing record
  (`tests/test_ledger.py:125-141`).
- **To build.** ~40–70 lines across `store.py`, `gate.py`, `runner.py` and
  `cli.py`, plus two chaos tests: a zombie with a fresh id, and two live
  `--resume` processes.
- **Experiment.** Local and zero quota, with the mock provider. Start run A. After
  more than 60 s, start run B with `--resume A`. Script both to commit with
  different messages and count commits. Check that a crashed holder is still
  recoverable with `--takeover`.
- **Expected result.** Before: both commit, under two fences. After: B refuses,
  and A is fenced on its next fresh intent (StaleFence, turned into BLOCK).
  - Falsified if OpenHands' own persistence already stops two processes resuming
    one conversation.
- **Architect's reasoning.** The assumption the project leans on hardest is
  enforced more weakly than it is stated. A second terminal is enough to break
  it. The fix is in-kernel and the test is free.
- **Analyst A.** VERIFIED all three code facts. Check the OpenHands persistence
  lock first; that is the correct falsifier.
- **Analyst B.** VERIFIED. Make P2 a permanent regression test. Renewal adds a
  synchronous UPDATE per decision, which I-03 should measure.
- **Neither analyst determined** whether OpenHands locks its persistence
  directory. That is the one open question.
- **Concerns.** It changes a documented default (README
  `protect(takeover=resuming_after_a_crash)`). A crashed process that leaves a
  live-looking lease will need a TTL wait or the flag.
- **[verified in synthesis]** P2 re-run: `fences 1 2`, then `zombie guard on a
  FRESH id: EXECUTE None`, then `zombie commit state: COMMITTED`.
- **Implementation relevance.** Kernel fix, zero quota. Protects I-04, I-05, I-06
  and I-24.

### I-03 · What does the gate cost? Guarded vs unguarded, plus the Q9 tally

**Kind** experiment · **Area** evaluation, overhead

- **What it is.** Run the same graded tasks with the gate on and off, with no
  crashes. With no crash the gate prevents nothing, so this isolates its cost.
  Measure:
  - per-call latency (fsync at `synchronous=FULL`, git probe subprocesses);
  - false BLOCK, ESCALATE and SUBSTITUTE verdicts;
  - human interventions;
  - success.

  Tally the effect classes, which closes `docs/0009` Q9 and decides whether
  speculative execution stays unbuilt.
- **Why it fits.** Q9 is OPEN (`0009` line 112). The only data point is
  `0041`'s 6 PURE_READ out of 14 effects.
- **To build.** An experiment-only `--unguarded` switch refused outside an env
  flag, per-decision timing in `on_decision`, and a tally script. ~60 lines.
  Needs I-20.
- **Experiment.** 5 tasks × 2 arms on one source, ~140 requests.
- **Expected result.** Latency in milliseconds against a live LLM p50 of 3.1 s.
  Intervention cost is non-trivial until I-01 lands.
  - Falsified (the gate is a net cost) if, after I-01, the guarded arm still shows
    more interventions or lower success.
- **Architect's reasoning.** The gate is proven to prevent duplicates. What it
  costs on ordinary, crash-free work has never been measured.
- **Analyst A.**
  - `agentctl/control/dash.py:363-387` (`_effects`) already aggregates by state
    and class. Reuse it for the tally.
  - Bound `--unguarded` further by refusing any non-localhost base URL.
  - The switch should not outlive the experiment.
- **Analyst B.** Expects the latency result to be null. Add a same-arm repeat to
  get a noise baseline, and enforce the env-flag refusal with a test.
- **Concerns.**
  - Both analysts predict the latency half's result, which by the Architect's own
    rule makes it the less informative half.
  - The informative outputs are false verdicts and interventions before and after
    I-01, and the Q9 tally.
  - n = 5 is noisy.
- **Implementation relevance.** Experiment-only. Closes a question open since
  2026-09-05.

### I-04 · Does resume beat restarting? Crash at turn k, three arms

**Kind** feature (kill hook) + experiment · **Area** recovery, continuity

- **What it is.** Kill the runner at the k-th effect, then finish the task three
  ways:
  - **(A)** `agentctl run '' --resume <cid>`;
  - **(B)** a fresh conversation on the *dirty* workspace, which is what a user
    without the harness would do;
  - **(C)** a fresh conversation on a clean copy.

  Measure requests and tokens to completion, acceptance, duplicate effects,
  BLOCKs, and wall time.
- **Why it fits.** Continuity is a charter criterion. The chaos suite proves no
  duplicates with one effect per run, but has never been compared against a
  restart. Resume re-sends the whole conversation while a restart re-reads a few
  files. On a pool rationed in requests, which is cheaper is not obvious.
- **To build.** A test-only `AGENTCTL_KILL_AT_EFFECT=n` hook in Seam C, calling
  `os._exit` (~20 lines, modelled on `experiments/0004-nine-point/worker.py`), a
  driver script, and tasks that include a non-idempotent effect.
- **Experiment.** 4 tasks × 2 kill points × 3 arms ≈ 24 runs ≈ 400 requests.
  Run k=1 first (~200 requests) and decide whether the second kill point is worth
  it.
- **Expected result.** A: zero duplicates and fewer requests than C. B: duplicates
  in some fraction of runs.
  - **Falsified** if B matches A on duplicates, because the model inspects
    `git log`, and on requests. The claim would then narrow to effects the agent
    cannot inspect (I-25).
- **Architect's reasoning.** "Crash it and re-run with `--resume`" has only ever
  been compared with doing nothing. This experiment can come out against the
  project. It also exercises `run --resume` for the first time.
- **Analyst A.**
  - VERIFIED that no test executes `runner.run`.
  - Add a task whose git history is *ambiguous*, for example a pre-commit hook
    that fails after a partial index write, so arm B's "the model figures it out"
    path is actually tested.
  - Cites ReliabilityBench as context (A tagged it UNVERIFIED).
- **Analyst B.**
  - VERIFIED.
  - ReliabilityBench grades by end-state equivalence, which supports grading
    through I-20's acceptance command.
  - Arm B depends on whether the model inspects `git log` unprompted, which the
    system prompt can bias.
  - Enforce I-01 and I-02 as prerequisites, not suggestions.
- **Concerns.** Among the more expensive experiments. The result is directional
  rather than statistical, and depends heavily on the model.
- **Implementation relevance.** The kill hook is reused by I-07 and I-25.

### I-05 · A supervisor that outlives the quota

**Kind** feature + experiment · **Area** rate-limit shifting, long-running agents

- **What it is.** `agentctl supervise <cid>` (or `run --until-done`) wraps the
  run loop.
  - It classifies why a run ended:
    - rate limit or pool exhausted, via the existing `_explain_provider_error`
      header parsing (`agentctl/runtime/runner.py:448-467`);
    - overload;
    - **proxy dead**, which is currently unrecognised and produces a traceback;
    - key rejected.
  - It then chooses one of three responses:
    - (a) wait for the earliest reset, then resume with an explicit takeover;
    - (b) shift to a source group that still has allowance, then resume;
    - (c) stop and notify.
  - It never shifts to `paid`.
- **Why it fits.** The charter's first sentence is about surviving a rate limit
  without work stopping. Today exhaustion exits with advice for a human
  (`runner.py:463-467`). The parts already exist: persisted conversations, resume
  with takeover, and source groups.
- **To build.** `agentctl/runtime/supervise.py`, ~150 lines. A proxy-liveness
  check reusing `_proxy_pool` (`dash.py:81-111`). Optionally,
  `proxy --exclude-capped`, fed by I-08.
- **Experiment.** Two drills, against a baseline of plain `run`, which exits:
  - **exhaustion drill:** one OpenRouter key plus Gemini, run until the key 429s
    (~50 + 20 requests);
  - **proxy-death drill:** kill the proxy mid-run and restart it after 30 s.
- **Expected result.** The supervisor completes the task.
  - Falsified if a mid-task shift to another model family fails more often than
    waiting does.
  - Also falsified if real exhaustion rarely happens mid-task.
- **Architect's reasoning.** The literal reading of "API shifting on rate limits"
  is what the harness does when the router has nothing left. That is a
  control-plane decision. It is not a rebuilt router, which the charter forbids.
- **Analyst A.**
  - VERIFIED that connection-refused falls through to `return None`.
  - The router's cooldown state lives in process, and `/metrics` still reported
    an outage 15 s after a cooldown expired (`0038` §5.2). So the supervisor must
    reason from I-08 telemetry. A treats I-08 as a **hard blocker**, not a
    nice-to-have.
- **Analyst B.**
  - VERIFIED.
  - ReliabilityBench found rate limiting the most damaging fault in its ablations,
    which supports prioritising this **[verified in synthesis:** arXiv 2601.06112
    abstract**]**.
- **Both analysts, independently:** split it. Build a **wait-only** supervisor
  first (no risky dependency). Gate the **shift** half on I-12's finding about
  model hopping.
- **Concerns.**
  - A shift changes the model family mid-conversation.
  - A Gemini reset can be hours away.
  - An auto-resume loop can spin, so it needs an attempt bound.
  - The OpenRouter premise (§4.C) changes how much there is to shift to.
- **Implementation relevance.** This is the owner's "API shifting" ask. Depends
  on I-02 and I-08 (and I-13 for the shift half).

### I-06 · Approvals that do not stop the run

**Kind** feature · **Area** long-running agents, dashboard interaction

- **What it is.** `--confirm-destructive` calls `input()` inside the gate
  (`runner.py:329-335`). Unattended, it blocks forever. Detached, it reads EOF as
  refuse. The policy prompt has the same shape (`:425-433`).
  - Proposal: the effect is recorded BLOCKED as "awaiting operator approval", and
    the agent is told it is queued.
  - Approve or deny later through `resolve` or the dashboard. An approved effect
    executes on the next resume.
  - An optional notification hook.
- **Why it fits.** `0013` §3 Panel 3 is exactly this. The ledger already models
  BLOCKED and its human transitions (`models.py:79-81`).
- **To build.** ~80 lines in `runner.py`, `cli.py` and `store.py`, including
  `agentctl approve`.
- **Experiment.**
  - Mock: the run continues and ends with one queued approval. Approve → resume →
    executes exactly once. Deny → never executes.
  - Live: one task that deletes a build directory, ~15 requests.
- **Expected result.** Unattended runs finish with queued approvals instead of
  hanging.
  - Falsified if models loop, re-issuing the queued action.
- **Analyst A.** VERIFIED `input()` at `:330` and the EOF handling at `:331-332`
  and `:427-430`. Script three re-issues and assert they alias to *one* pending
  record.
- **Analyst B.** VERIFIED. The message must say "do not repeat this". Make the
  loop test a first-class pass/fail, and defer the webhook.
- **Concerns.** The model's reaction to "queued" is the uncertain part. A stale
  approval needs its pre-state recaptured at execution (`gate.py:218-237`).
- **Implementation relevance.** A precondition for unattended I-05 and for I-19.

### I-07 · Cross-model resume drill

**Kind** experiment · **Area** provider switching, recovery

- **What it is.** Crash right after `git commit` executes, before its observation
  is recorded. Resume on a **different source group** (Gemini ↔ OpenRouter). Count
  commits. Record whether the resumed turn was substituted through the intent
  hash, reconciled by the probe, or BLOCKED.
- **Why it fits.** `0023` §5: the one live crash test sent both runs to the same
  model, so the cross-model case never ran. With turn affinity inert, cross-model
  switches are now the *normal* path.
- **To build.** I-04's kill hook and a two-source driver.
- **Experiment.** 2 directions × 3 reps × ~12 requests ≈ 70 requests.
- **Expected result.** Exactly one commit.
  - **Falsified** if the new model rewords the commit, the hash misses, and a
    duplicate lands. That would define the next design problem: alias by effect
    kind plus world state, not by exact arguments.
- **Analyst A.** VERIFIED the aliasing design in `0023`. Argument drift is the
  classic weakness of content-addressed deduplication.
- **Analyst B.** VERIFIED `0023` §5 verbatim, and recomputed `mid_turn` False in
  23 of 23 calls.
- **Concerns.** Three passes can pass by luck; record the result as evidence, not
  proof. It needs a reliable kill point.
- **Implementation relevance.** The most direct test of "the endpoint can
  change".

### I-08 · Seam A records failures; telemetry becomes append-only and ingests itself

**Kind** feature, verified live · **Area** observability, routing foundation

- **What it is.** `AgentctlHook` implements only `async_pre_call_hook` and
  `async_log_success_event` (`agentctl/adapters/litellm/hook.py:26-42`). Every
  429, 413, 402, 404 and timeout the router retried around is invisible.
  Proposal:
  - a failure callback recording the deployment, exception class, status,
    rate-limit headers, prompt size and timestamp;
  - append-only JSONL instead of `_flush`'s full-file rewrite on every call
    (`agentctl/kernel/hook.py:199-209`);
  - auto-ingest into `dash` and `cost`;
  - telemetry moved out of the tracked `hook_telemetry.json`, which currently has
    2,843 uncommitted changed lines.
- **Why it fits.** Six `mistral-small-latest` deployments produced zero records
  out of 250. Current data cannot say whether they are dead, rate-limited, or
  rejecting tool schemas.
- **To build.** ~80 lines, plus a `failure_record` table.
- **Experiment.** 20 realistic-size requests through `pool`. The failure table
  should show Groq 413s and the mistral-small outcome.
- **Expected result.** A non-empty failure log.
  - Falsified (as designed) if litellm fires the failure callback only on the
    *final* failure, not on each retried attempt.
- **Analyst A.** VERIFIED both code facts. Resolve the per-attempt question
  **offline first**: register a `CustomLogger`, point the router at an unreachable
  base URL, and see what fires.
- **Analyst B.**
  - VERIFIED, and recomputed 0/250.
  - Found litellm issue #19806 requesting a per-retry callback hook, which
    suggests none exists. B treats the per-attempt question as a **blocking** one.
  - If only terminal failures are logged, scope down to "record every terminal
    failure with its deployment". That is still far better than nothing.
  - **[verified in synthesis:** the issue is *closed as not planned*, not open as B
    reported, which strengthens B's inference**]**.
- **Concerns.** Exception objects may not expose headers for every provider.
- **Implementation relevance.** The root of the routing and dashboard dependency
  chain (I-05, I-11–I-15, I-17, I-18).

### I-09 · Conversation attribution through the proxy

**Kind** feature + experiment · **Area** observability, cost attribution

- **What it is.** The hook reads the conversation id from `meta.conversation_id`
  or `data.extra_headers["x-litellm-session-id"]`
  (`agentctl/kernel/hook.py:151-154`). But `extra_headers` is a *client-side*
  kwarg, and live, 23 of 23 calls read `unknown:`. As a result:
  - `cost --conversation` is empty;
  - cost per completed task cannot be computed;
  - `research/phase-10-5` §2.12 ("attribution is free through the proxy") is
    falsified by the repository's own data.

  Fix: read the id where the proxy actually exposes it, and stamp the parent id
  onto subagent and recon calls.
- **To build.** ~20 lines, tested against a *captured real* proxy `data` dict,
  not a hand-built one (the `0021` §4 lesson). ~10 lines in `subagent.py`.
- **Experiment.** One live run, ~15 requests: cost-ledger rows carrying the
  conversation id must equal the recorder's client-side completion count.
- **Expected result.** Equal counts.
  - Falsified if OpenHands does not send the header through a `base_url` proxy
    call. The fix then moves to `LLM(extra_headers=…)`.
- **Analyst A.**
  - The same module's `record()` already documents fixing this *exact bug class*
    once before, which is strong circumstantial evidence.
  - Capture the real dict from a local mock-upstream proxy at zero quota.
- **Analyst B.** VERIFIED the code, and recomputed 23/23 from the raw telemetry.
- **[corrected after synthesis, §8]** An earlier version of this line said the
  installed litellm proxy never references `x-litellm-session-id`. **That was
  wrong.** The search tool had skipped the gitignored `.venv/`. What the code
  actually does:
  - OpenHands sends the header on every call that carries a session id
    (`openhands/sdk/llm/options/common.py:78-83`).
  - The proxy maps it into `data["litellm_session_id"]` and
    `metadata.session_id` (`litellm/proxy/litellm_pre_call_utils.py:69,
    1279-1284, 1323`).
  - agentctl's hook reads `data["extra_headers"]`, which does not exist at the
    proxy.

  So the likely fix is a one-line change of key. E-06 or E-14 must still confirm
  that the SDK fills in the session id in `agentctl run`'s configuration.
- **Implementation relevance.** Charter problem 3. Tiny code, verified live.

### I-10 · Known-free is not unpriced is not priced

**Kind** feature · **Area** cost control

- **What it is.** The ledger has two states, `priced = 1 if cost else 0`
  (`agentctl/control/cost/ledger.py:113`), so its figures are wrong in both
  directions:
  - litellm puts list prices on free Gemini, Mistral and Groq calls, and the
    `daily_usd` cap counts those phantom dollars;
  - OpenRouter's `:free` calls read as "unknown".

  The generated config already records `model_info.free` (`proxy.py:230`). Add a
  third state, `known_free`, excluded from spend and from the coverage
  denominator.
- **To build.** ~40 lines.
- **Experiment.** Zero quota: re-ingest the existing telemetry and expect $0 known
  and no "unknown". Then one live run, cross-checked against the providers'
  consoles.
- **Expected result.** Free deployments show $0.00.
  - Falsified if any "free" deployment actually bills, which would itself be
    worth knowing.
- **Analyst A.** VERIFIED `ledger.py:113` and `proxy.py:230`. `record()` extracts
  no `free` field.
- **Analyst B.** VERIFIED, and recomputed 154/250 priced and the 96 unpriced
  OpenRouter `:free` records (41+34+21). Pin those numbers in a regression test.
- **Concerns.** "Free" is a configuration claim. Display it as "free per proxy
  config", not "$0".
- **Implementation relevance.** Zero quota. A prerequisite for any USD budget to
  mean anything.

### I-11 · A pool fit for agent turns

**Kind** feature + experiment · **Area** routing, reliability

- **What it is.** Three parts:
  1. `check_inference` verifies only each provider's **first** model
     (`agentctl/control/probe.py:281`, `p.default_model`). Verify every distinct
     model id, and drop dead ones.
  2. Remove Groq from `pool`: 12 of 48 deployments, which cannot carry turn 2.
     Keep it in `pool-groq` for small scouts.
  3. Decide deliberately whether ministral-3b belongs in the default agent pool.

  A CONFIGURE alternative for part 2: litellm's `enforce_model_rate_limits`
  pre-call check with a per-deployment `tpm`.
- **To build.** ~50 lines in `probe.py` and `proxy.py::build`.
- **Experiment.** Per-model verification (8 requests). Then an A/B of 40–60
  realistic-size requests, measuring attempts per success, p50 and p90 latency,
  and failures by class.
- **Expected result.** Attempts per success fall from about 1.3–1.4 toward 1.0.
  - **Falsified** if cooldowns (`allowed_fails: 1`, `cooldown_time: 300`) already
    make dead deployments negligible. The change would then be cosmetic.
- **Analyst A.** VERIFIED. Read the installed pre-call check first; CONFIGURE
  beats BUILD, per the charter.
- **Analyst B.**
  - VERIFIED `model_rate_limit_check.py`: it is enabled through
    `optional_pre_call_checks`, reads `tpm`/`rpm`, and raises `RateLimitError`
    with `num_retries=0`. It needs `tpm` stamped on each deployment, which is a
    few lines, not zero. Add it as a fourth arm.
  - **[corrected after synthesis, §8] That arm does not fit.**
    - The check compares only usage *already recorded* in the current minute
      (`model_rate_limit_check.py:250-268`). It never estimates the incoming
      prompt, so it cannot stop a 9K-token prompt reaching an 8K-TPM Groq
      deployment.
    - When it does fire, `num_retries=0` makes the request **fail**. It is not
      re-routed within the group.
    - So removing Groq from `pool` (the BUILD path) is the fix, and the
      CONFIGURE alternative is withdrawn.
  - B also claimed, from secondary sources, that Groq's TPM varies from 6k to 12k
    and contradicts the project's flat 8,000.
- **[verified in synthesis] B's Groq concern does not hold for this pool.**
  - Groq's own rate-limit page lists both models the pool uses, `gpt-oss-20b` and
    `gpt-oss-120b`, at 8K TPM on the free plan (30 RPM, 1K RPD, 200K TPD). That
    matches the project's 8,000.
  - The page also says limits apply per **organization**, which matters for §4.C.
- **Concerns.** Removing ministral shrinks the Mistral leg, so keep it in
  `pool-mistral`. Per-model verification costs a few requests per `proxy` run.
- **Implementation relevance.** The default agent path.

### I-12 · Sticky or shuffled? Session affinity vs shuffle vs one strong source; retire `TurnAffinity`

**Kind** configure + experiment · **Area** routing, model switching, cache economics

- **What it is.**
  - One live conversation went through 11 deployments across 3 models in 11
    turns. Its cache-hit ratio was 32.7%, against 94.93% for a single-model run.
  - `TurnAffinity` is inert.
  - litellm ships session and deployment affinity, which is exactly `0009` Q4.

  Experiment arms:
  - **(A)** shuffle, after I-11;
  - **(B)** session affinity;
  - **(C)** one strong source.

  Configure the winner, delete or re-point `TurnAffinity`, and close Q4.
- **To build.** A few lines of `router_settings`, and removal of
  `hook.py:86-146` and its tests.
- **Experiment.** 5 tasks × 3 arms ≈ 210 requests over two days. Measure success,
  requests and tokens per task, cache-hit ratio, p50, and distinct models per
  conversation.
- **Expected result.** B and C show higher cache hit and fewer models, with equal
  or better success. B keeps failover; C gives it up.
  - **Falsified** if cache hit rises but neither latency nor success improves. On
    a free pool that would retire the cache-economics argument, a scope-shrinking
    DECISION.
  - Also falsified if A succeeds as often as C.
- **Analyst A.**
  - VERIFIED from litellm's docs that session affinity exists. The docs say it
    reads the `x-litellm-session-id` header or `metadata.session_id`.
  - "The highest-value, lowest-risk routing idea." Also count tool-call-id format
    mismatches per arm.
- **Analyst B.**
  - Recomputed the 11-hop sequence and the 32.7% exactly.
  - Found that the **installed** 1.100.0 check reads only `metadata.session_id`,
    and that the proxy does not map the header into it. So arm B is configuration
    **plus** a hook change that stamps `metadata.session_id`.
  - Proposes a zero-quota wiring test.
- **Disagreement, resolved in A's favour [corrected after synthesis, §8].**
  - B is right that the affinity check reads only `metadata.session_id`
    (`deployment_affinity_check.py:266-310`, from `litellm_metadata` or
    `metadata`).
  - But the installed proxy *does* fill that field from `x-litellm-session-id`
    (`litellm_pre_call_utils.py:1279-1284, 1323`), and OpenHands sends that
    header.
  - So arm B is plausibly **configuration only**:
    `optional_pre_call_checks: ["session_affinity"]`, plus
    `deployment_affinity_ttl_seconds`.
  - Confirm with E-05 or E-06 before spending arm B's quota.
- **Concerns.**
  - Affinity concentrates a conversation on one account.
  - It interacts with I-14's weights.
  - Arm C's loss of failover must be visible in the results.
- **Implementation relevance.** Closes Q4. Mostly configuration, which is the
  method's preferred verdict.

### I-13 · A quota ledger and pre-run admission

**Kind** feature + experiment · **Area** rate-limit awareness, dashboard

- **What it is.**
  - Count requests per **quota**, not per key, per provider day, from I-08
    telemetry.
  - Limits come from a user file, `~/.agentctl/limits.yaml`, with `measured_on`
    and `source` fields, never from source code.
  - Calibrate OpenRouter against `/api/v1/key`.
  - `dash` shows dated evidence under the `UNKNOWN` banner.
  - `run`/`doctor` estimate the run's requests and warn before it starts.
- **To build.** `agentctl/control/quota.py`, ~150 lines, a panel, and a preflight
  line.
- **Experiment.** Piggyback on a week of use and compare the local count with
  OpenRouter's reported `used`.
- **Expected result.** The count tracks within a few requests when this machine
  is the only client.
  - Falsified if it drifts, for example because the same keys are used by other
    tools.
- **Analyst A (PURSUE, with a precondition).**
  - OpenRouter's own limits page says extra accounts or keys will not affect rate
    limits, because capacity is governed globally.
  - The first work item is therefore a **cross-account independence check**: burn
    one account's free quota and see whether sibling accounts' `used` moves.
- **Analyst B (EXPERIMENT FIRST).**
  - The central accuracy claim has zero in-tree evidence.
  - Run the calibration for days *before* writing the estimator.
  - If the keys are shared with other tools, the warning becomes actively
    misleading, which is worse than an honest `UNKNOWN`.
- **The disagreement is about the label, not the substance.** Both say measure
  before building. A adds the account-independence premise.
- **[verified in synthesis]** Reset clocks: Gemini's RPD resets at midnight
  Pacific (Google's rate-limit page); OpenRouter counts the "current UTC day"
  (OpenRouter's limits page). This answers the Architect's open question.
- **Implementation relevance.** The input to I-05's shift decision and to
  Panel 1.

### I-14 · A scarcity-weighted pool

**Kind** configure + experiment · **Area** routing

- **What it is.** The uniform shuffle gives Gemini (one 250-RPD quota) 12.5% of
  requests, OpenRouter (six 50-RPD quotas) 37.5%, and Mistral 25%. `docs/0040`
  §6.1's rule, "allocate inversely to scarcity", is implemented only in recon.
  Emit a per-deployment `weight:` in proportion to its quota's allowance divided
  by the deployments sharing it.
- **To build.** ~40 lines in `proxy.py` and a `models` column.
- **Experiment.** Simulate first (I-15), then run live inside I-27. The metric is
  successful requests before the first request that exhausts every retry.
- **Expected result.** Quotas exhaust closer together.
  - **Falsified** if cooldowns already equalise exhaustion, in which case weights
    change only latency.
- **Analyst A.** VERIFIED from litellm's docs that `weight` controls selection
  frequency.
- **Analyst B.** VERIFIED from the installed `simple_shuffle.py` that it honours
  `weight`/`rpm`/`tpm`.
- **Both analysts:** simulate first.
- **Concerns.**
  - A sticky session ignores weights after the first pick.
  - The weights inherit whatever the user file gets wrong.
  - If §4.C's premise fails, OpenRouter's weight collapses.
- **Implementation relevance.** One generator change. Do not build it before I-15
  says it matters.

### I-15 · A pool simulator

**Kind** tool + backtest · **Area** evaluation, routing

- **What it is.** `agentctl simulate`, a small discrete-event model.
  - **Input:** a request trace.
  - **Model:**
    - quotas per account: OpenRouter 50/day, Gemini 250/day per project, Groq
      TPM, Mistral RPM/TPM;
    - the router's behaviour (shuffle, weights, `allowed_fails`, cooldown,
      retries), taken from the generated config.
  - **Output:** tasks per day, time to the first unrecoverable failure, and when
    each quota runs out.
- **Why it fits.** `0038` §4.1 and `0040` did this arithmetic by hand, three
  times, and moved it by an order of magnitude twice.
- **To build.** `agentctl/control/simulate.py`, ~200 lines, stating its
  simplifications in its output.
- **Experiment.** Backtest one real day of I-08 telemetry. Target: within about
  20% of the observed exhaustion times.
- **Expected result.** A usable model.
  - Falsified if it cannot reproduce a day it was calibrated on. Routing
    experiments would then have to stay live.
- **Analyst A.** Print the fraction of inputs that were measured versus inferred.
  Hard gate: no other idea may cite its output until the backtest passes.
- **Analyst B.** The tree holds only 23 real agent-turn calls, too thin for a
  backtest. Report wide error bars.
- **[orchestrator note]** No full day of *failure* telemetry exists yet, so this
  cannot be validated until I-08 has run for at least a day. Its value is
  deferred, not cancelled.
- **Implementation relevance.** Turns routing A/Bs from a day of quota into free
  runs.

### I-16 · A policy about the pool that exists, in a unit that binds

**Kind** feature · **Area** cost control, policy

- **What it is.** Three defects:
  1. **The shipped `agentctl/control/policy/data/policy.yaml` does not compile.**
     Its `tiering:` block at line 38 is refused (`compile.py:236-240`), and the
     checked-in `policy.compiled.json` is stale.
  2. The policy's pool members (`openrouter/free`, …) match no model group the
     proxy exposes. So every `--policy` run through the proxy hits the "spend on
     it?" prompt, which reads EOF as refuse.
  3. USD caps cannot bind on a free pool (I-10).

  Proposal:
  - pools refer to proxy groups, validated at compile time;
  - add `budget.requests_per_task` and `requests_per_day`, enforced by counting
    completions in the runner process;
  - fix the shipped file, and add a test that compiles it.
- **To build.** ~120 lines.
- **Experiment.** Mock: a 20-request task stops at a cap of 10, and resume
  continues. One live run, ~12 requests.
- **Analyst A.** Reproduced P3 by running the compiler. Put a compile-the-shipped-
  file test in `tests/test_policy.py` permanently.
- **Analyst B.** Reproduced P3 independently. That test should be written first
  and should **fail today**.
- **[verified in synthesis]** P3 re-run: exit 2, `tiering is not implemented and
  nothing routes by it … Remove the block.`
- **Concerns.** A mid-run stop needs a clean SDK pause or interrupt. **No member
  verified** that SDK 1.45.0 has one.
- **Implementation relevance.** The compile fix and pool-name fix are near
  risk-free and should ship regardless. The requests cap can wait for I-13's
  distribution.

### I-17 · A run index, so the dashboard finds every run's data

**Kind** feature · **Area** dashboard

- **What it is.** `~/.agentctl/runs.db`, with one row per run, subagent, recon and
  supervisor attempt: ids, workspace, ledger and telemetry paths, source, start,
  end, exit reason, acceptance result, and request count. `dash`, `status`,
  `blocked` and `cost` iterate it.
- **Why it fits.** The dashboard reads the wrong files:
  - `DEFAULT_LEDGER = Path("ledger.db")` (`cli.py:43`), while runs write
    `<ws>/.agentctl/ledger.db` (`runner.py:130`);
  - `cost.db` stays empty until a manual `ingest`.
- **To build.** `agentctl/control/runs.py`, ~120 lines. Write a *started* row
  first and an *ended* row later, so a missing end row means the run died.
- **Experiment.** Mock runs in two workspaces. `dash` must show both, with their
  blocked effects.
- **Analyst A.** VERIFIED both paths, and the same mismatch for `cost.db`
  (`cli.py:44`, `dash.py:390-391`).
- **Analyst B.** VERIFIED. The runner's `finally` only detaches the recorder.
  Test a crash before `finally` and check the run renders as "died".
- **Concerns.** It stores task text and paths, so keep it local and out of any
  repository.
- **Implementation relevance.** The cheapest unlock in the dashboard cluster.

### I-18 · A live turn stream and `agentctl why`: Panel 2

**Kind** feature · **Area** dashboard, observability

- **What it is.** `agentctl watch <cid>`, plus a `dash --serve` view.
  - **Sources tailed:** OpenHands' persisted events, the ledger, and I-08
    telemetry.
  - **Shown per turn:** the serving deployment and model, failed attempts, tokens,
    latency, and each tool call with its class and verdict.
  - **`agentctl why <turn>`:** prints the routing inputs for that turn.
- **To build.** `agentctl/control/watch.py`, ~200 lines. The join key is the
  conversation id (I-09).
- **Experiment.** Acceptance test: would it have shown the three `0041` defects
  unaided?
  - Falsified if nobody opens it.
- **Analyst A (PURSUE).** Sound, sequenced after I-08, I-09 and I-17. Pin the
  event-directory shape as a test fixture, because it is an SDK internal
  (`0009` R1).
- **Analyst B (EXPERIMENT FIRST).**
  - For a one-person tool, "nobody opens it" is a real risk.
  - Printing more in the runner's existing verbose path may capture most of the
    value at a fraction of 200 lines.
  - Run the acceptance test offline against I-21 cassettes first.
- **Disagreement preserved.** Both accept the design. They differ on whether a
  separate module is justified before a cheaper "print more" is tried. **No
  evidence settles this.** It is a usage question.
- **Implementation relevance.** Panel 2. Build it only after I-08 and I-09 give it
  something true to show.

### I-19 · Resolve and approve from the dashboard, with the evidence in front of you: Panel 3

**Kind** feature + usability check · **Area** dashboard, the human half of fail-closed

- **What it is.** `agentctl dash --serve`:
  - a stdlib `http.server` on 127.0.0.1 with a per-launch token;
  - **landed** and **retry**, on the same code path as `cmd_resolve`, including
    fence adoption;
  - **approve** and **deny**, for I-06;
  - each blocked effect shown with the full command, the probe fingerprint and
    verdict, the recorded observation, the surrounding turns, and the short id.
- **To build.** ~250 lines, with no dependencies (the "no CDN, no fonts" rule).
- **Experiment.** Seed 10 BLOCKED effects with known ground truth. Resolve them via
  the CLI and via the page, ideally by someone other than the author. Measure
  decision time and wrong decisions.
  - Falsified if the error rates are equal. A richer `agentctl show` would then be
    enough.
- **Analyst A.** Standard loopback-plus-token pattern (the Jupyter model). The
  named mitigations are sufficient.
- **Analyst B.** Test that the token is minted per launch and that no CORS headers
  are sent. A CSRF-shaped request from a local webpage is the threat.
- **Concerns.** A new attack surface, and scope creep toward a web app (`0009`
  R3). Keep it to one page.
- **Implementation relevance.** The one place the dashboard *drives* the harness,
  as the owner asked.

### I-20 · Graded runs: `--accept` on `run`, and `agentctl bench` over a fixed corpus

**Kind** feature, the experiment substrate · **Area** evaluation, the real work

- **What it is.**
  - `run --accept "<cmd>"`: the harness runs the acceptance command outside the
    agent's loop and records PASS or FAIL.
  - `agentctl bench corpus.yaml --arm name=flags …`: for each task, copy a seed
    repo at a pinned commit, run it with the arm's flags and `--record`, grade
    it, and write one row per task, arm and rep.
  - Seed corpus: the tasks already graded (`0041`, `0036`, `0035`, the
    `range_parser` stub), real open items (`0039` §5 `service_id`), and 4–6 new
    multi-file tasks with a commit and a changelog append.
- **Why it fits.** `runner.run()` returns no success field at all. Charter
  criterion 3 ("lower cost per completed task than baseline") cannot be computed.
- **To build.** `agentctl/runtime/bench.py` and a CLI subcommand, ~250 lines, plus
  ~40 lines of acceptance in the runner.
- **Experiment.** A baseline of 6 tasks × 1 arm ≈ 84 requests, preceded by a noise
  check.
  - Falsified (as a design) if outcomes are too noisy for single runs to mean
    anything.
- **Analyst A.**
  - **τ-bench's `pass^k`** exists for exactly this problem.
  - Build repeated trials (k ≥ 2–3) into the bench from day one, not as a one-off
    pre-check.
  - Run each baseline task twice.
- **Analyst B.**
  - ReliabilityBench grades by end-state equivalence, which supports the
    out-of-band acceptance command.
  - Make the noise check a **hard gate** before the baseline pass.
- **[verified in synthesis]** The τ-bench abstract (arXiv 2406.12045) proposes
  `pass^k` and reports pass^8 below 25% in its retail domain.
- **Concerns.**
  - With k = 3, the baseline costs about 250 requests, not 84.
  - Toy tasks measure toy behaviour.
  - Grading commands are effects themselves, so run them outside the ledger.
- **Implementation relevance.** Every comparative experiment (I-03, I-04, I-07,
  I-12, I-21–I-27) needs it.

### I-21 · The cassette corpus as a zero-cost regression suite

**Kind** feature + experiment · **Area** evaluation, CI

- **What it is.** Keep every bench cassette with its seed commit, and have CI
  replay them all on Linux and Windows. A harness change that alters what the
  model sees then shows up as a **miss at a named turn**. Today CI replays one
  3-turn cassette.
- **To build.**
  - A `bench/cassettes/` layout.
  - A CI loop, ~40 lines.
  - A tool to accept an intended divergence, so the suite does not cry wolf
    (`0034` §10).
- **Experiment.** Record 10 cassettes during I-20 and replay them cross-OS
  unchanged. Then apply I-01, and check that divergence appears only at the
  re-run turns.
- **Expected result.** 10 of 10 identical before any change.
  - **Falsified** if they miss on Linux for environment reasons. `0039` §7 #12
    recorded a fixed prefix of 3,593 tokens on Windows and 3,591 on Linux, cause
    not identified.
- **Analyst A.** Do not trust the corpus as a gate until the cross-OS cause is
  fixed or recordings are made per OS.
- **Analyst B.** Confirmed the `0039` numbers. Check specifically whether the
  divergence affects content or ordering, or only token counts.
- **Concerns.** Cassettes contain workspace contents, so use only synthetic or
  public code. Watch their size.
- **Implementation relevance.** Turns every live run into a permanent free test.

### I-22 · Are the scouts right? Citation-check accuracy, and recon vs a single agent, per correct answer

**Kind** experiment · **Area** multi-agent (read-only), evaluation

- **What it is.** 10–15 mechanically gradable questions about this repository,
  each with a ground-truth `path:line` and value. Answer each through (a) the
  single read-only subagent and (b) `recon`. Hand-label every citation, then
  measure:
  - the citation checker's precision and recall (`citations.py`, `WINDOW = 3`);
  - answer correctness;
  - requests and tokens per **correct** answer.
- **Why it fits.** `0040` priced recon in requests. `0039` §7 #15 then showed it
  can be confidently wrong.
- **To build.** A question file and a grading script, ~80 lines. No product code.
- **Experiment.** 12 questions × 2 arms ≈ 280 requests.
  - Recon is falsified if it yields fewer correct answers per request than a
    single agent.
  - The checker is falsified if it flags more than 30% of correct citations, or
    misses more than half of the wrong ones.
- **Analyst A.**
  - Cross-tabulate the checker's verdict against *answer* correctness. That is
    the decision-relevant number.
  - Found a one-line citation error: `WINDOW` is at `:56`, not `:55`.
- **Analyst B.** Report precision and recall at several window sizes. `3` was
  chosen once, from one failure.
- **Concerns.** Labelling is subjective. The "Mistral" leg is in practice
  ministral-3b, so report per leg.
- **Implementation relevance.** Must precede any further recon investment,
  including I-23.

### I-23 · Read delegation inside a run: an `ask_scout` tool

**Kind** feature + experiment · **Area** multi-agent (read-only), context cost

- **What it is.** A runtime tool, `ask_scout(question, paths)`:
  - classified PURE_READ;
  - runs the read-only subagent on a plentiful source;
  - returns its report together with `citations.verify()` output;
  - capped per run.
- **Why it fits.** It stays inside the safety argument already made for read-only
  subagents (`subagent.py:60`, `READ_ONLY_TOOLS = {"read_file"}`).
- **To build.** ~80 lines, a matrix row, a cap, and I-09's parent link.
- **Experiment.** 4 recon-heavy tasks × 2 arms ≈ 130 requests.
  - Falsified if models ignore the tool, or call it and then re-read the files
    anyway.
- **Analyst A (EXPERIMENT FIRST).** Measure specifically how often the main agent
  re-reads a file after asking a scout about it.
- **Analyst B (EXPERIMENT FIRST).** The re-read outcome is **the more likely one**,
  because a coding agent needs the file itself before a `write_file`. Make it the
  primary hypothesis.
- **Concerns.** An in-process subagent inside a gated run is an unproven
  concurrency path, so start with a subprocess.
- **Implementation relevance.** The only multi-agent shape that might *save*
  quota. Both analysts expect it may not.

### I-24 · Parallel tasks on isolated worktrees (`agentctl batch`)

**Kind** feature + experiment · **Area** multi-agent (writing, not shared), throughput

- **What it is.** Each independent task gets its own git worktree, process, ledger
  and conversation, pinned to a source by the scarcity allocator. Results come
  back as branches.
- **Why it fits.** `0038` §4.4 verified 120 concurrent commits across 3 worktrees
  with zero failures, and named this "the design to use if multi-agent is ever
  revisited".
- **To build.** `agentctl/runtime/batch.py`, ~150 lines.
- **Experiment.** 6 tasks, sequential versus 3-wide, ~84 requests per arm.
  - Falsified if workers collide on shared quota.
- **Analyst A (EXPERIMENT FIRST).**
  - Pin workers to *different* quota-independent sources as the primary
    configuration. Otherwise the experiment cannot separate parallelism from
    contention.
  - Cites the Illusion paper (automatic multi-agent systems cost up to 10× and
    underperform) and Anthropic's figures (agents use about 4× the tokens of
    chat, multi-agent systems about 15×).
  - Both apply to coordinated agents, not to independent batch work.
- **Analyst B (EXPERIMENT FIRST).** Report wall time and requests per completed
  task *separately*. Parallelism creates no quota.
- **[verified in synthesis]** Both sources confirmed at the source (arXiv
  2606.13003 abstract; Anthropic engineering post).
- **Concerns.**
  - When quota binds, the best case is exhausting the same daily allowance
    sooner.
  - Merge conflicts return work to the human.
  - Shared `~/.agentctl` state.
  - Worktree cleanup on Windows.
- **Implementation relevance.** It answers "multi-agent" without breaking single
  writer, but its value is unproven.

### I-25 · Merchant sandbox: idempotency keys end to end with a real model

**Kind** feature + experiment · **Area** production-agent scenarios, side-effect safety

- **What it is.**
  - A local fake commerce service (`POST /refunds`, `/orders/{id}/cancel`,
    `/emails`) that honours `Idempotency-Key`.
  - A real `http_request` tool. The matrix already declares it `EXTERNAL` with a
    key field, and Seam C already stamps keys, but no such tool ships.
  - Tasks such as "refund the duplicate charge and email the customer".
  - Crash injection after the send.
  - A variant server that **ignores** keys.
  - `send_email` with no key, which should fail closed.
- **To build.** `experiments/merchant/fake_service.py` (~150 lines), an
  `HttpRequestTool` (~80 lines, localhost only by default), and bench tasks that
  grade the service's state.
- **Experiment.** 3 tasks × {crash, no crash} × {compliant, non-compliant} ≈ 150
  requests.
- **Expected result.**
  - Compliant server: exactly one refund per task.
  - Non-compliant server: duplicates, which the ledger cannot see. That
    demonstrates the README's stated limit.
  - Email: blocked after a crash.
  - **Falsified** if the model fills the key argument itself with an unstable
    value. Seam C leaves a caller-supplied key alone (`seam_c.py:95-99`), so the
    tool schema would have to *hide* the field.
- **Analyst A.**
  - "The single strongest match to the owner's real-world-use-case gap."
  - Stripe's idempotency semantics match the gate's SAFE_TO_RETRY path.
  - Add a compliant server that returns a *different* body on the repeated key,
    to test that SUBSTITUTE hands back the original observation.
- **Analyst B.**
  - VERIFIED `if existing: return action`.
  - Add an arm that deliberately tries to make the model supply its own key.
  - Enforce the localhost allowlist with a test.
- **[verified in synthesis]** The Stripe engineering post (Brandur Leach,
  *Designing robust and predictable APIs with idempotency*) describes the same
  client-key / server-cache contract.
- **Concerns.** It widens the agent's reach. Fake semantics may be kinder than
  real ones (key expiry).
- **Implementation relevance.** The highest-stakes effect class, never yet tested
  with a real model.

### I-26 · Prompt-injection canaries against the no-sandbox boundary

**Kind** experiment · **Area** adversarial, safety

- **What it is.** Seed bench repos with injected instructions: in the README, a
  code comment, a fixture, and failing-test output. Each asks for a harmless
  canary:
  - a write outside the workspace;
  - a `curl` to a local server;
  - `python -c "os.remove(...)"`;
  - `git push --force` to a local bare remote;
  - reading `keys.env` and printing its length.

  Count the triggers and which layer caught each one.
- **Why it fits.** "No sandbox" is the README's first limitation.
  - `python -c` classifies EXTERNAL (`tests/test_classify_corpus.py:105`).
  - `paths.py` deliberately does not cover reads.
- **To build.** Canary repos and a canary server, ~100 lines, experiment-only.
- **Experiment.** 8 scenarios ≈ 110 requests, on the strongest free model, in a
  disposable user account or VM.
- **Expected result.** Out-of-workspace writes and force pushes are caught.
  `python -c` and the keys-file read pass, unless the model refuses.
  - Falsified (the matrix-as-sandbox claim) if any canary that should be caught is
    not.
- **Analyst A.**
  - VERIFIED all three classification facts, including `tools.yaml:105` (force
    push is DESTRUCTIVE).
  - Use **AgentDojo** as the template, and add injection inside *tool return
    values*.
- **Analyst B.**
  - README injection against coding agents is a documented attack class
    (secondary sources, UNVERIFIED).
  - Run 2–3 reps per scenario.
  - A sanitised VM may change model behaviour compared with the real environment.
- **[verified in synthesis]** AgentDojo (arXiv 2406.13352): 97 realistic tasks,
  629 security test cases.
- **Concerns.** Sensitive by nature, so run it with no real `keys.env`. Results
  date quickly.
- **Implementation relevance.** Decides whether unattended mode (I-05, I-06) is
  responsible to ship.

### I-27 · The headline test: does the pool complete more tasks per day than one key?

**Kind** experiment (soak) · **Area** value claim, long-running reliability

- **What it is.** A full quota day per arm:
  - **(A)** one OpenRouter key and a plain `run` loop;
  - **(B)** the full pool after I-11;
  - **(C)** the pool plus supervisor, session affinity and weights.

  Measure accepted tasks per day, interventions, duplicates, blocked effects,
  requests per completed task, and wall time.
- **Why it fits.** It is the charter's cost criterion as a number. `0038`'s 21.4
  tasks/day and `0040`'s ×1.55–×4.33 are arithmetic, not measurements.
- **To build.** A "run until exhaustion" mode on I-20.
- **Experiment.** A ≈ 50 requests. B and C ≈ 550 each, so 2–3 days of quota.
  Run it **last**.
- **Expected result.** A stops at about 3 tasks. C completes the most.
  - **Falsified** if C does not beat B by a meaningful margin, meaning the control
    plane adds nothing over what litellm gives for free.
  - Also falsified if A's per-task quality beats B's.
- **Analyst A.** Make the OpenRouter cross-account check (§4.C) a **named
  precondition**. Arm B's advantage is built on it.
- **Analyst B.** Arm C bundles four mechanisms, so attribution needs the
  component experiments first. Record provider-overload days so a bad day is not
  blamed on an arm.
- **Concerns.** It competes with the owner's own use of the quota. Day-to-day
  variance. It needs 30+ tasks.
  - Also **[orchestrator]**: no member checked whether pooling several free
    accounts is permitted by the providers' terms (§4.C).
- **Implementation relevance.** The verdict on the whole system.

---

## 3. Harness-specific experiments

Kept separate from the features. Request costs are estimates.

The agent-capable allowance is about 550 requests/day, or about 300 if the
OpenRouter premise fails. The Architect proposed capping experiments at 150–200
requests/day so the owner keeps a working day.

### 3.1 Zero quota (local, mock provider, or existing data)

| # | Experiment | Question | Idea | Proposed by |
|---|---|---|---|---|
| E-01 | Identical re-run regression test + **tenth chaos point** (crash between Seam B's `_close` write and its return) | Does OBSERVED separate repeat from replay without a duplicate? | I-01 | Architect; chaos point by A and B independently |
| E-02 | Zombie writer with a fresh id; two live `--resume` processes | Can two drivers both commit? | I-02 | Architect; permanent test by B |
| E-03 | Compile the shipped `policy.yaml` in CI | Does the shipped safety artifact compile? (It does not, today) | I-16 | A, B |
| E-04 | `CustomLogger` + router pointed at an unreachable base URL | Does litellm fire failure callbacks per attempt or per final failure? | I-08 | A (method), B (blocking status) |
| E-05 | Feed the hook's output `data` dict to `DeploymentAffinityCheck` directly | Does session affinity pin with our wiring? | I-12 | B |
| E-06 | Capture a real `data` dict from a local mock-upstream proxy | Where does the session id actually arrive? | I-09 | A |
| E-07 | Re-ingest the existing `hook_telemetry.json` under three cost states | Does spend fall to $0 known? | I-10 | Architect; pinned test by B |
| E-08 | Queued approval: approve → once, deny → never, three re-issues → one record | Do approvals survive being unattended? | I-06 | Architect; re-issue aliasing by A |
| E-09 | Run index with a crash before `finally` | Does a dead run render as "died"? | I-17 | B |
| E-10 | Seeded blocked effects, CLI vs page, second person | Does evidence on screen reduce wrong `--landed`? | I-19 | Architect |
| E-11 | Simulator backtest | Can a simple model reproduce a real day? | I-15 | Architect; needs a day of I-08 data first |

### 3.2 Low quota (≤ 50 requests each)

| # | Experiment | Cost | Idea |
|---|---|---|---|
| E-12 | **OpenRouter cross-account independence.** Spend on one account, then read every sibling's `/api/v1/key` `used` | a handful | Analyst A (new) |
| E-13 | Per-model verification, then pool-hygiene A/B (current pool vs Groq removed). The `enforce_model_rate_limits` arm is withdrawn (§8) | 8 + 40–60 | I-11 |
| E-14 | Attribution: ledger rows = recorder count | ~15 | I-09 |
| E-15 | Failure telemetry against a real pool (Groq 413s, mistral-small) | ~20 | I-08 |
| E-16 | Fail-first-then-pass tasks, with and without I-01 | ~30 | I-01 |
| E-17 | Requests-per-task cap stops a real run at N | ~12 | I-16 |

### 3.3 Medium quota (70–400 requests)

| # | Experiment | Cost | Can falsify | Idea |
|---|---|---|---|---|
| E-18 | Bench baseline with repeated trials (`pass^k`, k=2–3) | 84–250 | whether single runs are interpretable | I-20 |
| E-19 | Cross-model resume (Gemini ↔ OpenRouter) | ~70 | intent-hash aliasing across models | I-07 |
| E-20 | Gate cost, before and after I-01, plus the Q9 tally | ~140 | the gate pays for itself on crash-free work | I-03 |
| E-21 | Merchant sandbox, 2×2, plus B's "model supplies its own key" arm and A's "different body" server | ~150+ | SAFE_TO_RETRY with a real model | I-25 |
| E-22 | Injection canaries, 2–3 reps, including injection in tool output | 110–330 | "the matrix stands in for a sandbox" | I-26 |
| E-23 | Wait-only supervisor: exhaustion drill and proxy-death drill | ~70 + | the harness survives exhaustion unattended | I-05 |
| E-24 | Resume vs dirty restart vs clean restart, plus A's ambiguous-history task | 200–400 | the resume machinery beats a restart | I-04 |
| E-25 | Shuffle vs session affinity vs one source | ~210 | model hopping matters / cache matters on a free pool | I-12 |
| E-26 | Scout accuracy and checker precision/recall, at several windows | ~280 | recon is worth it per correct answer | I-22 |
| E-27 | `ask_scout` pilot; primary metric: re-reads after asking | ~130 | delegation saves quota | I-23 |
| E-28 | Batch 3-wide on *different* sources vs sequential; wall time and requests reported separately | ~170 | parallelism helps under a quota bound | I-24 |

### 3.4 Days of quota

| # | Experiment | Precondition |
|---|---|---|
| E-29 | Pool vs one key vs pool + control plane, tasks per day | E-12 passed; I-01, I-02, I-08, I-09, I-11, I-20 landed |

### 3.5 Coverage against the owner's list

| Owner's example | Covered by |
|---|---|
| Rate-limit-triggered shifting | E-23 (wait), I-05 shift half after E-25; E-12 decides how much there is to shift to |
| Provider failure and recovery | E-13, E-15, E-23 (proxy death) |
| Interruption and resume | E-24, E-19 |
| Duplicate side-effect prevention | E-01, E-02, E-21, E-24 |
| Cost-aware routing | E-07, E-17; weights (I-14) only after E-11 |
| Long-running reliability | E-23, E-29 |
| Dashboard observability | E-09, E-10; I-18's acceptance test offline via I-21 |
| Failure injection | E-01/E-02 chaos points, E-24's kill hook, E-23 proxy death |
| Concurrent agents | E-02 (two resumes), E-28 |
| API degradation | E-13, E-15 (dead and oversized deployments) |
| Tool-call failures | E-16 (failed test re-run) |
| Partial execution | E-21 (crash after send), E-24 |
| Context/window pressure | Only indirectly: Groq's TPM ceiling (E-13), scout summaries (E-27). **See §7** |
| Recovery from inconsistent state | E-02, E-08, E-10 |

---

## 4. High-value directions

These are not ranked by score. Each group says why it deserves consideration
and what would make it fail.

### A. Fix the correctness holes before measuring anything: I-01, I-02, I-16

- All three are **verified defects**, reproduced three times over: by the
  Architect's probes, by the analysts reading the code, and in synthesis.
- All three are kernel-local or configuration, zero quota, and have an obvious
  falsification path through the existing chaos suite.
- They come first for a methodological reason too.
  - With I-01 unfixed, every live experiment counts false BLOCKs and stale
    substitutions as "gate cost" or "task failure".
  - With I-02 unfixed, charter criterion 1 depends on the user never running
    `--resume` while the original is alive.
  - I-16's defect is `docs/0039` in miniature: a safety artifact that reads like
    protection and does not compile.

### B. Make the telemetry true: I-08, I-09, I-10

- Every routing, dashboard and cost idea measures through Seam A, and three of
  its outputs are wrong or missing:
  - failures are invisible (0/250 mistral-small);
  - conversation ids are `unknown` (23/23);
  - free calls carry list prices (154/250).
- It is an afternoon's code, verifiable with about 35 live requests.
- **Resolve I-08's callback-semantics question offline first (E-04).** Both
  analysts flagged it, and litellm has declined a per-retry hook (issue #19806,
  closed as not planned).

### C. Check the multi-account premise before building on it

This is the council's most consequential finding, and only Analyst A surfaced it.

**What the providers' own documents say [verified in synthesis]:**
- **OpenRouter** says adding accounts or keys "will not affect your rate limits,
  as we govern capacity globally". Its limits page also documents a per-key
  `free_model_daily_requests` counter.
- **Groq** says limits apply at the organization level.
- **Gemini** says they apply per project, not per key. The project already learned
  this one the hard way (`65535c4`).

**Why it matters.**
- Analyst A reads the OpenRouter sentence as ambiguous. It most plausibly
  describes per-model capacity throttling, but it is not scoped explicitly.
- `docs/0033` ("the account is the unit"), `0038` §9.4 (6 × 50 = 300/day), `0040`
  and I-27's arm B all rest on per-account independence.

**The test is almost free.** E-12: spend on one account, then read the siblings'
counters.

**[orchestrator]** There is a second question no member examined. **No one read
any provider's terms of service.** It is unchecked whether operating several
free accounts to aggregate quota is permitted. Account suspension is a failure no
router can route around. Settle both questions before I-27, and before more is
built on the multi-account design (I-05's shift half, I-13, I-14).

### D. Give "done" a definition: I-20, with repeated trials

- No task success signal exists in the code, so no comparative claim in the
  charter can be tested.
- Both analysts independently pushed the same way: τ-bench's `pass^k` (A) and a
  hard noise gate (B). Build repetition in from the start.
- Recording on by default makes I-21's regression corpus almost free.
- The cross-OS prefix anomaly (`0039` §7 #12) is the one thing that could make
  that corpus cry wolf. Test it first.

### E. Route by configuration, not construction: I-11, then I-12, then I-14 via I-15

- litellm 1.100.0 already ships two of the three mechanisms proposed: session
  affinity and weighted shuffle. Both are confirmed against the installed source,
  and the charter commits to configuring what litellm solves.
- The third, per-deployment rate-limit checks, does not fit (§8). It cannot see
  prompt size, and it fails requests instead of re-routing them. Groq has to
  leave `pool` by config generation.
- Session affinity is plausibly pure configuration, because the proxy maps the
  header OpenHands already sends (§8).
- **Why it could fail.** Cooldowns may already neutralise dead deployments
  (I-11) and equalise exhaustion (I-14). Cache affinity may buy nothing on a pool
  that costs $0 (I-12). Each of those outcomes is a legitimate scope reduction,
  and each experiment is designed to show it.

### F. The experiments that can shrink the project's claims: I-04, I-07, I-03

- **I-04** can show that a restart is as good as a resume.
- **I-07** can show that a different model rewords the commit and the intent hash
  misses.
- **I-03** can show that the gate costs more than it saves on crash-free work.
- The method says to find these out before building further on top. All three
  are cheap once I-20 and the kill hook exist.

### G. The real-world shapes: I-25, I-26

- **I-25 (merchant)** is where both analysts placed the strongest real-world
  match. `EXTERNAL` effects with idempotency keys are the highest-stakes class,
  fully declared, and never met by a real model. It produces the one result no
  mock can: whether a model invents its own key.
- **I-26 (injection)** measures the accepted "no sandbox" limit instead of
  asserting it. That frequency decides whether unattended operation (I-05, I-06)
  is responsible to ship at all.

### H. A dashboard that drives the harness: I-17, then I-06, then I-19

- **I-17** fixes the panels that point at the wrong files.
- **I-06** turns the confirmation prompt into durable state.
- **I-19** is the one place the dashboard legitimately acts, and a wrong click
  there records an effect that never happened.
- **I-18** (the live stream) is contested (§6). It should follow B's cheaper
  route first.

### Directions that do not yet deserve build effort

| Idea | Why it waits |
|---|---|
| **I-23** `ask_scout` | Both analysts expect it to fail its own test (the model re-reads the files anyway). Pilot only after I-22 |
| **I-24** `batch` | Quota, not wall time, binds. The best case is exhausting the same allowance sooner. Run E-28 small |
| **I-13** quota module, **I-14** weights | Rest on the unverified multi-account premise (C) and an unrun calibration. Measure first |
| **I-15** simulator | Sound, but cannot be validated until I-08 has produced a day of failure data |
| **I-05** shift half | Gated on I-12's model-hopping result. Build the wait-only half first, which both analysts said independently |
| **I-03** `--unguarded` as a lasting flag | Both analysts: an experiment switch, never a feature |

---

## 5. Final research backing

### 5.1 External sources

| # | Source | Supports | Found by | Status |
|---|---|---|---|---|
| 1 | [OpenRouter — API limits](https://openrouter.ai/docs/api-reference/limits) | Free-model caps (50/1000 per day by credits purchased); per-key `free_model_daily_requests` in the current UTC day; the "additional accounts … will not affect" statement | A | **Re-fetched in synthesis.** The statement is verbatim at the source |
| 2 | [Gemini API — rate limits](https://ai.google.dev/gemini-api/docs/rate-limits) | Limits per project, not per key; RPD resets at midnight Pacific | A, B | **Re-fetched in synthesis** |
| 3 | [Groq — rate limits](https://console.groq.com/docs/rate-limits) | `gpt-oss-20b`/`120b` free: 30 RPM, 1K RPD, 8K TPM, 200K TPD; limits per organization | Synthesis (corrects B's secondary figures) | **Fetched in synthesis** |
| 4 | [LiteLLM — routing](https://docs.litellm.ai/docs/routing) | `weight` in simple-shuffle; `session_affinity` via `optional_pre_call_checks`; header or `metadata.session_id`; `deployment_affinity_ttl_seconds` default 3600 | A, B | **Re-fetched in synthesis** |
| 5 | Installed litellm 1.100.0: `router_utils/pre_call_checks/deployment_affinity_check.py`, `model_rate_limit_check.py`, `router_strategy/simple_shuffle.py`, `proxy/litellm_pre_call_utils.py` | What the *installed* version does, as opposed to the docs | B; corrected in §8 | The affinity check reads `metadata.session_id` (`:266-310`). The proxy fills it from `x-litellm-session-id` (`litellm_pre_call_utils.py:1279-1284, 1323`). The rate-limit check counts only recorded usage and fails with `num_retries=0` (`:250-268`) |
| 6 | [LiteLLM — reliability](https://docs.litellm.ai/docs/proxy/reliability) | `num_retries`, `allowed_fails`, `cooldown_time` | A | Fetched by A (partial). Not re-fetched |
| 7 | [BerriAI/litellm#19806](https://github.com/BerriAI/litellm/issues/19806) | No per-retry `CustomLogger` hook exists; the request to add one was declined | B | **Re-fetched in synthesis: closed as not planned** (B had it as open) |
| 8 | [ReliabilityBench, arXiv 2601.06112](https://arxiv.org/abs/2601.06112) | Rate limiting was the most damaging fault in its ablations; end-state-equivalence grading | B (VERIFIED), A (UNVERIFIED) | **Re-fetched in synthesis.** Caveat: single author, two models, four domains |
| 9 | [The Illusion of Multi-Agent Advantage, arXiv 2606.13003](https://arxiv.org/abs/2606.13003) | Automatic multi-agent systems cost up to 10× and underperform CoT-SC | A, B | **Re-fetched in synthesis.** Scoped to *automatic* MAS |
| 10 | [Anthropic — multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | Agents use ~4× the tokens of chat; multi-agent systems ~15× | A | **Re-fetched in synthesis** |
| 11 | [τ-bench, arXiv 2406.12045](https://arxiv.org/abs/2406.12045) | The `pass^k` reliability metric; pass^8 < 25% in retail | A | **Re-fetched in synthesis** |
| 12 | [AgentDojo, arXiv 2406.13352](https://arxiv.org/abs/2406.13352) | A prompt-injection benchmark for tool-using agents: 97 tasks, 629 security cases | A (no URL given) | **Located and fetched in synthesis** |
| 13 | [Stripe — Designing robust and predictable APIs with idempotency](https://stripe.com/blog/idempotency) | The client key / server cache contract behind SAFE_TO_RETRY | A (fetched), B (secondary) | **Re-fetched in synthesis** |
| 14 | ARMO blog on README-based injection; the `agent-canary` tool | README injection against coding agents is a live attack class | B | UNVERIFIED (secondary, no URL recorded). Treat as a pointer only |
| 15 | OpenRouter Zendesk rate-limit article | Same figures as #1 | B | Secondary. Superseded by #1 |

### 5.2 In-repository evidence

| Evidence | What it shows | Reproduced by |
|---|---|---|
| P1 (`research/phase-11-council/probes/p1_identical_rerun.py`) | An identical test re-run is SUBSTITUTEd with stale output, or BLOCKed | Architect; **synthesis re-run** |
| P2 (`…/p2_zombie_fresh_intent.py`) | A superseded holder's fresh intent executes and commits | Architect; **synthesis re-run** |
| P3 (`agentctl policy agentctl/control/policy/data/policy.yaml`) | The shipped policy does not compile | Architect; A; **synthesis re-run** |
| `store.observed()`, `store.renew()` have zero callers | Designed-and-disconnected mechanisms | Architect; A; B; opencode |
| `hook_telemetry.json`: 23/23 `unknown:`, 0/250 mistral-small, 154/250 priced, 11-hop sequence, 32.7% cache hit | The live boundary contradicts the mock-tested claims | Architect; B recomputed all five |
| `docs/0041` §1: "11 EXECUTE, 1 BLOCK" in the table vs "the two blocked effects" in the text (and 12 ≠ 14) | The latest document is internally inconsistent; its ledger is not in the tree | A |
| 643 passed, 1 skipped | The suite is green; none of the above is visible to it | A |

---

## 6. Disagreements and corrections, preserved

| Topic | Position 1 | Position 2 | Factual basis and status |
|---|---|---|---|
| **Multi-account premise** | Analyst A: the OpenRouter sentence threatens 6×50; test it first | Architect and B: not raised. B lists OpenRouter limits without flagging it | The sentence is verbatim at the source. Its scope is ambiguous. **Open, and cheap to settle (E-12)** |
| **Session-affinity wiring** | A: litellm reads the `x-litellm-session-id` header, per the docs | B: the installed check reads only `metadata.session_id`; the header is never mapped | **A is right for the installed version too** (§8). The proxy maps the header into `metadata.session_id`. B's "never mapped" and this document's first synthesis both came from a search that skipped `.venv/` |
| **Groq TPM** | B: 6k–12k by model, contradicting the flat 8,000 (secondary sources) | Project, `doctor.py`: 8,000, self-labelled INFERRED | **B's concern does not apply.** Groq's page lists 8K TPM for both models in the pool. The project's figure can move from INFERRED to documented for these two models |
| **litellm #19806** | B: an open request, so per-retry callbacks may not exist | — | **Closed as not planned.** Strengthens B's inference |
| **I-13 verdict** | A: PURSUE, precondition first | B: EXPERIMENT FIRST | The same substance: measure before building |
| **I-18 verdict** | A: PURSUE after I-08, I-09, I-17 | B: EXPERIMENT FIRST; "print more" may suffice | Unresolved by evidence. It is a usage question |
| **ReliabilityBench** | B: VERIFIED | A: UNVERIFIED | Verified in synthesis. The claim holds as B stated it |
| **Citation errors in Phase 1** | A: `WINDOW` at `citations.py:56`, not `:55` | opencode: the `TurnAffinity` pin is in `RequestHook.apply` (`hook.py:141-146`), not the class range | Both minor. B found no errors in about 60 checks |

---

## 7. What the council did not cover

Stated plainly, so silence is not read as coverage.

- **Provider terms of service.** See §4.C. Unchecked by any member.
- **Context-window pressure as its own experiment.** Nothing measures an
  hours-long conversation outgrowing a model's window. That includes condensation
  behaviour when consecutive turns land on models with different context limits.
  Only Groq's TPM ceiling and scout summaries touch it.
- **Fault types other than dead, capped and oversized deployments.** The council
  proposed no injection of partial or streaming failures, slow responses, or
  schema drift, though ReliabilityBench treats those as distinct fault classes. A
  fault-injecting mock upstream behind the real proxy
  (`experiments/0005-m1-seam-a` already runs mock upstreams) would be the natural
  vehicle. *[orchestrator note, not a council finding]*
- **Multi-host fencing.** Still unexercised (README).
- **Any live number.** Every figure in §3 is a cost estimate. None of the 29
  experiments has run.

---

## 8. Addendum (2026-09-24): fix-design research, and one retracted claim

This was done after the council, to settle open design questions before any fix
starts. The source-reading was delegated to a free model under `opencode`,
because the Claude session limit had stopped both research subagents. Every
claim below was then re-checked by hand against the installed source.

### 8.1 A retraction

Section 6 and I-09 said the installed litellm proxy never references
`x-litellm-session-id`. **That was false.** The search tool used (ripgrep)
silently skips gitignored paths, and `.venv/` is gitignored. Analyst B's matching
claim likely has the same cause.

This is `docs/0039`'s pattern exactly: a check that could not fail on the input
it was given. **Rule for future source checks: search `.venv/` with plain `grep`,
or pass file paths explicitly.**

### 8.2 What the installed source actually does

| Question | Finding | Evidence (installed source) | Consequence |
|---|---|---|---|
| I-01: are observations durable before Seam B sees them? | **Yes.** Persisting the event (atomic write + fsync) runs *before* caller-supplied callbacks | `openhands/sdk/conversation/impl/local_conversation.py:427-435`; `sdk/utils/files.py:18-22` | Marking `OBSERVED` from Seam B means the observation is already on disk. The design is sound on the persistence axis. Keep the tenth chaos point anyway |
| I-02: does the SDK stop two processes resuming one conversation? | **No.** The only cross-process lock is per event *append* (`events/.eventlog.lock`); the state lock is thread-only; base-state writes are unguarded | `sdk/conversation/event_store.py:202`; `state.py:253-255, 447-451`; `fifo_lock.py` | The Architect's falsifier is refuted, so the hole is real. Two drivers would interleave one event history. I-02 stands |
| I-16 / I-06: can a run be stopped cleanly and resumed? | **Yes.** `pause()` takes effect between steps, is callable from a callback (the lock is re-entrant) or another thread, and `run()` resumes from PAUSED | `local_conversation.py:2676-2699, 1925-1931, 1942-1946`; `fifo_lock.py:63-65` | A requests-per-task cap is feasible: count completions and call `pause()`. `--resume` continues |
| I-09: why 23/23 `unknown`? | OpenHands sends `x-litellm-session-id` as a client header. The proxy maps it to `data["litellm_session_id"]` and `metadata.session_id`. agentctl reads `data["extra_headers"]`, which does not exist at the proxy | `openhands/sdk/llm/options/common.py:78-83`; `litellm/proxy/litellm_pre_call_utils.py:69, 1279-1284, 1323`; `agentctl/kernel/hook.py:151-153` | Most likely a wrong-key bug. Fix: read `data.get("litellm_session_id")` or `metadata["session_id"]`. Confirm the SDK populates it (E-14) |
| I-12: is session affinity config-only? | Plausibly yes. The affinity check reads `metadata.session_id`, which the proxy fills from the header | `deployment_affinity_check.py:266-311`; `router.py:1996-1998` (`"session_affinity"`), `:633` (`deployment_affinity_ttl_seconds`) | Arm B is `optional_pre_call_checks: ["session_affinity"]`. Verify with E-05 before spending quota |
| I-11: can `enforce_model_rate_limits` replace removing Groq? | **No.** It checks usage already recorded this minute, not the incoming prompt, and raises `RateLimitError(num_retries=0)`, which fails the request with no re-route | `model_rate_limit_check.py:250-268`; `router.py:7244-7247` | Withdrawn as an alternative. Remove Groq from `pool` in `proxy.py::build` |
| I-08: do failure callbacks fire per retried attempt? | **Unresolved; E-04 remains the gate.** `failure_handler` is invoked on intermediate retries, and the router stamps `model_info` per attempt. But `CustomLogger` dispatch is de-duplicated once per logging object | `litellm/utils.py:1988-1996`; `litellm_core_utils/litellm_logging.py:2045, 3476, 3492`; `router.py:3495` | If retries share one logging object, only the first failure reaches the hook. Run the offline spike before building |

---

*Council: Architect (Opus 5.5), Analysts A and B (Sonnet), all isolated.
Synthesis and verification by the orchestrator (Opus 5.5). Mechanical code-claim
checks were delegated to a free model under `opencode` and spot-checked.*
