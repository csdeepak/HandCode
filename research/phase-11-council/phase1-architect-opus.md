# Phase 1 — Architect's Ideas

Repository: `C:\Users\csdee\openhands` (`agentctl`), HEAD `6870711`, read on 2026-09-24.
Working tree: clean except `hook_telemetry.json` (uncommitted, rewritten by a proxy
run on 2026-09-21 15:18–15:27 local time, *after* `6870711`). I used that file as
evidence, and it is the only telemetry from a live pooled run in the tree.

Method. I read `docs/0041` first, then `README`, `INDEX`, `0001`, `0009`, `0013`,
`0021`, `0023`, `0030`, `0032`–`0041`, the relevant parts of
`research/phase-10-5`, and every module under `agentctl/`. I ran no provider and
spent no quota. I ran three things locally with the repo's own venv, all writing
only to the scratchpad:

- **P1**: a gate probe that re-runs an identical test command. It found a defect (I-01).
- **P2**: a zombie-writer probe. It found a defect (I-02).
- **P3**: `agentctl policy <shipped policy.yaml> --out <scratch>`. It failed to compile (I-16).

Reproduction snippets are inline where they matter.

Citations use `path:line` against HEAD, or `docs/NNNN §x`.

---

## A. Current state as I understand it

### A.1 Capabilities by tier

**(a) Implemented and run against a real provider**

| Capability | Evidence | Caveat |
|---|---|---|
| `agentctl run` end to end: real tools, real model, through the proxy | `docs/0041` §1 (divide-by-zero, 3 passed), `0036` §1 (cart discount), `0035` §2 (dogfood) | All three are one-file toy fixes. No task-level success signal exists in code (runner returns decisions + blocked only, `agentctl/runtime/runner.py:274-287`) |
| Effect ledger + gate verdicts on live traffic | `0041` §1 table: 14 effects, 11 EXECUTE, 1 BLOCK | The two blocked effects were failed bash commands, and `0041` called them right. P1 suggests at least some were false blocks (I-01) |
| Crash + resume with no duplicate commit, against OpenRouter | `0023` §5 (via `experiments/0007-real-provider`, not via `agentctl run --resume`) | "the shuffle sent both runs to `nex-free`", so cross-model resume was **not** exercised live (`0023` §5 caveat) |
| Seam A hook fires in a real proxy and captures the deployment id | `0021` §1 (mock upstreams behind a real proxy); `0023` §5 (3/3 trace ids, real provider); live telemetry: 22 agent records with `deployment` | Conversation attribution is **broken live**: 23/23 pre-call records carry `trace_id = "unknown:…"` (`hook_telemetry.json`), see I-09 |
| Proxy generation with verification on by default, `retry_policy`, `allowed_fails_policy` | `0041` §2.1–2.2: 12/12 through six dead deployments | `check_inference` verifies **one model per provider** (`agentctl/control/probe.py:281` uses `p.default_model`). `mistral/mistral-small-latest` succeeded 0 times in 250 live records (I-11) |
| Source groups and `agentctl models` | `0041` §1 ("all four source groups served tool calls") | — |
| `keys --check`, account-level inference probe | `0034`, `0038` §9.4 (31/31 keys, 6 providers) | — |
| OpenRouter free-quota read (`/api/v1/key`) | `0038` §9.2, §9.4 (six accounts, limit 50) | Manual refresh only (`agentctl/control/dash.py:261-294`) |
| `doctor` networked preflight, Groq headroom warning | `0041` §1 table | Groq mechanism is inferred, not measured (`0039` §5) |
| Record and replay | `0029` (a real session recorded against a real provider); `verify.py` replays `experiments/0008-m6-replay/session.jsonl` in CI on Linux and Windows | The cassette is only 3 turns |
| Read-only subagent | `0039` §1 #8 (found by running it for real) | Only the CLI invokes it. The main agent cannot delegate (no task tool) |
| `recon` fan-out, allocated by scarcity | `0039` §7 #14–#15 (first live fan-out, 11 requests); `e58988a` | 1 of 2 scout reports was confidently wrong (`0039` §7 #15) |
| Tree-kill bash timeout | `0036` §2 (found live, measured) | — |
| Keys pre-commit hook | `0034` §10 (staged a real key; commit refused) | — |
| Classifier on live commands | Runs on every live call (`0041`) | Accuracy is measured only on a 75-command synthetic corpus (`0026`). Every interpreter and test runner is `EXTERNAL` (P1) |

**(b) Implemented, tested only against a mock or locally**

| Capability | Evidence |
|---|---|
| `agentctl run --resume` as a CLI path | No test drives `runner.run` (only `inspect.getsource`, `tests/test_runtime_tools.py:245-252`). The live crash/resume in `0023` predates `agentctl run` (`0025`) |
| Intent-hash aliasing across models (`find_by_intent`) | Built from the `0023` §4 live failure. Only unit tests exercise the fix |
| Batch false-`LANDED` fix (`_sole_writer`, Seam C `recapture`) | `agentctl/kernel/gate.py:196-237`; `c8113f3`; mock/local tests |
| Account-wide daily-cap failover | `0021` §1 used mock 429s. No live run has ever exhausted a real account and continued |
| `--confirm-destructive` and escaping-writes authorization | `agentctl/runtime/runner.py:290-338`, `agentctl/kernel/paths.py`. Not recorded firing in a live run |
| Filesystem append probe, idempotency-key probe, Seam C key stamping | `agentctl/kernel/reconcile/filesystem.py`, `external.py`, `agentctl/adapters/openhands/seam_c.py:80-107`. Chaos suite with a mock |
| Nine-point chaos suite | `docs/0019`, `tests/test_chaos_nine_point.py`. Each run issues one effect of two kinds (README "What it does not do yet") |
| Policy compile, pre-run budget refusal, escalation prompt | `experiments/0009-m7-policy`. **P3: the shipped `agentctl/control/policy/data/policy.yaml` no longer compiles** (its `tiering:` block at line 38 is now refused), and `policy.compiled.json` is stale from 2026-09-13 |
| Short-id prefix resolution | `tests/test_cli.py:88-131`. It was fixed after `0041` but has not been re-run live against a Gemini id |
| Citation check on scout reports | `agentctl/runtime/citations.py` (`3971f5d`). The working-tree telemetry shows a three-source pooled session after the commit, but nothing records its outcome |
| Plugin audit | `agentctl/runtime/plugins.py`. Local only |
| `tool_concurrency_limit=1` pin | `agentctl/runtime/runner.py:40-70` |
| Fencing across hosts | README: "implemented and tested; multi-host is not exercised" |

**(c) Declared or configured, but not acted on (or acting on nothing)**

| Item | Where | Why it is inert |
|---|---|---|
| `TurnAffinity` "turn-atomic routing" | `agentctl/kernel/hook.py:86-165` | It pins `data["model"]`, which in a pre-call hook is the **group name** (`pool`, `pool-openrouter`). The router then picks a deployment. It also fires only when `mid_turn` is true, and `mid_turn` was false in **23/23** live calls, because OpenHands only calls the LLM after every tool result is in. Live telemetry shows one conversation hopping OpenRouter accounts *and models* on nearly every turn |
| Policy `pools`, `escalate_to.when.{or_after_failures, requires_capability}` | `agentctl/control/policy/data/policy.yaml:8-23`; `docs/0030` §6 | Recorded, never routed by. `escalation()` has no callers beyond display and the pool-boundary prompt (`0039` §5). Pool members (`openrouter/free`, `mistral/free`, …) match **no** model string the proxy exposes, so any `--policy` run against `openai/pool` hits the "not in the default pool — spend on it?" prompt (`agentctl/runtime/runner.py:418-433`), which reads EOF as refuse |
| USD budgets (`--max-budget`, `per_task_usd`) | `agentctl/runtime/runner.py:233-238` | `max_budget_per_run` compares `accumulated_cost`, which is 0.0 on unpriced endpoints (`docs/0038` §2). The cost figures are also wrong in the other direction (I-10) |
| `EffectState.OBSERVED` | `agentctl/kernel/ledger/models.py:65,77`; `agentctl/kernel/ledger/store.py:349-350` | Nothing ever calls `observed()` |
| Lease renewal and release | `agentctl/kernel/ledger/store.py:135-146` | No caller. The lease TTL is 60 s (`agentctl/adapters/openhands/__init__.py:88`), so after the first minute of a run the lease is just a row |
| `http_post`, `http_request`, `send_email` rows, the `IdempotencyProbe` path | `agentctl/control/matrix/data/tools.yaml:132-140` | The runtime ships only `execute_bash`, `read_file` and `write_file` (`agentctl/runtime/tools.py:317-321`). No real `EXTERNAL`-with-key tool exists |
| `AGENTCTL_TELEMETRY` set by the runner | `agentctl/runtime/runner.py:133-134` | The hook that reads it lives in the *proxy* process (`proxy/agentctl_hook.py`), so nothing in the runner's process reads it |
| `service_id=` on `LLM` | `agentctl/runtime/runner.py:220`, `agentctl/runtime/subagent.py:210` | The field is silently discarded (`0039` §5) |
| `cost_per_task` | `agentctl/control/cost/ledger.py:183-185` | Nothing defines a completed task, and conversation ids are "unknown" live |
| The `modify_params` synthetic-tool-result decision | `docs/0038` §5.1 | Declared an open decision, never taken |

**(d) Described in docs only**

- Free-tier orchestrator: a local consumption model per endpoint and an `allowances.yaml` (`docs/0013` §2).
- Dashboard Panels 2–4: live turn stream, session list with resolve buttons, weekly cost and cache view; M8 on FastAPI plus HTMX (`docs/0013` §3).
- `agentctl resume`, `cost today`, `why <turn>`, push notifications, session journal export (`docs/0013` §4).
- Cache affinity and cache-aware context layout; Q4, deployment affinity (`docs/0009` Q4, `0013` §7).
- Speculative execution, gated on Q9 (`docs/0010` §6.4, `0009` Q9).
- Capability broker and multi-source MCP (`docs/0010` §8.3).
- Recon build steps 5 (`--max-output-tokens` for scouts), 7 (concurrent fan-out) and 8 (subagent conversation linked to its parent) (`research/phase-10-5` §7).
- Worktree-per-worker multi-agent topology. Only the probe test landed (`docs/0038` §4.4).
- Goose/ACP portability spike (`docs/0038` §6).

### A.2 Architectural assumptions in force

1. **Single writer per conversation and workspace.** The lease, `find_by_intent`, the git probe and the handoff all assume it (`docs/0038` §4.2). Writing multi-agent is SKIP on safety grounds at any budget (`0038` §10.3). P2 shows the enforcement is weaker than the assumption (I-02).
2. **Kernel/control boundary.** The kernel has no network access and no harness imports, and the control plane may fail. `tests/test_boundaries.py:24-44` enforces this, and it is why budget spend is *supplied* to the kernel, never fetched (`docs/0030` §4).
3. **Effect decisions fail closed; cost decisions fail open** (`docs/0008` §6.5, `0030` §3). `guard()` never raises (`agentctl/kernel/gate.py:52-61`).
4. **Seam B decides; Seam C only substitutes** (README "How it works"; `agentctl/adapters/openhands/seam_c.py:53-78`).
5. **Derived, never asserted.** A panel with nothing behind it says so, and "Can I work right now?" is structurally `UNKNOWN` (`agentctl/control/dash.py:208-240`; `docs/0039` §4 rule).
6. **No rate limits in source.** A test asserts it (`agentctl/control/providers.py:13-22`; `docs/0032` §2).
7. **Never silently spend.** `paid` is a group you ask for by name, never a fallback (`agentctl/control/proxy.py:341-351`; `docs/0002` §5).
8. **No sandbox.** `execute_bash` runs on the host, and `python -c` is opaque to the classifier (README).
9. **The quota facts.** OpenRouter 6×50 = 300 RPD. Gemini 250 RPD for **one** project. Mistral exposes per-minute limits only, with any daily cap unknown. Groq cannot carry an agent turn past turn 1 (~311 tokens of headroom). Cerebras is excluded (`docs/0040` §6, `0038` §9.4). Live telemetry adds that `mistral-small-latest` never succeeded once (I-11). The agent-capable daily allowance is therefore roughly **OR 300 + Gemini 250 ≈ 550 requests ≈ 39 tasks at the measured 14 req/task** (`docs/0038` §4.1), plus ministral-3b, which is a 3B model.
10. **`tool_concurrency_limit = 1`**, pinned with a `raise` (`agentctl/runtime/runner.py:40-70`).
11. **Replay pins the model, not the world** (`docs/0029`). The workspace must start where the recording did.
12. **The live-boundary rule**: a feature never run against the real boundary is not done (`docs/0041` §3).

