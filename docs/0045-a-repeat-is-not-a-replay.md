---
Number:        0045
Title:         A Repeat Is Not a Replay
Type:          DECISION
Status:        ACCEPTED
Created:       2026-10-01
Supersedes:    —
Superseded-by: —
Depends-on:    0023, 0031, 0042, 0043, 0044
---

# 0045 — A Repeat Is Not a Replay

`docs/0042` I-01, built. Phase 1 of `0043`.

**The rule.** Once a tool's result — success *or* reported failure — is in the
history the model reads, an identical later call is the model choosing to
repeat it. It is executed, not matched to the earlier call. Every crash case is
unchanged.

---

## 1. The defect

Intent-hash aliasing (`0023` §4) was built for one case. A process crashes
before a call's result is persisted, a different model re-mints the same call
under a new id, and keyed lookup would miss it. So `find_by_intent` matched
calls by tool name plus arguments.

It matched **every** identical call in the conversation, including the most
common loop in coding work: edit → run the tests → run them again.

| What the model did | What the gate did |
|---|---|
| Re-ran a test command after a fix | SUBSTITUTE: handed back the *old* failing output (P1) |
| Re-ran a command after it failed | BLOCK: "whether it landed is unknown" (P1) |
| Ran `python -c "divide(1, 0)"` to show the new error | Recorded a BLOCKED effect "awaiting your decision" (`0044` N15) |
| Fixed the git identity, then re-issued `git commit` | Refused twice; the agent had to reword the command (`0044` N15) |

That made the protection cosmetic. The block stopped only byte-identical
retries, and the model got past it by rewording.

## 2. Why the line can move

The SDK persists every event **before** any caller callback runs, and if
persisting raises, no callback runs at all. This was checked in SDK 1.45.0 and
1.50.1 (`local_conversation.py`, the `_default_callback` comment and the
`[_default_callback] + callback_list` composition).

Seam B's `_close` is a caller callback. So by the time it sees an
`ObservationEvent`, that observation is durably in the history:
- the harness will never re-drive the action;
- the model has the result in view on every later turn.

That is what OBSERVED now means. The state existed from the start
(`models.py`), but `store.observed()` had no callers.

## 3. What changed

| Where | Change |
|---|---|
| `models.py` | `INTENT → OBSERVED` is legal, so delivery is **one write**. Going through COMMITTED would open a crash window in which a reported failure sat as COMMITTED, the `0031` §10 bug |
| `store.deliver()` | Writes OBSERVED with `committed_at`, the observation and, for a reported failure, the error |
| `store.find_by_intent()` | Only the **most recent** identical call is a candidate, and not when it is OBSERVED |
| `store.committed_since()` | Counts OBSERVED as landed, so the sole-writer check (`0038` §3) still sees delivered siblings. A delivered failure counts too: unknown is treated as "it might have" |
| `gate.record_observation()` | The entry point for a caller that knows the result was persisted. A replay-safe failure stays FAILED, as before |
| `gate.mark_observed()` + `GateDecision.record_id` | A result substituted after a crash becomes OBSERVED once it reaches the model. Otherwise every later deliberate repeat would get the old output |
| `seam_b._close` | Uses both of the above |

**Not changed:**
- `record_success` and `record_tool_error` keep their old shapes for callers
  that cannot attest delivery.
- A call re-driven under its **own** id is still substituted, whatever its
  state, because that is a replay by definition.

## 4. What it costs: the line that moved

`0023` §4 called aliasing "deliberately conservative". That conservatism is now
narrower, in one specific place.

**A model that saw a failure and retries the identical command is no longer
stopped.** For a test runner that is the point. For `curl -X POST` that timed
out after the server processed it, the retry is a second effect, and nothing
local can know.

Three reasons this is acceptable:
1. **The old block did not protect anything.** It stopped only byte-identical
   retries. Phase 0 watched the agent reword its way past it.
2. **The gate's guarantee was always about replay.** The README says the gate
   stops an effect happening *twice*, and `--confirm-destructive` stops one
   happening *at all*. A crash still never causes a repeat (§5).
3. **Remote effects have a real answer.** Idempotency keys make a retry safe
   however it is issued (`0020`). That answer survives this change, and
   I-25's merchant sandbox is the experiment that tests it with a real model.

The boundary is pinned by a test so it cannot move further unnoticed:
`test_a_reminted_call_after_the_result_was_seen_is_the_models_call`.

## 5. Evidence

**Unit, zero quota.** `tests/test_observed.py`, 13 tests:
- P1's two cases;
- the exact Phase 0 commit sequence;
- every unchanged crash case: an unobserved twin, an INTENT twin, a BLOCKED
  twin, the same id re-driven, most-recent-only;
- the sole-writer check seeing an OBSERVED sibling;
- both pieces of Seam B wiring.

**Mutation-checked:**

| Mutation | Caught by |
|---|---|
| Alias to OBSERVED twins again | 5 tests |
| `committed_since` ignores OBSERVED | The sole-writer test |
| Also skip COMMITTED twins (the over-eager fix) | **Real duplicate commits** in the chaos suite: re-minted resume at `after_commit` and `before_observation`, plus the unobserved-twin test |

**Chaos, real process death.** 38 → 52 tests.
- **The tenth point**, `after_observed`, runs through all four per-point
  tables. The state is OBSERVED, and a same-id resume SUBSTITUTEs.
- **A re-minted resume** runs at every point where the result had not reached
  the model, and never commits twice.

**`verify.py`: 10/10.**
- M2b first came back INCONCLUSIVE: its acceptance pinned the post-substitution
  state as COMMITTED.
- It now requires OBSERVED. That is stricter, and it is the first proof
  through the real SDK that `mark_observed` fires after a substitution.

**Live, the `0041` rule (E-16).** Two identical seeded repos with a failing
test, run on `gemini/gemini-3.6-flash`. The task: *run `python -m pytest -q`,
fix `stats.py`, run `python -m pytest -q` again.*

| | Old (`6870711`) | New |
|---|---|---|
| Outcome | fixed, 1 passed | fixed, 1 passed |
| Exit code | **1** | **0** |
| Gate decisions | 7 EXECUTE, **2 BLOCK** | 6 EXECUTE |
| Left for a human | **1 blocked effect** | nothing |
| The identical `pytest` (hash `462eaef1`) | first run BLOCKED; two identical retries refused; the agent reworded twice (`4f93a391`, `afdd4e81`) | ran twice: OBSERVED with the failure, then OBSERVED passing |
| Wall time | ~7 min | ~2 min |

n = 1 per arm, on one model, so the direction is clear and the magnitude is
not. Both repos had a local git identity configured, to keep `0044` N12 out of
the comparison.

## 6. Left open

- **P1 as written still prints SUBSTITUTE.** It calls `record_success`, which
  attests no delivery. That is the conservative path, correctly unchanged. The
  regression tests use `record_observation`, the path Seam B takes.
- **Intent-hash fragility across models is untouched.** A cross-model resume
  that *rewords* the call still misses its twin, and I-07 tests that. This
  change narrows when aliasing applies; it does not make the match smarter.
- **I-02 (one driver per conversation) is next.** It matters more now, because
  `agentctl run --resume` was shown to work live in `0044` §3, so it will be
  used.