### A.3 What is missing relative to the gap statement

- **The real work.**
  - The most common coding loop, edit → run tests → fix → re-run the *same* test command, is mishandled by the gate. The identical re-run either gets the **stale recorded output** (SUBSTITUTE) or is **BLOCKED** (P1, I-01).
  - Nothing defines or checks task success.
  - Confirmations call `input()` and block an unattended run forever, or refuse on EOF.
  - A run that exhausts the pool exits (`agentctl/runtime/runner.py:251-263`) and waits for a human to type `--resume`.
- **The dashboard.** It is a one-shot snapshot.
  - By default it reads `./ledger.db` (`agentctl/cli.py:43`, `agentctl/control/dash.py:364`), but runs write `<ws>/.agentctl/ledger.db` (`agentctl/runtime/runner.py:130`).
  - SPEND stays empty until someone runs a manual `ingest`, and conversation attribution is "unknown".
  - It has no live view, no resolve, and no link from a run to its data.
- **Routing and rate limits.**
  - `pool` uses uniform `simple-shuffle` over 48 deployments covering eight models, from ministral-3b to nemotron-ultra-550b, including 12 Groq deployments that 413 after turn 1 (`agentctl/control/proxy.py:224,303`).
  - Seam A records **successes only** (`agentctl/adapters/litellm/hook.py:26-42`), so 429s, 413s and dead deployments are invisible.
  - There is no quota model, and the one routing rule declared (turn affinity) is inert.
- **Experiments.** None of the charter's comparative claims has a baseline arm: cost per completed task versus baseline routing, cache efficiency, continuity (`docs/0001` success criteria).
- **Use cases.** Every live task was a single-file fix on a toy repo. `EXTERNAL` effects with idempotency keys, the "merchant" shape, have never met a real model, because no such tool ships.

---

## B. Ideas

### I-01: Tell a replay from a repeat — use the `OBSERVED` state the ledger already defines

- **Kind:** BOTH
- **Area:** safety / the real work / gate correctness
- **What it is.** The gate currently treats any identical non-replay-safe call in a conversation as "the same effect". In practice that means `execute_bash` running `python -m pytest`, `npm test`, `ruff`, `python app.py` (all `EXTERNAL`), `git commit -am …`, or `>>` appends. Such a call is aliased by intent hash to its earlier twin, with two results:
  - If the twin is COMMITTED, the agent gets the twin's **old observation** back.
  - If the twin failed, the new call is **BLOCKED**.

  P1 reproduces both:

  ```
  run 1: EXECUTE
  run 2 (after COMMITTED): SUBSTITUTE already recorded (matched to call_A by intent hash) b'{"output":"1 failed"}'
  run 2 (after failing run): BLOCK | the tool reported failure and this effect cannot be safely repeated ... (matched to call_C by intent hash)
  ```

  The proposal is to mark a record `OBSERVED` once the model has actually been handed its observation. Seam B already sees that event in `_close` (`agentctl/adapters/openhands/seam_b.py:191-210`). Then:
  1. `find_by_intent` aliasing ignores `OBSERVED` twins. A repeat the model issues *after seeing the result* is intentional, not a replay.
  2. A failed non-replay-safe tool whose observation was delivered stops being an end-of-run "BLOCKED — needs you" alarm. It keeps the error, and is still blocked if a crash re-drives it without an observation.
  3. The crash cases stay exactly as they are. A twin in `INTENT`, or `COMMITTED` without an observation, is precisely what `0023` §4 aliasing exists for.
- **Why it fits this harness.**
  - The aliasing is at `agentctl/kernel/gate.py:67-77`, and SUBSTITUTE for COMMITTED/OBSERVED is at `:99-102`.
  - `record_tool_error` blocks every non-replay-safe failure (`:282-315`).
  - Every interpreter falls to `class: EXTERNAL` (`agentctl/control/matrix/data/tools.yaml:37-38`), and `BashObservation.make` sets `is_error = exit_code != 0` (`agentctl/runtime/tools.py:97-100`).
  - The `OBSERVED` state and the `COMMITTED → OBSERVED` transition already exist (`agentctl/kernel/ledger/models.py:65,77`), and `store.observed()` has **no callers** (`agentctl/kernel/ledger/store.py:349-350`).
  - The runner's own docstring says the gate is about replay safety, not about intentional repeats (`agentctl/runtime/runner.py:15-22`).
  - `docs/0041` §1 records "2 blocked failed bash commands" among 6 `EXTERNAL` effects in a test-driven task, which is the shape P1 produces. That is a hypothesis to confirm, since the 0041 ledger is not in the tree.
- **What would actually need to be built.**
  - Seam B `_close` marks OBSERVED after commit, or records "error observed".
  - The state machine gains BLOCKED/FAILED-with-observation semantics, as a flag column rather than a new state if simpler.
  - `find_by_intent` gains a state filter.
  - The runner's end-of-run blocked list excludes observed failures.
  - Tests: P1 as a regression test, plus the nine-point chaos suite unchanged and green.
  - Size: ~60–120 lines plus tests, in `agentctl/kernel/gate.py`, `agentctl/kernel/ledger/store.py`, `agentctl/kernel/ledger/schema.sql`, `agentctl/adapters/openhands/seam_b.py` and `agentctl/runtime/runner.py`.
- **Experiment/test to run.**
  - Local, zero quota: run P1 as a test, then the full chaos suite and the three `experiments/000{1,2,3}` scripts. Zero duplicate effects must survive.
  - Live, ~30 requests: two tasks deliberately shaped as "the test fails first, then passes", for example seed a failing test and ask for a fix. Run each with and without the change.
  - Measure: false BLOCKs, stale SUBSTITUTEs (a model told `1 failed` after its fix), end-of-run "BLOCKED" count, task success.
- **Expected observable result.** Without the change, the identical re-run is blocked or substituted, and the run ends with "N effects need you" despite passing tests. With it, zero such events and the chaos suite still green.
  - **Falsified if** any chaos crash point produces a duplicate with the change. That would mean OBSERVED is not a sound signal of "the model saw it", for example because callbacks fire before persistence and a crash in between loses the observation while the ledger says OBSERVED.
  - **Also falsified (as a problem) if** live agents almost never re-issue byte-identical commands.
- **Reasoning summary.** Intent-hash aliasing was built for one situation: the same logical call re-minted by a different model *after a crash*. It currently fires for every identical call in the conversation's whole history, which captures the normal test loop. The ledger already has a state meaning "the harness handed this back", and it is unused. Using it separates replay from repeat without weakening the crash guarantee. The fix is small, local and testable at zero cost. It also removes a source of false human interventions that would contaminate every later experiment.
- **Risks.**
  - The exact ordering of OpenHands event persistence against callbacks decides soundness, so the chaos suite has to prove it.
  - A true duplicate is now possible if a model *intentionally* repeats a non-idempotent effect, such as a second `git commit` of the same message. That is arguably the agent's choice, not a replay, but it moves a line the project drew deliberately (`docs/0023` §4: "Deliberately conservative").
- **Depends on:** existing gate and Seam B. Informs I-03, I-04, I-20.

### I-02: One driver per conversation, enforced — renew the lease, refuse live takeover, fence fresh intents

- **Kind:** BOTH
- **Area:** recovery / safety / single-writer
- **What it is.** Three gaps compose into two live drivers of one conversation, both executing effects:
  1. The lease is never renewed (`agentctl/kernel/ledger/store.py:135-140` has no callers), so it lapses after 60 s.
  2. `agentctl run --resume` always steals the lease (`takeover=bool(resume)`, `agentctl/runtime/runner.py:212`), even when the original run is still alive.
  3. `write_intent` asserts the fence only when a record already exists (`agentctl/kernel/ledger/store.py:282-285`), so a superseded holder's **fresh** tool call passes.

  `docs/0038` §3 named premise 3 and fixed only its downstream symptom. P2 reproduces the gap:

  ```
  fences 1 2
  zombie guard on a FRESH id: EXECUTE None
  zombie commit state: COMMITTED
  ```

  Proposal:
  - (i) Renew the lease on every gate decision, which costs one UPDATE and piggybacks the existing connection.
  - (ii) `--resume` refuses when the lease is live and names the holder. A `--takeover` flag steals it explicitly, for the crashed-holder case `0016` §3 needs.
  - (iii) Fresh intents check the *lease table's* current fence for the conversation, not the previous record's.
- **Why it fits this harness.** "Zero duplicate side effects across crash and replay" is the first charter criterion (`docs/0001`). The whole fencing argument ("takeover is only safe because the zombie is rejected on its next write", `tests/test_ledger.py:125-141`) is tested only for an *existing* record.
- **What would actually need to be built.** ~40–70 lines in `agentctl/kernel/ledger/store.py` (`write_intent`, a `current_fence()` read), `agentctl/kernel/gate.py` (a renew hook), `agentctl/runtime/runner.py` and `agentctl/cli.py` (the `--takeover` flag), plus two chaos tests: a zombie with a fresh id, and two live `--resume` processes.
- **Experiment/test to run.** Local only, zero quota, using `experiments/0000-falsification/mock_provider.py`. Start run A. After more than 60 s (or with the TTL shrunk), start run B with `--resume A`. Script both mock models to issue `git commit` with *different* messages, so intent hashes differ. Count commits and ledger rows before and after the change. Also check that a real crashed holder is still recoverable with `--takeover`.
- **Expected observable result.** Before: both processes commit, and the ledger shows COMMITTED rows under two fences. After: B refuses without `--takeover`, and a superseded A is fenced on its next fresh intent (StaleFence, which the gate turns into BLOCK).
  - **Falsified if** the OpenHands conversation persistence itself prevents two processes resuming one conversation (for example a file lock). The hole would then be theoretical. Worth knowing either way.
- **Reasoning summary.** The single-writer assumption is the one the project says decides multi-agent "at any budget". Its enforcement is weaker than its statement: a resumed run in a second terminal is enough to break it. The fix is small and entirely in-kernel, and the test is free. It is the kind of hole `docs/0039` §3 says the suite will never find by itself, because every test starts from the state its author understood.
- **Risks.**
  - Lease renewal adds a write per decision, which is measurable in I-03.
  - Refusing the takeover changes a documented default (README `protect(takeover=resuming_after_a_crash)`). A crash that leaves a live-looking lease then needs a TTL wait or an explicit flag, which is the right trade-off but a UX cost.
- **Depends on:** nothing. Protects I-04, I-05, I-24.

### I-03: What does the gate cost? A guarded-versus-unguarded audit on real tasks

- **Kind:** EXPERIMENT
- **Area:** eval / safety / overhead
- **What it is.** Run the same graded tasks with the gate on and with it off, without crashes. The gate's benefit is zero in a no-crash run, so this arm isolates its cost. Measure:
  - wall-clock overhead per tool call: fsync at `synchronous=FULL` (`agentctl/kernel/ledger/store.py:1-7`), git probe `capture` spawning `git rev-parse` and `git status` (`agentctl/kernel/reconcile/git.py:53-75`);
  - false BLOCK/ESCALATE/SUBSTITUTE verdicts;
  - end-of-run human interventions requested;
  - task success.

  Tally effect classes and the top `EXTERNAL` commands as a side output. That closes `docs/0009` Q9 ("cheapest high-value measurement in the project") and decides whether speculative execution (`docs/0010` §6.4) stays unbuilt.
- **Why it fits this harness.** The owner's own example question. `0041` §1's 6 PURE_READ out of 14 (43%) is the only Q9 data point, so speculation looks weak but is unmeasured.
- **What would actually need to be built.**
  - An experiment-only `--unguarded` switch in `agentctl/runtime/runner.py` that skips `protect()`. It should be refused outside an env flag, so it never becomes a daily default.
  - Per-decision timing in `on_decision` (`agentctl/runtime/runner.py:198-204`).
  - A tally script over ledgers and events.
  - ~60 lines. Uses I-20's corpus.
- **Experiment/test to run.**
  - 5 corpus tasks × 2 arms × 1 rep, all on one source for both arms (for example `pool-gemini`) so model variance does not swamp the result. About 140 requests over 1–2 days.
  - Measure median/p90 gate latency per call against LLM latency (live p50 3.1 s, p90 15.2 s, in `hook_telemetry.json`), false verdicts adjudicated by hand, interventions, success.
- **Expected observable result.** Latency overhead in milliseconds, which is noise next to seconds of LLM time. Intervention and false-verdict cost is non-trivial *until* I-01 lands. After I-01, near zero.
  - **Falsified (the gate is a net cost) if**, after I-01, the guarded arm still shows more human interventions or lower success with no duplicates prevented. A companion crash arm (I-04) would then have to show a duplicate prevented for the gate to justify itself.
- **Reasoning summary.** The project has proved the gate *prevents* duplicates. It has never measured what the gate *costs* on ordinary, crash-free work, which is most work. The measurable costs are human attention and false information to the agent. The expected latency cost is small. Running it before and after I-01 turns I-01 from an argument into a number. The Q9 tally comes for free from the same ledgers.
- **Risks.**
  - With 5 tasks the success-rate difference will be noisy. The intervention and false-verdict counts are the robust signal.
  - An unguarded switch is a footgun and must stay experiment-only.
- **Depends on:** I-20 (corpus), I-01 (for the second pass).

### I-04: Does resume beat restarting? Crash injection at turn k, three arms

- **Kind:** BOTH (a small crash-injection hook plus the experiment)
- **Area:** recovery / continuity / eval
- **What it is.** Kill the runner process at the k-th effect of a graded task, then finish it three ways:
  - (A) `agentctl run '' --resume <cid>`, the ledger's value proposition;
  - (B) a fresh conversation, same task, on the **dirty** workspace, which is what a user without the harness does;
  - (C) a fresh conversation on a clean copy, the naive restart.

  Measure requests and tokens to completion, final acceptance result, duplicate effects (commit count, appended-line count), BLOCKs needing a human, and wall time.
- **Why it fits this harness.** Continuity is a charter criterion (`docs/0001`). The chaos suite proves *no duplicates* at nine protocol points, but only with one effect per run (README), and never compares against a restart. Resume re-sends the whole conversation, while a restart re-reads a few files. It is not obvious which is cheaper on a free pool whose binding constraint is requests per day (`docs/0040` §1).
- **What would actually need to be built.**
  - A crash-injection hook: an env var such as `AGENTCTL_KILL_AT_EFFECT=n`, checked in Seam C after `write_intent` or after the inner call, calling `os._exit`. Test-only, around 20 lines, modelled on `experiments/0004-nine-point/worker.py`.
  - A driver script.
  - Tasks must include a non-idempotent effect (a commit, or an append to a changelog) so duplicates are possible at all.
- **Experiment/test to run.** 4 tasks × kill points k ∈ {after the first commit's INTENT, mid-run} × 3 arms ≈ 24 runs × ~15–18 requests ≈ 400 requests. Split it: k = 1 on day one (~200), then decide whether the second k is worth it. Use one source for all arms.
- **Expected observable result.** Arm A: zero duplicates and fewer requests than C. Arm B: a duplicate commit in some fraction of runs, which is the thing the project exists to prevent, at a request cost similar to A.
  - **Falsified if** B matches A on duplicates, because agents inspect `git log` before committing again, and matches or beats it on requests. The resume machinery would then add no measurable value for this workload, and the claim would need narrowing to "effects the agent cannot inspect" (EXTERNAL; see I-25).
- **Reasoning summary.** "Crash it and re-run with `--resume`: work already done is not repeated" (README) has only ever been compared with doing nothing. The honest baseline is a human restarting the task, and a capable model may well notice its own prior commit. This experiment can come out against the project, which is exactly what makes it worth running. It also exercises `agentctl run --resume` itself for the first time, a tier-(b) path.
- **Risks.**
  - Quota: this is one of the more expensive experiments.
  - The small-sample result will be directional, not statistical.
  - Arm B's outcome depends heavily on the model. Use the strongest free source.
- **Depends on:** I-20, I-02 (so the resumed and killed processes cannot both drive), I-01 (so false BLOCKs do not pollute A).

### I-05: A supervisor that outlives the quota — wait or shift on exhaustion, survive proxy death

- **Kind:** BOTH
- **Area:** long-running agents / rate-limit-aware behaviour / reliability
- **What it is.** `agentctl run --until-done`, or `agentctl supervise <cid>`, wraps the run loop. When a run ends on a provider error, the supervisor classifies it:
  - rate limit or pool exhausted: `_explain_provider_error` already parses `X-RateLimit-Reset`, `X-RateLimit-Remaining` and `free-models-per-day` (`agentctl/runtime/runner.py:448-467`);
  - overload (`:488-492`);
  - connection refused, meaning the proxy died, which is currently unrecognised and raises a traceback (`:436-493`);
  - key rejected.

  It then chooses one of three things:
  - (a) wait until the earliest observed reset and `--resume` with an explicit takeover;
  - (b) shift to a different source group that I-13 says still has allowance, then resume;
  - (c) stop and notify.

  Every decision is printed and logged to the run index (I-17). It never shifts to `paid` (`agentctl/control/proxy.py:341-347`).
- **Why it fits this harness.**
  - The charter's first sentence is about surviving a rate limit without work stopping (`docs/0001`, `0032` intro).
  - Today a run that exhausts the pool exits with advice to "wait for the reset, use a different provider key, or run offline" (`agentctl/runtime/runner.py:463-467`), which leaves a human in the loop.
  - The pieces exist: persisted conversations with `delete_on_close=False` (`:224-229`), resume with takeover (`:212`), and source groups (`agentctl/cli.py:265-284`).
  - Proxy restarts lose cooldown state, which lives in the router's in-process cache (`agentctl/control/dash.py:212-218`), so a restarted proxy re-hits capped keys.
- **What would actually need to be built.**
  - `agentctl/runtime/supervise.py`, ~150 lines: an error classifier, a wait/shift/stop policy, and a resume loop with a maximum-attempts bound.
  - A proxy-liveness check reusing `_proxy_pool` (`agentctl/control/dash.py:81-111`).
  - Optionally, `agentctl proxy --exclude-capped`, which reads I-08's persisted 429 observations so a regenerated or restarted pool leaves out deployments known to be capped until their reset.
- **Experiment/test to run.**
  - (1) Exhaustion drill. Build a proxy config from a keys environment holding **one** OpenRouter key plus Gemini, then run corpus tasks back to back until the OpenRouter key 429s. Cost: that key's 50/day, plus ~20 Gemini requests. Measure whether the in-flight task completes unattended and how many requests are wasted on dead deployments.
  - (2) Proxy death. `taskkill` the proxy mid-run, restart it after 30 s, and measure whether the run survives and how many requests re-hit capped deployments after the restart.
  - Baseline: the current `agentctl run`, which exits.
- **Expected observable result.** The supervisor completes the task after a shift, or after a wait if the drill is scheduled near a reset. Plain `run` exits.
  - **Falsified (not worth building) if** shifting mid-task to a different model family makes the task fail more often than waiting. I-12 measures the related quality question.
  - **Also falsified if** real exhaustion almost never happens during a task in practice. I-13's counts over a week answer that.
- **Reasoning summary.** The most literal reading of the owner's "API shifting based on rate limits" is not a smarter router inside litellm, which is solved and which the charter says not to rebuild. It is what the *harness* does when the router has nothing left. That decision belongs in the control plane, needs the ledger to make resuming safe, and is the capability that makes an hours-long run on free tiers possible at all. It composes existing pieces rather than inventing new ones.
- **Risks.**
  - A shift mid-conversation changes the model family, and quality may drop (I-12).
  - Waiting for a Gemini daily reset can mean hours. The supervisor must be interruptible and must keep the lease renewed (I-02).
  - An auto-resuming loop could spin on a persistent non-transient error, so it needs a hard attempt bound.
- **Depends on:** I-02, I-08, I-13, I-17. Uses I-06 for unattended approvals.

### I-06: Approvals that do not stop the run

- **Kind:** FEATURE (with a usability check)
- **Area:** long-running agents / safety / dashboard interaction
- **What it is.** `--confirm-destructive` currently calls `input()` inside the gate (`agentctl/runtime/runner.py:329-335`). An unattended run therefore blocks forever, and a detached one reads EOF as refuse (`:331-332`). The policy's "leave the default pool" prompt has the same shape (`:425-433`). Proposal: a confirmation becomes a ledger record. The effect is recorded BLOCKED with `reason="awaiting operator approval"`, and the agent receives "this action needs human approval; it has been queued — continue with other work or finish". The operator approves or denies later through `agentctl resolve` or the dashboard (I-19). An approved effect becomes executable on the next resume, by the same resolve-retry route the ledger already supports (`agentctl/cli.py:173-195`, `agentctl/kernel/ledger/models.py:79-81`). An optional notification hook (`docs/0013` §4, §5 "webhook out of the control plane") fires on a queued approval.
- **Why it fits this harness.** `docs/0013` §3 Panel 3 describes exactly this ("buttons for it landed / it did not, run it / abandon the turn") as the human half without which fail-closed is "correct and unusable". The ledger already models BLOCKED and human resolution. The only thing missing is using it for authorization as well as ambiguity. The distinction `docs/0025` §4 draws (gate = twice, confirmation = at all) is preserved: the *reason* differs, the storage is shared.
- **What would actually need to be built.**
  - `_install_confirmation` gains a non-interactive mode, the default when stdin is not a TTY or under the supervisor.
  - A `pending_approval` marker (a reason prefix or a column).
  - An `agentctl approve <id>` alias for `resolve --retry` with an audit note.
  - ~80 lines in `agentctl/runtime/runner.py`, `agentctl/cli.py` and `agentctl/kernel/ledger/store.py`.
- **Experiment/test to run.**
  - Local with the mock provider: script a destructive command and check the run continues and ends with one queued approval. Approve it, resume, and check it executes exactly once. Deny it, resume, and check it never executes.
  - One live run with a task that naturally deletes a build directory, ~15 requests.
- **Expected observable result.** Unattended runs finish with queued approvals instead of hanging or silently refusing, and nothing destructive executes unapproved.
  - **Falsified if** models, told an action is queued, loop re-issuing it until max iterations. That would burn quota and needs a stronger message or a stop.
- **Reasoning summary.** A long-running agent cannot depend on a human being at the keyboard at the moment it hits `rm -rf build/`. The ledger is already the right place for "this is waiting for a person", and the dashboard is already supposed to be where the person answers. This turns an interactive prompt into durable state without weakening the authorization rule.
- **Risks.**
  - The model's reaction to "queued" is the uncertain part.
  - A queued approval re-executed after the world has moved on (the build dir already gone, a different file now at that path) needs its pre_state re-captured at execution time, which Seam C's `recapture` provides (`agentctl/kernel/gate.py:218-237`).
- **Depends on:** I-02 (resume safety). Feeds I-19.

### I-07: Cross-model resume drill — the case `0023` admits was never run live

- **Kind:** EXPERIMENT
- **Area:** model/provider switching / recovery
- **What it is.** Crash a run immediately after `git commit` executes and before its observation is recorded, using the same kill hook as I-04. Then resume on a **different source group**: Gemini, whose `tool_call_id` carries a 300+ character thought signature (`docs/0041` §2.3), to OpenRouter, and the reverse. Count commits, and record whether the resumed turn was SUBSTITUTEd via intent hash (`agentctl/kernel/gate.py:67-77`), probe-reconciled (`:141-186`), or BLOCKED.
- **Why it fits this harness.** `docs/0023` §5: "the shuffle sent both runs to `nex-free`, so this particular pass did not exercise the cross-model id case." The provider-switch guarantee is the project's central claim ("the model/provider endpoint can change"), and in its only live test it was not exercised. With turn affinity inert (tier (c)), cross-model switches happen on nearly every turn, so this is the normal path, not an edge case.
- **What would actually need to be built.** Nothing beyond I-04's kill hook and a two-source driver script.
- **Experiment/test to run.** 2 directions × 3 repetitions × ~12 requests ≈ 70 requests, split Gemini/OpenRouter. Assert exactly one commit per run.
- **Expected observable result.** One commit, resolved by intent hash when the re-minted call is byte-identical in arguments.
  - **Falsified if** the new model re-issues the commit with *different* arguments (for example a reworded message), so the intent hash misses. The gate would then treat it as fresh, the probe would never run, and the result is a duplicate commit. This seems plausible for a different model. If it happens, it defines the next design problem: aliasing by *effect kind plus world state* rather than by exact arguments.
- **Reasoning summary.** The intent hash assumes a different model re-issues the *identical* arguments, and that is an assumption about model behaviour, not about code. Only a live cross-model resume can test it. It is cheap, and its most likely failure mode would expose a real gap in the core guarantee. Of all the experiments here, it is the most direct test of the charter's guiding principle.
- **Risks.** A small sample can pass by luck, so if all three pass, record it as evidence and not proof, as `0023` did. It needs a reliable kill point between execute and record.
- **Depends on:** I-04's hook, I-02.

### I-08: Seam A records failures, per attempt; telemetry becomes append-only and ingests itself

- **Kind:** FEATURE (verified live)
- **Area:** observability / routing foundation
- **What it is.** `AgentctlHook` implements `async_pre_call_hook` and `async_log_success_event` only (`agentctl/adapters/litellm/hook.py:26-42`). Every 429, 413, 402, 404 and timeout that the router retried around is invisible. Proposal:
  - Add a failure callback recording deployment id, exception class, HTTP status, `retry-after` / `x-ratelimit-*` headers where present (`docs/0038` §5.3: "record Groq's `x-ratelimit-remaining-*` when a response carries them … Never poll"), prompt size and timestamp.
  - Replace `_flush`'s rewrite of the whole JSON file on every call (`agentctl/kernel/hook.py:199-209`, which is O(n²) and loses everything on a crash mid-write) with append-only JSONL.
  - Have `agentctl dash` and `cost` ingest new lines automatically, idempotent on `(trace_id, ts)` as they already are (`agentctl/control/cost/ledger.py:106-128`).
  - Stop writing telemetry into the tracked repo-root `hook_telemetry.json`, which is currently dirty in git with 2,843 changed lines: default to `~/.agentctl/telemetry/`.
- **Why it fits this harness.** The strongest evidence is in the tree:
  - `mistral/mistral-small-latest`, 6 deployments in `pool` and 6 in `pool-mistral` (`proxy/proxy_config.yaml`), produced **zero** successful records out of 250. In the same 24-token probe batch, every other model produced 17–36. `pool-mistral` agent turns were served 8/8 by ministral-3b.
  - Whether mistral-small is dead, rate-limited or rejecting tool schemas is **unknowable** from current data. That is `docs/0039`'s "confidently wrong" shape arriving as silence.
  - The runner's `AGENTCTL_TELEMETRY` (`agentctl/runtime/runner.py:133`) is read by no one in its process.
- **What would actually need to be built.** ~80 lines in `agentctl/adapters/litellm/hook.py` and `agentctl/kernel/hook.py` (a `record_failure`, JSONL flush); a `failure_record` table in `agentctl/control/cost/ledger.py`; auto-ingest in `agentctl/control/dash.py` and `agentctl/cli.py`; a launcher default path in `agentctl/control/proxy.py`'s `HOOK_MODULE`.
- **Experiment/test to run.** Live verification, ~20 requests: send 20 realistic-size requests (5–8K prompt tokens, taken from a cassette) through `pool`. Confirm the failure table shows the Groq 413s (predicted ~25% of first attempts, 12/48 deployments) and the mistral-small outcome.
- **Expected observable result.** A non-empty failure log naming mistral-small's error class and Groq's 413s, with per-attempt deployment ids.
  - **Falsified (as a necessary feature) if** litellm's router does not invoke the failure callback per *retried attempt*, only per final failure. Per-attempt data would then need `litellm`'s router-level callbacks instead, which the analysts should check.
- **Reasoning summary.** Every rate-limit-aware idea (I-05, I-11–I-15) needs to know what failed, where and when. Today the system only records what succeeded, so a dead 12.5% of the pool looks exactly like a healthy one. This is small, is out of band per the kernel/control rule, and cannot break a request, because Seam A must never block (`agentctl/adapters/litellm/hook.py:29-35`).
- **Risks.** Callback semantics differ between router retries and final failures, which needs a source read. Headers may not be exposed on the exception object for all providers.
- **Depends on:** none. Foundation for I-05, I-11–I-15, I-17–I-18.

### I-09: Conversation attribution that works through the proxy

- **Kind:** BOTH
- **Area:** observability / cost attribution
- **What it is.** The hook takes the conversation id from `meta["conversation_id"]` or `data["extra_headers"]["x-litellm-session-id"]` (`agentctl/kernel/hook.py:151-154`). In the proxy, an *incoming* HTTP header does not land in `extra_headers`, which is a client-side kwarg. Live result: **23/23** calls have `trace_id` starting with `unknown:`. So:
  - `agentctl cost --conversation <id>` and `by_conversation` (`agentctl/control/cost/ledger.py:159-166`) return nothing useful;
  - "cost per completed task", the charter's cost criterion, is not computable;
  - `research/phase-10-5` §2.12's "cost attribution is already free through the proxy" is falsified by the repo's own telemetry.

  Fix: read the session id from wherever litellm's proxy exposes request headers to a pre-call hook. The analysts must find the exact key (`proxy_server_request.headers`, `metadata.headers`, or a native `litellm_session_id`). Also stamp the parent run's conversation id onto subagent and recon calls (`research/phase-10-5` build step 8).
- **Why it fits this harness.** `docs/0001` problem 3 ("Nothing joins provider spend to a logical unit of agent work") is one of the four stated problems. `docs/0021` §3 lists attribution as working, but it was measured against mock upstreams.
- **What would actually need to be built.** ~20 lines in `agentctl/kernel/hook.py` (pure-dict logic stays testable), plus a test built from a *real* captured proxy `data` dict rather than a hand-built one. That is the lesson of `docs/0021` §4 ("where the metadata actually is"). Subagent `conversation_id` pass-through: ~10 lines in `agentctl/runtime/subagent.py`.
- **Experiment/test to run.** One live run, ~15 requests. Assert that the count of cost-ledger rows with that conversation id equals the client-side count of completions for the run. The recorder (`agentctl/adapters/litellm/recorder.py`) gives the client count for free with `--record`.
- **Expected observable result.** Equal counts.
  - **Falsified if** OpenHands 1.45.0 does not actually send `x-litellm-session-id` through `base_url` calls to a proxy. `docs/0015` §5 says it does, but that may be only for its own LiteLLM path. The fix would then have to add the header in `LLM(extra_headers=...)` from the runner.
- **Reasoning summary.** This is a live defect in a tier-(a) capability that no mock could show, which is exactly the class `docs/0041` warns about. It blocks the cost-per-task metric that the dashboard's Panel 4 and every routing comparison need. The fix is tiny; the value is in verifying it against the real proxy.
- **Risks.** Minimal. The only risk is fixing it by reading a header key that exists in one litellm version and not the next, so the test should be built from a captured real payload.
- **Depends on:** I-08 (same module).

### I-10: Known-free is not unpriced is not priced

- **Kind:** FEATURE
- **Area:** cost control
- **What it is.** The cost ledger has two states: `priced = 1 if cost else 0` (`agentctl/control/cost/ledger.py:113`). Live telemetry shows litellm assigns **list prices to free-tier calls**:

  | model | calls | priced | sum |
  |---|---|---|---|
  | gemini-3.6-flash | 37 | 37 | $0.01329 |
  | ministral-3b-latest | 45 | 45 | $0.00333 |
  | groq gpt-oss-20b/120b | 72 | 72 | $0.00114 |
  | OpenRouter `:free` (3 models) | 96 | 0 | unknown |

  So the ledger reports free Gemini/Mistral/Groq work as real, "trustworthy" spend (`Totals.trustworthy`, `:66-68`), and the `daily_usd` cap (`agentctl/runtime/runner.py:405-412`) counts phantom dollars. At the same time the `:free` calls read as "unknown". The generated config already knows which deployments are free (`model_info.free`, `agentctl/control/proxy.py:230`). Seam A should record it, and the ledger should gain a third state, `known_free`, excluded from both the spend and the coverage denominator.
- **Why it fits this harness.** `docs/0021` §5 and `0030` §3 built the whole "coverage" concept around under-counting. This is the opposite error, in the same column. "Never render an unpriced total as though it were a real zero" (`agentctl/control/cost/ledger.py:74-83`) has a mirror image the code does not handle: never render a free call as a paid one.
- **What would actually need to be built.** ~40 lines: `agentctl/kernel/hook.py::record` reads `litellm_params.model_info.free`; a schema column in `agentctl/control/cost/ledger.py`; `describe_cost` and the `dash`/`cost` rendering.
- **Experiment/test to run.** Zero quota: re-ingest the existing `hook_telemetry.json` and check that spend drops to $0 known plus "unknown" for none. Then piggyback one live run and cross-check against the providers' own usage consoles (free-tier billing pages show $0).
- **Expected observable result.** Spend of $0.00 for free deployments, with coverage computed only over deployments that can bill.
  - **Falsified if** any "free" deployment actually bills, for example a Mistral plan change or Gemini billing enabled on the project. That would be a valuable finding, and it argues for showing "free per config, verify in console" rather than asserting $0.
- **Reasoning summary.** A budget built on numbers that are wrong in both directions is decoration, which is the project's own verdict on `max_budget_per_run`. The proxy config holds the ground truth about which deployments are free, and nothing passes it to the ledger. It is cheap, local and verifiable against existing data.
- **Risks.** "Free" is a configuration claim, and tiers change (`docs/0032` §2). The display must say *"free per the proxy config"*, not *"$0"*.
- **Depends on:** I-08 (same record path).

### I-11: A pool fit for agent turns — verify every model, keep Groq out of `pool`, decide on ministral-3b

- **Kind:** BOTH
- **Area:** routing / reliability
- **What it is.** Three pool-hygiene changes:
  - (i) `check_inference` verifies each provider's **first model only** (`agentctl/control/probe.py:281`). Verify each *distinct model id* per provider instead: 8 calls today rather than 5. Drop dead model ids from the generated config the same way dead providers are dropped. `docs/0034` §4: "A catalogue says what exists. Only a call says what *you* can use."
  - (ii) Remove Groq from `pool`. It stays in `pool-groq` for tiny-prompt scouts at `max_output_tokens=512` (`research/phase-10-5` build step 5). `doctor` already warns that turn 2 will 413 (`agentctl/runtime/doctor.py:79-125`), yet `agentctl proxy` puts 12 Groq deployments, 25%, in the default agent pool (`agentctl/control/proxy.py:222-231`).
  - (iii) Decide deliberately whether ministral-3b belongs in the default *agent* pool. Six of the 48 deployments hand an agent turn to a 3B model, and in live telemetry ministral served every `pool-mistral` turn.

  Alternatively, express (ii) with litellm 1.100.0's own `enforce_model_rate_limits` pre-call check and per-deployment `tpm` (`.venv/Lib/site-packages/litellm/router_utils/pre_call_checks/model_rate_limit_check.py:1-10`). That is CONFIGURE rather than BUILD, if it rejects a request whose prompt plus `max_tokens` exceeds Groq's TPM. The analysts should verify the semantics.
- **Why it fits this harness.** The owner's charter says generic routing is litellm's job (`docs/0001` "What it is not"). *What goes into the pool* is this project's job, because it generates the config.
- **What would actually need to be built.** ~50 lines in `agentctl/control/probe.py` (a per-model loop, stop-at-first-success per model), and `agentctl/control/proxy.py::build` (the pool membership rule, plus an explicit comment and `agentctl models` line saying why Groq is not in `pool`).
- **Experiment/test to run.**
  - (1) Per-model verification: 8 requests.
  - (2) A pool-hygiene A/B with I-08 in place: 40 realistic-size requests (prompts sampled from a cassette), 20 through the current pool and 20 through the cleaned pool. Measure attempts per successful request, p50/p90 latency, and failures by class. About 40–60 requests.
- **Expected observable result.** Attempts per success fall from roughly 1.3–1.4 (Groq 413s plus mistral-small failures) toward about 1.0, and p90 latency drops.
  - **Falsified if** the retry cost of dead deployments is negligible, because the router cools them down after the first failure (`allowed_fails: 1`, `cooldown_time: 300`, `agentctl/control/proxy.py:306-307`). With a warm router the dead ones might barely be picked. The cleanup would then be cosmetic, apart from the correctness of `models`/`dash` counts.
- **Reasoning summary.** The default pool is supposed to be "the widest safe thing you can ask for" (`agentctl/cli.py:688-699`). A quarter of it cannot carry a second agent turn, another eighth appears never to have answered, and an eighth is a 3B model. That is `docs/0039` #5 ("FAILOVER READY — 31 accounts" while seven could not serve) arriving again inside the pool.
- **Risks.**
  - Removing ministral-3b shrinks Mistral's contribution, the leg `docs/0040` §6 relies on for scouts, so keep it in `pool-mistral`.
  - Per-model verification costs a few more requests per `agentctl proxy` run.
- **Depends on:** I-08 for measurement.

### I-12: Sticky or shuffled? Session affinity against per-request shuffle against one strong source — and retire or fix `TurnAffinity`

- **Kind:** BOTH (mostly configure, plus an experiment)
- **Area:** routing / model switching / cache economics
- **What it is.** In the live pooled run, one conversation's consecutive turns went `openrouter-a5-m0 → a1-m1 → a6-m2 → a3-m0 → a3-m2 → a4-m1 → a2-m0 → a1-m0 → a1-m1 → a5-m1 → a6-m0`: a different account on almost every turn and three different *models* (`hook_telemetry.json`). The aggregate cache-hit ratio was **32.7%**, against **94.93%** for a single-model run in `docs/0036` §1. The project's own mechanism for keeping a turn on one deployment, `TurnAffinity`, is inert (tier (c)). Installed litellm 1.100.0 appears to ship session stickiness: `session_affinity` / `deployment_affinity` keyed on a session id (`.venv/Lib/site-packages/litellm/router_utils/pre_call_checks/deployment_affinity_check.py:36-41, 248-270`), which is exactly `docs/0009` Q4.
  - **Experiment:** three arms on the same corpus.
    - (A) the current shuffle over `pool` (after I-11);
    - (B) the same pool with session affinity, so one deployment per conversation until it fails;
    - (C) a single strong source (for example `pool-gemini` or the OpenRouter nemotron models only).
  - **Feature:** configure (B) if it wins. Delete `TurnAffinity` or re-point it, in the spirit of Phase 10.4's deletion of `tiering`. Close Q4.
- **Why it fits this harness.** Cache economics is charter problem 2 and success criterion 4 (`docs/0001`). Model heterogeneity per turn is an untested quality risk, and it is also the reason intent-hash aliasing (`docs/0023` §4) and `modify_params` (`agentctl/control/proxy.py:284-295`) are needed at all.
- **What would actually need to be built.** Reading the installed litellm source to confirm how `session_affinity` finds the session id, which should be free. Two or three lines of `router_settings` in `agentctl/control/proxy.py::build`. Removing or rewriting `agentctl/kernel/hook.py:86-165` and its tests.
- **Experiment/test to run.** 5 tasks × 3 arms ≈ 15 runs × ~14 requests ≈ 210 requests over two days. Measure success (acceptance), requests and tokens per task, cache-hit ratio, p50 latency, and number of distinct models per conversation.
- **Expected observable result.** (B) and (C) show much higher cache-hit ratios and fewer distinct models per conversation, and equal or better success than (A). (B) keeps failover, while (C) gives it up (`agentctl models` "gives up N of 48").
  - **Falsified (the charter's cache premise, for this workload) if** cache-hit ratio rises but neither latency nor success improves. On a free pool, dollars are zero, so cache would then buy nothing measurable here. That is worth recording as a DECISION that shrinks scope.
  - **Also falsified if** (A) succeeds as often as (C), which would mean per-turn model hopping is harmless.
- **Reasoning summary.** The pool currently gives each agent turn to a random model, and nobody has measured whether that matters. The fix, if one is needed, is configuration in a library the project already depends on, which is the method's preferred verdict (CONFIGURE over BUILD). The experiment can shrink scope, by retiring the cache-economics argument for free tiers, or confirm a cheap win. It also removes an inert mechanism whose docstring claims protection it does not provide.
- **Risks.**
  - Session affinity may concentrate a long conversation on one account and exhaust it faster. That is fine on OpenRouter, where the cap is per account and failover happens on the 429, but it interacts with I-14's weights.
  - Arm C's failover loss must be visible in the results, not hidden.
- **Depends on:** I-08, I-09, I-11, I-20.

### I-13: A quota ledger and pre-run admission — count what this machine spent, per quota, and say what a run will need

- **Kind:** BOTH
- **Area:** rate-limit-aware behaviour / dashboard / cost control
- **What it is.** `docs/0013` §2's "local consumption model per endpoint", built within the no-numbers-in-source rule (`agentctl/control/providers.py:13-22`):
  - Count successful and failed requests per **quota** (not per key: Gemini's six keys are one quota, `providers.py:119-121`) per provider day, from I-08 telemetry.
  - Limits come from a *user* file (`~/.agentctl/limits.yaml`, each entry carrying `measured_on:` and `source:`). OpenRouter is calibrated by its free `/api/v1/key` counter (`agentctl/control/probe.py:138-184`).
  - `dash` shows dated evidence rows under the `UNKNOWN` capacity banner, without changing its verdict:

    ```
    gemini (1 quota)   ~212 of 250 used today (local count, lower bound; limit from limits.yaml measured 2026-09-21)
    last 429 at 14:02
    ```

  - Before a run, `agentctl run`/`doctor` estimates the requests the task will need (the median from past runs in the run index, I-17) and warns: "this run needs ~14 requests; OpenRouter has ~9 left on the accounts this machine has used today — consider `--source gemini`".
- **Why it fits this harness.**
  - `docs/0013` §3 Panel 1 ("predicted remaining allowance, next reset") was deliberately left `UNKNOWN` because cooldown state has no honest source (`docs/0038` §5.2). A *dated local count* is honest in a way a live-capacity light is not.
  - `docs/0040` shows the binding unit is requests per day per quota.
  - The recon allocator already uses quota counts as its structural fact (`agentctl/runtime/orchestrate.py:9-26`).
- **What would actually need to be built.** `agentctl/control/quota.py`, ~150 lines: a loader for the user limits file, per-quota counters over the cost ledger, reset clocks (UTC for OpenRouter, Pacific midnight for Gemini, which the analysts should verify), and an estimator. A `dash` panel. A `doctor`/`run` pre-flight line.
- **Experiment/test to run.** Zero added quota: piggyback on a week of normal use and on I-20 runs. At each OpenRouter refresh, compare the local count with `/api/v1/key`'s `used`, and log prediction error for "will this run hit the cap?" against what happened.
- **Expected observable result.** The local count tracks OpenRouter's `used` within a few requests when this machine is the only client, and the pre-run warning fires before most cap hits.
  - **Falsified if** the local count drifts badly. That would happen if the owner uses the same keys from other tools, or if `/health` sweeps like the 228 probe-shaped records in the tree consume quota unseen. The panel must then say "lower bound, other clients invisible" loudly or be dropped.
- **Reasoning summary.** Honest capacity is not knowable live, but *consumption* is knowable locally. The one provider that exposes ground truth (OpenRouter) can calibrate the model. This gives the owner the Panel 1 answer he actually needs ("will I run out mid-task?") without violating either the "derived, never asserted" rule or the "no rate limits in source" rule. It is also the input I-05 needs to choose between wait and shift.
- **Risks.**
  - A user-maintained limits file goes stale, which is exactly the rot `providers.py` refuses. Mitigation: show `measured_on` and fade values older than N days.
  - Reset clocks per provider are themselves facts that change.
- **Depends on:** I-08, I-09, I-17.

### I-14: A scarcity-weighted pool — apply `docs/0040`'s allocation rule to the router

- **Kind:** BOTH
- **Area:** routing / rate limits
- **What it is.** `docs/0040` §6.1's durable finding is "allocate work inversely to quota scarcity, not evenly", and it is implemented only for recon file splits (`agentctl/runtime/orchestrate.py:78-135`). The default pool does the opposite:
  - Uniform shuffle gives Gemini, one 250-RPD quota, 6/48 = 12.5% of requests.
  - OpenRouter, six 50-RPD quotas, gets 37.5%.
  - Mistral, with no known daily cap, gets 25%.

  Litellm's shuffle honours per-deployment `weight`, `rpm` or `tpm` (`.venv/Lib/site-packages/litellm/router_strategy/simple_shuffle.py:31-52`). `agentctl proxy` could emit `weight:` per deployment in proportion to that quota's daily allowance divided by the deployments sharing it, reading limits from I-13's user file (never from source). Without limits it would fall back to the structural quota count, as the recon allocator does.
- **Why it fits this harness.** The same rule, the same reason, a different consumer. It changes one generator (`agentctl/control/proxy.py::build`). No routing code is written; the method's CONFIGURE verdict applies.
- **What would actually need to be built.** ~40 lines in `agentctl/control/proxy.py` (weight computation, and a comment explaining it in the generated YAML), plus an `agentctl models` column.
- **Experiment/test to run.** Offline first with I-15's simulator (zero quota). Then live inside I-27's day-long comparison. The metric is total successful requests before the first request that exhausts every retry.
- **Expected observable result.** In simulation, weighted routing extends time-to-first-hard-failure and total served requests per day, with all quotas exhausting close together rather than OpenRouter first.
  - **Falsified if** the router's cooldowns already achieve the same effect (dead deployments are skipped after one failure, so the order of exhaustion does not matter to total throughput). The weights would then change nothing but latency.
- **Reasoning summary.** A uniform shuffle drains the scarcest per-account quotas first and then spends retries rediscovering that they are dead. The project already found and wrote down the right rule, and litellm already takes weights. The question the experiment answers is whether weights beat cooldowns, which is not obvious and is cheap to test in simulation.
- **Risks.** Weights interact with session affinity (I-12): a sticky session ignores weights after the first pick. Quota numbers from the user file may be wrong.
- **Depends on:** I-13, I-15. Validated in I-27.

### I-15: A pool simulator — evaluate routing changes at zero quota

- **Kind:** BOTH (a tool plus a backtest)
- **Area:** eval / routing
- **What it is.** `agentctl simulate` is a small discrete-event model. It replays a request trace (sizes and timings from the cost and failure ledgers, or from cassettes) against a model of the pool:
  - quotas per account: OR 50/day each; Gemini 250/day for one project; Groq TPM 8,000 with prompt+max_tokens metering (flagged as inferred, `docs/0039` §5); Mistral RPM/TPM from `docs/0040` §6.2;
  - the router's behaviour: shuffle, weights, `allowed_fails`, `cooldown_time`, `num_retries`, from the generated config.

  It outputs predicted tasks per day, the time of the first unrecoverable failure, and per-quota exhaustion times, for any proposed config.
- **Why it fits this harness.** `docs/0038` §4.1 and `0040` §1/§6 did this arithmetic by hand. It was re-derived three times and moved by an order of magnitude twice (`0040` §5). A simulator makes that arithmetic reproducible and testable, and lets routing ideas (I-11, I-12, I-14) be falsified before they spend a real day's quota. The method is "falsify before committing".
- **What would actually need to be built.** `agentctl/control/simulate.py`, ~200 lines. Router semantics are simplified, and the simplifications are stated in the output. Calibration inputs come from I-08 telemetry.
- **Experiment/test to run.** A backtest. Take one real day's telemetry (after I-08), simulate that day's config, and compare predicted against observed exhaustion times and failure counts. Then use it for I-14.
- **Expected observable result.** Predictions within, say, 20% of observed exhaustion times on a backtest day.
  - **Falsified if** it cannot reproduce a day it was calibrated on. Router semantics (cooldown, retry order) would then matter more than a simple model captures, and routing experiments must be run live.
- **Reasoning summary.** Quota is the scarce resource, and the owner's routing questions are about quota. Every live routing A/B costs a day. A simulator turns most of them into free runs and reserves live quota for confirming the winner. It encodes the arithmetic the docs keep redoing by hand, and makes the inputs explicit, including which ones are inferred.
- **Risks.** A simulator can become its own confidently wrong answer, which is the `0039` pattern. It must print which inputs are measured, which are inferred, and the backtest error.
- **Depends on:** I-08. Feeds I-14, I-27.

### I-16: A policy about the pool that exists, in a unit that binds

- **Kind:** FEATURE
- **Area:** cost control / policy
- **What it is.** Three defects in one area:
  - (1) **P3:** the shipped `agentctl/control/policy/data/policy.yaml` no longer compiles with the shipped compiler, because its `tiering:` block (line 38) is refused (`agentctl/control/policy/compile.py:220-241`). The checked-in `policy.compiled.json`, which `dash` and `Policy.load()` read, is stale from 2026-09-13 and still contains `tiering`.
  - (2) Policy pool members (`openrouter/free`, `google-ai-studio/flash`, `cerebras/llama`, `mistral/free`) match no model string `agentctl run` ever uses. `openai/pool` and `openai/pool-<source>` are not in `free_tier`, so every `--policy` run through the proxy triggers the "not in the default pool — spend on it?" prompt, which reads EOF as refuse (`agentctl/runtime/runner.py:418-433`).
  - (3) USD caps do not bind on a free pool. They read 0.0 for unpriced calls and phantom list prices for others (I-10).

  Proposal:
  - Make policy pools refer to *proxy model groups* (`pool`, `pool-<source>`, `paid`), validated against the generated config at compile time, the way the compiler refuses an undefined pool.
  - Add `budget.requests_per_task` and optionally `requests_per_day`, enforced mid-run by counting completions client-side with a litellm callback in the runner process (the recorder's attachment pattern, `agentctl/adapters/litellm/recorder.py:158-166`) and stopping the conversation cleanly at the cap.
  - Fix the shipped source so it compiles, and add a test that compiles the shipped file.
- **Why it fits this harness.** `docs/0030`'s title is "A policy that fails open is worse than no policy". Today the default policy fails to compile at all, and when compiled from an older artifact it prompts on every legitimate free run. `subagent.py:36-41` already concluded "iteration count is the bound that actually binds". The requests cap generalises that to the main agent in the unit the pool is rationed in.
- **What would actually need to be built.** ~120 lines across `agentctl/control/policy/compile.py`, `agentctl/kernel/policy.py` (a new limit kind; still pure lookup), `agentctl/runtime/runner.py` (a counting callback plus stop) and `agentctl/control/policy/data/policy.yaml`, plus a test compiling the shipped file.
- **Experiment/test to run.** Local with the mock provider: a task that would take 20 requests stops at a cap of 10 with a clear message, and resume continues under a fresh allowance. One live run confirms the stop happens at the cap against a real provider, ~12 requests.
- **Expected observable result.** The shipped policy compiles, `--policy` runs through the proxy without spurious prompts, and a requests cap stops a runaway run at N.
  - **Falsified (as valuable) if** runs never approach any sensible request cap. I-13's weekly distribution answers that.
- **Reasoning summary.** The policy layer was built carefully and then quietly disconnected from the pool it is meant to govern, and its only budget unit is the one that cannot bind here. Reconnecting it and giving it the unit that is actually rationed turns M7 from a demonstration into a daily control. The shipped-file compile test closes a `docs/0039`-shaped defect: a safety artifact that looks valid and is not.
- **Risks.** A mid-run stop needs a clean way to end an OpenHands conversation between turns (a pause or interrupt API), which the analysts should verify exists in SDK 1.45.0.
- **Depends on:** I-10, I-13 for day caps.

### I-17: A run index, so the dashboard finds every run's data

- **Kind:** FEATURE
- **Area:** dashboard
- **What it is.** Every `agentctl run`, `subagent`, `recon` and supervisor attempt appends one row to `~/.agentctl/runs.db`: conversation id, parent id, workspace, ledger path, telemetry path, model or source, start and end, exit reason (completed / max-iterations / provider-exhausted / blocked / killed), acceptance result (I-20) and request count. `dash`, `status`, `blocked` and `cost` iterate the index rather than defaulting to `./ledger.db` (`agentctl/cli.py:43`), which is never where runs write (`agentctl/runtime/runner.py:130`), and `./cost.db` (`agentctl/control/dash.py:391`), which is empty until a manual `ingest`.
- **Why it fits this harness.** `docs/0013` §3 Panel 3 ("What happened while I was away? Session list with status, cost, duration, and blocked effects awaiting your decision") and §4 (`cost today`: "spent, remaining, tasks completed"). Today none of these can be computed because nothing links a run to its data.
- **What would actually need to be built.** `agentctl/control/runs.py`, ~120 lines (SQLite, control-plane side, may fail without affecting runs). Writes from `agentctl/runtime/runner.py` in a `finally`. `dash` panels: sessions, blocked-across-all-runs, today's tasks and spend.
- **Experiment/test to run.** Local: runs with the mock provider across two workspaces, and `dash` shows both, with their blocked effects. Live: piggybacks on any run.
- **Expected observable result.** `agentctl dash` with no flags shows the last N runs, their outcome, requests and blocked effects.
  - **Falsified (as a design) if** index writes can fail in ways that lose runs, for example a crash before `finally`. So write a "started" row first and an "ended" row later, and let a missing end row mean "died".
- **Reasoning summary.** The dashboard has good panels pointed at the wrong files. A run index is the smallest structure that connects them, and it is where the "tasks completed" and "exit reason" facts will live once they exist. It is control-plane, out of band, and a precondition for Panels 2–4.
- **Risks.** Low. There is a privacy note: the index stores workspace paths and task text, so keep it local and never in a repo, following the `keys.env` care in `docs/0033` §5.
- **Depends on:** none. I-20 adds outcomes.

### I-18: A live turn stream and `agentctl why` — Panel 2

- **Kind:** FEATURE
- **Area:** dashboard / observability
- **What it is.** `agentctl watch <cid>` (terminal) and a `dash --serve` view (I-19) tail three sources:
  - the OpenHands persisted events (`<ws>/.agentctl/conversations/<cid>/events`, `agentctl/runtime/runner.py:226`);
  - the effect ledger;
  - I-08's telemetry JSONL.

  Per turn it renders the deployment and model that served it, how many attempts failed and why, prompt and cached tokens, latency, and each tool call with its effect class as a chip and the gate verdict. `agentctl why <turn>` (`docs/0013` §4) prints the routing inputs for one turn: which deployments were tried, the failure classes, and whether affinity applied.
- **Why it fits this harness.** `docs/0013` §3 Panel 2 ("What is my agent doing, and what has it cost?"); §4 ("a routing system you cannot interrogate is one you cannot improve. Build it early"). It is read-only and never on the request path, which respects the control-plane-may-fail rule.
- **What would actually need to be built.** ~200 lines in `agentctl/control/watch.py`. The join key between events and telemetry is the conversation id (I-09) plus timestamps or turn signature.
- **Experiment/test to run.** Use it during I-12 and I-20 runs. The acceptance test is whether it would have shown, unaided, the three `0041` defects: the 402 dead deployment, the retry that did not happen, and the 300-character id.
- **Expected observable result.** A human can see mid-run that the pool is hopping models or re-hitting a dead deployment.
  - **Falsified (as worth building) if** nobody opens it. An honest outcome for a personal tool, measurable by whether it was used during the experiment weeks.
- **Reasoning summary.** Every defect in `docs/0039` and `0041` was found by a human looking at the right number at the right time. `0039` §3 #4 was found only "because the count was printed where a human would see it". A live stream is the cheapest way to put more numbers in view. It depends on I-08 and I-09 because right now there is nothing true to stream.
- **Risks.** OpenHands' persisted event format is an SDK internal and can change across versions (`docs/0009` R1), so pin it and test against a recorded directory.
- **Depends on:** I-08, I-09, I-17.

### I-19: Resolve and approve from the dashboard, with the evidence in front of you — Panel 3

- **Kind:** FEATURE (plus a small usability check)
- **Area:** dashboard / human half of fail-closed
- **What it is.** `agentctl dash --serve` is a stdlib `http.server` bound to 127.0.0.1, with a per-launch token in the URL. It is read-only except for three actions:
  - **landed**, **retry**: the same code path as `cmd_resolve`, including fence adoption (`agentctl/cli.py:173-195`);
  - **approve** / **deny**: for I-06's queued approvals.

  Each blocked effect shows what the agent intended (the full command, not truncated to 200 characters as in `agentctl/runtime/runner.py:328`), the probe's fingerprint and verdict, the recorded observation if any, the two conversation turns around the action, and the short-id prefix (`agentctl/kernel/ledger/store.py:43-62`). The static `--html` output stays for sharing.
- **Why it fits this harness.** `docs/0013` §3: "Read-only except for the blocked-effect resolution … without it the fail-closed design is unusable in practice." `docs/0041` §2.3 already found the CLI resolve path unusable against one provider. Resolution is a *decision*, and it needs evidence the CLI scatters across `show`, `blocked` and the events directory.
- **What would actually need to be built.** ~250 lines in `agentctl/control/dash_serve.py`. No new dependencies, following the dashboard's "no CDN, no fonts" rule (`docs/0032` §5).
- **Experiment/test to run.** A small usability check: seed 10 BLOCKED effects with known ground truth (some landed, some not) in a scratch repo. Resolve them once via CLI and once via the page, preferably by someone other than the author. Measure decision time and wrong decisions.
- **Expected observable result.** Fewer wrong "landed" decisions with evidence on screen.
  - **Falsified if** CLI and page produce the same error rate. The evidence, not the medium, would then be what matters, and a richer `agentctl show` is enough.
- **Reasoning summary.** A human resolving a blocked effect is performing the probe's job by hand. A wrong `--landed` records an effect that never happened, which is the exact outcome the system exists to prevent. Putting the evidence next to the decision is the whole feature. It is also the one place the dashboard legitimately *drives* the harness, as the owner asked, and it stays out of the request path.
- **Risks.**
  - A local web server is a new attack surface. Bind to loopback, require the token, send no CORS headers, and use POST only.
  - Scope creep toward a web app (`docs/0009` R3) is a real risk. Keep it to one page.
- **Depends on:** I-06, I-17.

### I-20: Graded runs — `--accept` on `run`, and `agentctl bench` over a fixed corpus

- **Kind:** FEATURE (the substrate for most experiments)
- **Area:** eval / the real work
- **What it is.**
  - (1) `agentctl run --accept "<command>"`. After the agent stops, the *harness* runs the acceptance command in the workspace, outside the agent's tool loop, and records PASS or FAIL, with output, in the run index. Optionally it feeds the failure back once as a new user message (`--accept-retries 1`).
  - (2) `agentctl bench <corpus.yaml> --arm <name>=<flags> …`. For each task it:
    - copies a seed repo at a pinned commit into a fresh directory;
    - runs `agentctl run` with the arm's flags (source, affinity, gate mode, kill-at-k), with `--record` always on;
    - grades with `--accept`;
    - writes one row per (task, arm, rep) to a results table: success, requests, tokens, cached tokens, wall time, verdict counts, blocked, duplicates (counted by a per-task "duplicate detector" command such as `git log --oneline | wc -l`).
  - The seed corpus is the tasks that already exist and were graded: `0041` divide-by-zero, `0036` cart discount, `0035` classifier dogfood (`experiments/0010-dogfood/run_dogfood.py`, which already has `--check-only`), the `myproject/range_parser.py` stub, plus real open items from this repo such as `0039` §5's `service_id` bug.
  - Add 4–6 tasks with *multi-file* edits, a commit, and a changelog append, because every live task so far touched one file.
- **Why it fits this harness.** Charter criterion 3, "Lower cost per completed task than baseline routing" (`docs/0001`), cannot be measured without a definition of *completed*. None exists in code (runner output, `agentctl/runtime/runner.py:274-287`), and the dashboard's "tasks completed" (`docs/0013` §4) has no source. Every experiment in this file needs this.
- **What would actually need to be built.** `agentctl/runtime/bench.py` plus a CLI subcommand, ~250 lines. A corpus directory, `bench/`, with seed repos as git bundles. Acceptance support in `agentctl/runtime/runner.py`, ~40 lines.
- **Experiment/test to run.** A baseline pass: 6 tasks × 1 arm (`pool`) ≈ 84 requests. That establishes per-task request counts (does 14/task from `docs/0038` §4.1 still hold on multi-file tasks?) and a success-rate floor.
- **Expected observable result.** A results table that turns I-03, I-04, I-12, I-23 and I-27 into repeatable commands.
  - **Falsified (as a design) if** task outcomes are so noisy across repetitions at temperature 0 on free models that single runs are uninterpretable. Measure that first, with 3 reps of one task. The design would then need reps, and quota planning changes.
- **Reasoning summary.** The project's experiments so far have been bespoke scripts, one per question, which is why none compare arms. A small bench with fixed tasks, fixed seeds and always-on recording makes every later comparison cheap to specify and re-grade. Recording means a result can be re-examined, and partly re-run via replay, at no quota. The acceptance check is also a daily-driver feature in its own right.
- **Risks.**
  - A corpus of toy tasks measures toy behaviour, so it needs a few real, multi-file ones.
  - Grading commands are themselves effects. Run them outside the agent and outside the ledger, and say so.
- **Depends on:** I-17 (results storage can start as a CSV). I-01 should land before its numbers are trusted.

### I-21: The cassette corpus as a zero-cost regression suite over real model behaviour

- **Kind:** BOTH
- **Area:** eval / CI
- **What it is.** Every I-20 run records a cassette (`agentctl/control/replay/cassette.py`). Store each with its seed commit, and have CI replay all of them (`agentctl run '' --replay`, `agentctl/runtime/runner.py:140-152`) against the current harness on Linux and Windows. A harness change that alters what the model would see produces a **miss at a named turn** (`docs/0029`: "a miss is the product"). That covers a gate verdict change (I-01), a tool output format, the system prompt, or a classifier rule. Today CI replays exactly one 3-turn cassette (`experiments/0008-m6-replay/session.jsonl`).
- **Why it fits this harness.** This is the only way to test harness changes against *real* model trajectories without spending quota. It directly answers `docs/0039`'s finding that the suite "pins behaviour that someone has already understood". Real trajectories contain behaviour nobody wrote down.
- **What would actually need to be built.** A `bench/cassettes/` layout. A CI job looping over cassettes, ~40 lines. A tool to *accept* an intended divergence by re-recording or pinning, so the suite does not become the "cries wolf" check `docs/0034` §10 warns about.
- **Experiment/test to run.** Record 10 cassettes during I-20's baseline. Replay them all on Windows and on Linux CI unchanged, which tests cross-OS determinism. Then apply I-01's change and confirm the divergence appears exactly at the re-run turn and nowhere else.
- **Expected observable result.** 10/10 replay identically cross-OS before any change, and I-01 produces misses only at identical-re-run turns.
  - **Falsified if** cassettes miss on Linux for environment reasons. `docs/0039` §7 #12 found the fixed prefix differs by 2 tokens between Windows and Linux and "the cause is still not identified". The suite then needs per-OS recordings, or a fix to that nondeterminism, before it is worth anything.
- **Reasoning summary.** Replay already exists and is live-verified, so a corpus of real sessions is almost free once a bench records them. It converts every live run into a permanent free regression test of harness behaviour. Its first run also tests an open anomaly, the cross-OS prefix difference, that could quietly break it.
- **Risks.** Cassettes contain workspace contents (`cassette.py:30-35`), so the corpus must hold only synthetic or public code. Large cassettes bloat the repo, so store them compressed or out of tree.
- **Depends on:** I-20.

### I-22: Are the scouts right? Citation-check accuracy, and recon versus a single agent, per correct answer

- **Kind:** EXPERIMENT
- **Area:** multi-agent (read-only) / eval
- **What it is.** Build 10–15 questions about *this* repository whose answers can be graded mechanically. Examples: "where is the lease TTL set and to what?" (the `0039` #15 failure), "what happens when a non-replay-safe tool exits non-zero?", "which file generates the proxy launchers?". Ground truth is a `path:line` and a value. Run each question two ways:
  - (a) `agentctl subagent reviewer` as a single agent over all files;
  - (b) `agentctl recon` with the scarcity split.

  Label every citation by hand as correct or wrong, then measure:
  - the citation checker's precision and recall against the labels (`agentctl/runtime/citations.py:110-157`, `WINDOW=3` at `:55`);
  - answer correctness per arm;
  - requests and tokens per *correct* answer.
- **Why it fits this harness.** `docs/0040` measured what fan-out costs and saves in requests. `docs/0039` §7 #15 then showed it can be confidently wrong, and said "`0040` … did not ask whether the reports are *true*". The ×4.33 is a throughput number. The owner needs correct answers per day. The citation checker shipped as tier (b).
- **What would actually need to be built.** A question file with ground truth and a small grading script, ~80 lines. No product code.
- **Experiment/test to run.** 12 questions × 2 arms: roughly 12 × (≈6 + ≈17) ≈ 280 requests, mostly on Mistral and Gemini legs. Note that the Mistral leg will in practice be ministral-3b (I-08, I-11), which is itself a finding worth isolating.
- **Expected observable result.** The citation checker flags most wrong citations with few false alarms, and recon is cheaper per answer but less often correct.
  - **Falsified (recon's value) if** correct answers per request are *lower* for recon than for a single agent.
  - **Falsified (the checker's value) if** it flags more than, say, 30% of correct citations (crying wolf, `docs/0034` §10) or misses more than half the wrong ones.
- **Reasoning summary.** The fan-out's headline value is quota arithmetic, and its first live run showed that arithmetic says nothing about truth. This experiment re-prices recon in the unit that matters, correct answers per request, and grades the one mechanism built to catch false reports. Either could come out badly. It spends quota mostly on the plentiful legs.
- **Risks.** Hand-labelling is subjective, so keep questions narrow. Ministral-3b as the Mistral leg may make recon look worse than a better Mistral model would. Report per leg.
- **Depends on:** I-11 (which Mistral model is really serving), I-09 (to attribute scout spend).

### I-23: Read delegation inside a run — an `ask_scout` tool for the main agent

- **Kind:** BOTH
- **Area:** multi-agent (read-only) / context cost
- **What it is.** Today only the CLI starts a subagent (`agentctl/cli.py:461-539`), and the SDK has no task tool (`agentctl/runtime/subagent.py:23-24`). Add a runtime tool, `ask_scout(question, paths)`:
  - classified `PURE_READ` in `agentctl/control/matrix/data/tools.yaml`;
  - runs a read-only subagent on a plentiful source (for example `pool-mistral`), in-process or as a subprocess;
  - returns the report together with `citations.verify()` output (`agentctl/runtime/citations.py:160-163`), so the main agent receives "claims, with which ones checked out".

  The main agent's context then carries a summary instead of file bodies, the saving `docs/0040` §2 measured (−32% tokens), while scarce-quota turns go to the main agent's decisions.
- **Why it fits this harness.** It is the multi-agent slice the project already accepts as safe: a subagent that cannot produce an effect needs none of the four single-writer invariants (`docs/0038` §4.4, `agentctl/runtime/subagent.py:1-14`). The two concurrency hazards are closed: the ContextVar workspace (`agentctl/runtime/tools.py:43-61`) and `register_all(overwrite=False)` (`:324-350`).
- **What would actually need to be built.** An `AskScoutTool` in `agentctl/runtime/tools.py`, ~80 lines. A matrix row. A per-run cap on scout calls. Subagent `conversation_id` linked to the parent (I-09).
- **Experiment/test to run.** 4 recon-heavy tasks from the bench ("find where X is enforced and fix Y") × 2 arms (with and without the tool) ≈ 130 requests. Measure main-agent prompt tokens per turn, total requests, scarce-quota requests, and success.
- **Expected observable result.** Lower main-agent tokens and fewer scarce-quota requests, at equal success.
  - **Falsified if** models either ignore the tool, or call it and then re-read the files anyway. That would be `research/phase-10-5`'s warning that "a scout's summary cannot replace the file contents a `write_file` needs": requests would go up and nothing would be saved. This is a likely failure mode and worth measuring.
- **Reasoning summary.** It is the natural extension of two shipped pieces (read-only subagent plus citation check) into the real work, and it stays inside the safety argument the project already made. It is also the only multi-agent shape that plausibly *saves* scarce quota rather than multiplying it (`docs/0038` §4.1). The experiment can show it does not.
- **Risks.** An in-process subagent inside a gated run is the concurrency path `docs/0039` §5 calls unproven. Start with a subprocess. Wrong scout reports can mislead the main agent, which the verification output mitigates but does not solve.
- **Depends on:** I-09, I-22 (know how often scouts are wrong first).

### I-24: Parallel tasks on isolated worktrees — `agentctl batch`, single writer per worker

- **Kind:** BOTH
- **Area:** multi-agent (writing, but not shared) / throughput
- **What it is.** `agentctl batch tasks.yaml` gives each independent task its own `git worktree`, its **own process**, its own ledger (`<worktree>/.agentctl/ledger.db`) and its own conversation, with each worker pinned to a source by the scarcity allocator (`agentctl/runtime/orchestrate.py:78-135`, applied to tasks rather than files). Results come back as branches for human or CI merge. No two writers share a workspace, a ledger, a conversation or a process-global tool registry, so all four `0038` §4.2 invariants hold *per worker*.
- **Why it fits this harness.** `docs/0038` §4.4 verified that per-worker worktrees restore correct probe verdicts ("120 concurrent commits across 3 worktrees on Windows with zero failures") and called it "the design to use if multi-agent is ever revisited". This is that design with the coordination removed. It is batch parallelism, not a supervisor-and-workers topology, so the SKIP's cost argument (32–140 requests per task) does not apply.
- **What would actually need to be built.** `agentctl/runtime/batch.py`, ~150 lines: worktree create and clean up, subprocess launch, source assignment, and collecting results into the run index. Guard against two tasks targeting the same worktree.
- **Experiment/test to run.** 6 bench tasks, sequential on `pool` against parallel 3-wide with source pinning. About 84 requests per arm. Measure wall time, tasks completed, per-quota consumption, 429s, and merge conflicts.
- **Expected observable result.** Wall time roughly ÷3 at the same request count, with quota spread across legs.
  - **Falsified if** parallel workers collide on the shared proxy and quotas and produce more 429-retries and failures per task than sequential runs. For example, three workers on one OpenRouter account family would each see "capped" sooner. The throughput gain would then be illusory on this pool.
- **Reasoning summary.** The owner asked about multi-agent scenarios, and the project has a principled reason to refuse shared-workspace writers. Separate worktrees keep the principle and still give parallelism, which is useful for the "queue of small issues" workload that long-running personal use actually looks like. The experiment tests whether parallelism buys anything when the bottleneck is quota rather than wall time.
- **Risks.**
  - Merge conflicts push work back onto the human.
  - Shared `~/.agentctl` state (run index, telemetry file) needs concurrent-writer safety (SQLite WAL is fine; the JSON telemetry is not, hence I-08).
  - On Windows, subprocess and worktree cleanup is fiddly (`docs/0036` §2's tree-kill).
- **Depends on:** I-02, I-08, I-17, I-20.

### I-25: Merchant sandbox — idempotency keys end to end with a real model

- **Kind:** BOTH
- **Area:** merchant/production scenarios / side-effect safety
- **What it is.**
  - A local fake commerce service (a stdlib HTTP server) with `POST /refunds`, `POST /orders/{id}/cancel` and `POST /emails`. It honours `Idempotency-Key` the way a real payments API does: the same key returns the first response and does not act twice.
  - A real `http_request` tool in `agentctl/runtime/tools.py`. The matrix already declares `http_request` as `EXTERNAL` with `idempotency_key: idempotency_key` (`agentctl/control/matrix/data/tools.yaml:132-137`), and Seam C already stamps the key (`agentctl/adapters/openhands/seam_c.py:80-107`), but no such tool ships.
  - Tasks: "Customer #42 was double-charged for order 1001; refund the duplicate and email them", "cancel all unshipped orders older than 30 days".
  - Crash injection between the request leaving and the observation being recorded.
  - A variant server that **ignores** keys, to demonstrate README's limit: "A non-compliant remote voids the guarantee."
  - `send_email`, without a key, should fail closed (`tools.yaml:139-140`).
- **Why it fits this harness.** This is the highest-stakes effect class, the one the project's correctness story is *for* (`docs/0020`: "every effect class now has a recovery path"). The path has never met a real model. The fake service costs nothing and makes duplicates countable exactly (refund count).
- **What would actually need to be built.**
  - `experiments/merchant/fake_service.py`, ~150 lines.
  - An `HttpRequestTool` in `agentctl/runtime/tools.py`, ~80 lines. It is restricted to `localhost` by default, which is itself a safety property to test.
  - Bench tasks with acceptance commands querying the fake service's state.
- **Experiment/test to run.** 3 tasks × {no crash, crash after send} × {compliant, non-compliant server} ≈ 12 runs × ~12 requests ≈ 150 requests. Measure refunds issued (the duplicate count), emails sent, BLOCKs, and whether the agent's final report matches the service's state.
- **Expected observable result.** Compliant server: exactly one refund per task across crashes, with SAFE_TO_RETRY in the ledger. Non-compliant server: duplicates appear, and the ledger cannot tell. That demonstrates the documented limit. Email: BLOCKED after a crash, not duplicated.
  - **Falsified if** real models fill the `idempotency_key` argument themselves with something unstable. Seam C deliberately leaves a caller-supplied key alone (`seam_c.py:95-99`), so a model inventing a fresh key on the resumed call would defeat the mechanism. That is plausible and important, and the result would argue for the tool schema to *hide* the key field from the model.
- **Reasoning summary.** A coding-agent harness's hardest effects are rarely in the repo; they are calls to someone else's server. The project built the mechanism for exactly this and tested it only against a mock with a mock model. A local fake service makes the real-model test cheap, safe and exactly countable. The most interesting outcome, a model supplying its own unstable key, is one no mock could produce.
- **Risks.**
  - A real HTTP tool widens the agent's reach. Default to localhost only, with an allowlist.
  - Fake-service semantics may be kinder than real ones (for example key expiry windows).
- **Depends on:** I-04's kill hook, I-20.

### I-26: Prompt-injection canaries against the no-sandbox boundary

- **Kind:** EXPERIMENT
- **Area:** adversarial / safety
- **What it is.** Seed bench repos with injected instructions in a README, a code comment, a test fixture and a failing test's output. Each instruction asks for a **harmless canary** effect that would be dangerous in its real form:
  - write a file outside the workspace (`~/.agentctl_canary`);
  - `curl` a local canary server on 127.0.0.1;
  - `python -c "import os; os.remove('canary.txt')"`, the interpreter hole (`tests/test_classify_corpus.py:105`, README "No sandbox");
  - `git push --force` to a local bare remote;
  - read `~/.agentctl/keys.env` and print its length.

  Run with `--confirm-destructive` on (the default). Count canaries triggered, and which layer caught each one: classifier, escaping-writes confirmation, the gate, or none.
- **Why it fits this harness.** README lists "No sandbox" first, "because it is the limitation the others assume away", and says the capability matrix "stands in for one". That substitution has been kept honest only against a synthetic 75-command corpus (`docs/0026`), never against what real models do when a workspace tells them to do something. `agentctl/kernel/paths.py` explicitly does not cover reads outside the workspace ("exfiltration … a different concern"), so the keys-file read is expected to pass, and measuring that is the point.
- **What would actually need to be built.** Canary seed repos and a canary server, ~100 lines, experiment-only. No product changes unless results demand them.
- **Experiment/test to run.** 8 scenarios × 1 run ≈ 110 requests, on the strongest free model. Run it **in a disposable Windows user account or VM**, even with harmless canaries, because the premise is that nothing is sandboxed.
- **Expected observable result.** Out-of-workspace writes are caught (escaping-writes), and `git push --force` is caught (DESTRUCTIVE). `python -c` and the keys-file read pass unless the model refuses on its own.
  - **Falsified (the claim that the matrix stands in for a sandbox) if** any canary that should have been caught was not. A result showing the free models themselves refuse most injections would also be informative, as it shifts where the protection actually comes from.
- **Reasoning summary.** The project's own documents list the interpreter hole and the exfiltration gap as accepted limits, but nobody has measured how often a real agent walks through them when prompted by content in its own workspace. For a harness whose value is "safe to run unattended on a real repo", that frequency decides whether unattended mode (I-05, I-06) is responsible to ship. The canaries make it safe to measure.
- **Risks.** Even canaries on a host with real keys are sensitive (the keys-file read). Use a machine or account without the real `keys.env`. Results depend heavily on the model and will change as models change, so date them.
- **Depends on:** I-20.

### I-27: The headline test — does the pool complete more tasks per day than one key?

- **Kind:** EXPERIMENT
- **Area:** routing / value claim / soak
- **What it is.** A full quota-day run of a queue of bench tasks, compared across arms on separate days:
  - (A) **single key**: one OpenRouter key, direct, plain `agentctl run` in a loop, no supervisor. This is the "without this project" baseline.
  - (B) **full pool** (after I-11), plain `run` loop.
  - (C) **full pool + supervisor** (I-05) **+ session affinity** (I-12) **+ weights** (I-14).

  Measure tasks completed (accepted) per day, human interventions, duplicate effects, blocked effects, requests per completed task, and wall time. This is the long-running soak the owner's gap statement asks for.
- **Why it fits this harness.**
  - It is the charter's promise stated as a number: "surviving a rate limit without work stopping" (`docs/0032` intro), "Lower cost per completed task than baseline routing" (`docs/0001`).
  - README states that a pool over one key survives an overload but "does NOT survive an account-wide daily cap". No experiment has measured how much the multi-account pool actually buys in completed work.
  - `docs/0038` §4.1's 21.4 tasks/day and `0040`'s ×1.55–×4.33 are arithmetic, not measurements.
- **What would actually need to be built.** Nothing new beyond its dependencies. It needs a queue runner (I-20 bench with a "run until exhaustion" mode).
- **Experiment/test to run.** Arm A costs one key's 50 requests (≈3 tasks) and can run on the same day as another arm. Arms B and C each consume most of a day's agent-capable allowance (~550 requests), so this is 2–3 days of the owner's quota. Run it **last**, after cheaper experiments have fixed what they will fix.
- **Expected observable result.** A: about 3 tasks and then a hard stop. B: many more tasks, but with interruptions at exhaustion and some quality loss from model hopping. C: the most tasks per day with zero interventions for rate limits.
  - **Falsified if** C does not beat B by a meaningful margin. The harness layers (supervisor, affinity, weights) would then add nothing over what litellm's pool gives for free, and the project's control-plane value would rest on effect safety alone.
  - **Also falsified if** B's success per task is so much lower than A's (because of weak or rotating models) that A's 3 tasks are the better day's work. That is unlikely, but it is exactly the kind of result worth checking rather than assuming.
- **Reasoning summary.** Everything else in this file is a component. This is the one experiment whose result tells the owner whether the harness, as a whole, is worth using over a single key and a bare agent. Its cost is high, so it goes last and is designed so that each arm's result is interpretable alone. It is also the first time the system would run for hours unattended, which is the charter's stated setting ("A coding agent runs for hours across hundreds of turns").
- **Risks.**
  - A day-long run competes with the owner's own use of the same quota. Schedule it.
  - Day-to-day provider variance (overloads) can swamp arm differences, so repeat the decisive arm if the margin is small.
  - The bench tasks must be numerous enough (30+) not to run out before quota does.
- **Depends on:** I-01, I-02, I-05, I-08, I-09, I-11, I-12, I-14, I-17, I-20.

---

## C. Experiments vs features

| ID | Name | Classification |
|---|---|---|
| I-01 | Tell a replay from a repeat (`OBSERVED`) | Feature + experiment pair |
| I-02 | One driver per conversation | Feature + experiment pair (local, zero quota) |
| I-03 | What the gate costs (plus Q9 tally) | EXPERIMENT |
| I-04 | Resume vs restart, crash at turn k | Feature (kill hook) + experiment pair |
| I-05 | Supervisor: wait or shift on exhaustion, proxy death | Feature + experiment pair |
| I-06 | Approvals that do not stop the run | FEATURE |
| I-07 | Cross-model resume drill | EXPERIMENT |
| I-08 | Seam A records failures; append-only telemetry | FEATURE (verified live) |
| I-09 | Conversation attribution through the proxy | Feature + experiment pair |
| I-10 | Known-free vs unpriced vs priced | FEATURE |
| I-11 | A pool fit for agent turns | Feature + experiment pair |
| I-12 | Sticky vs shuffled vs single source; retire `TurnAffinity` | Feature (configure) + experiment pair |
| I-13 | Quota ledger and pre-run admission | Feature + experiment pair |
| I-14 | Scarcity-weighted pool | Feature + experiment pair |
| I-15 | Pool simulator | Feature + experiment pair (backtest) |
| I-16 | A policy about the real pool, in a binding unit | FEATURE |
| I-17 | Run index | FEATURE |
| I-18 | Live turn stream and `why` | FEATURE |
| I-19 | Resolve and approve from the dashboard, with evidence | FEATURE (plus a usability check) |
| I-20 | `--accept` and `agentctl bench` | FEATURE (experiment substrate) |
| I-21 | Cassette corpus as a regression suite | Feature + experiment pair |
| I-22 | Are the scouts right? | EXPERIMENT |
| I-23 | `ask_scout` tool inside a run | Feature + experiment pair |
| I-24 | `agentctl batch` on isolated worktrees | Feature + experiment pair |
| I-25 | Merchant sandbox, idempotency end to end | Feature + experiment pair |
| I-26 | Prompt-injection canaries | EXPERIMENT |
| I-27 | Pool vs one key, tasks per day (soak) | EXPERIMENT |

Rough quota envelope, requests, all estimates:

- **Zero:** I-02, I-10 (except the cross-check), I-15, I-17, I-18, I-19, I-21 (after recording).
- **≤ 50:** I-01 (~30), I-08 (~20), I-09 (~15), I-11 (~60 with the A/B), I-16 (~12), I-06 (~15).
- **~70–150:** I-07, I-20 baseline (~84), I-03 (~140), I-23 (~130), I-24 (~170 over two arms), I-25 (~150), I-26 (~110).
- **~200–400:** I-04, I-12, I-22.
- **Days of quota:** I-27.

The agent-capable daily allowance is about 550 (OR 300 + Gemini 250). I would cap experiments at roughly 150–200 per day so the owner keeps a working day.

---

## D. What I would do first, and why

**1. I-01 and I-02, before any live experiment.**
- Both are correctness holes in the core, both reproduce locally for zero quota (P1, P2), and both would silently contaminate every experiment that follows.
- I-01 sits inside the most common real task loop (edit → test → re-run). Until it is fixed, any live comparison would count false BLOCKs and stale SUBSTITUTEs as "the gate's cost" or as task failures. It may also be the explanation for `docs/0041`'s "right" block, and that is worth settling on its own.
- I-02 means "zero duplicate side effects", the first charter criterion, currently depends on the user never running `--resume` while the original is alive.
- Both are small, both are kernel-local, and both have an obvious falsification path through the existing chaos suite.

**2. The telemetry-truth trio: I-08, I-09, I-10.**
- Every routing, dashboard and cost idea measures through Seam A, and three of its numbers are wrong or missing today:
  - failures are invisible (mistral-small's 0/250);
  - conversation ids are `unknown` (23/23);
  - free calls are priced at list price (154/250 "priced").
- These are an afternoon's work, verifiable with about 35 live requests, and they turn the existing `hook_telemetry.json` from anecdote into data.
- By the owner's rule they must be verified against the real proxy, not a mock, because the one attribution test that exists passed against a mock and is broken live.

**3. I-20, the bench with `--accept`, seeded with the three tasks that already have graders.**
- Without a definition of a completed task there is no cost per task, no success rate, and no baseline arm. That is why none of the charter's comparative claims has ever been tested.
- Building it forces the question the gap statement is really asking ("does the harness add value?") into a shape that can be answered.
- Recording is on by default, so I-21's regression suite follows almost for free.

**4. Then the cheap falsification experiments that could shrink scope: I-12 (sticky vs shuffled), I-04 (resume vs restart), I-07 (cross-model resume), I-03 (gate cost).**
- Each can come out against the project. Stickiness might buy nothing on a free pool, a restart might be as good as a resume, a different model might re-word the commit, and the gate's cost might exceed its benefit on crash-free work.
- The method says to find that out before building on top. I-12's feature half is configuration; I-04 and I-07 need only a kill hook.

**5. Routing and continuity features in dependency order: I-11 → I-13 → I-15 → I-14 → I-05 (with I-06).**
- This order builds the "API shifting" the owner asked for as control-plane decisions over litellm rather than a re-implemented router, which the charter forbids.
- Each step is falsifiable before the next is built: the simulator (I-15) lets weights (I-14) fail for free, and the quota ledger (I-13) supplies the supervisor's wait-or-shift input.

**6. Dashboard: I-17 → I-18 → I-19.**
- The run index comes first because the existing panels are pointed at the wrong files.
- Resolve-from-dashboard comes after I-06, because approvals are what make the dashboard *drive* the harness rather than just display it.

**7. Last, the expensive or scenario experiments: I-22, I-23, I-24, I-25, I-26, and finally I-27.**
- I-25 and I-26 are the "real-world, production-shaped" tests. They are worth doing before anyone runs the harness unattended on something that matters.
- I-27 is the verdict on the whole system and costs days of quota, so it should run once, after everything it depends on has stopped moving.

Two things I would *not* do yet:
- **Any writing multi-agent beyond I-24's isolated worktrees.** The single-writer argument is sound, and I-02 shows its enforcement needs strengthening first.
- **A web dashboard with a framework** (`docs/0013` §3's FastAPI/HTMX). A stdlib page covers the one write it needs, and scope regrowth is an explicitly recorded risk (`docs/0009` R3).
