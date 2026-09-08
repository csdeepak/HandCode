---
Number:        0019
Title:         The Nine-Point Chaos Suite
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0008, 0012, 0018
---

# 0019 — The Nine-Point Chaos Suite

The correctness claim in `docs/0008` §10 rested on **one** tested crash point.
It now rests on nine, times two effect kinds, with real process death and real
effects counted from the filesystem.

**38 tests, ~40s.** Runs on every commit.
Code: `tests/test_chaos_nine_point.py`, `experiments/0004-nine-point/worker.py`.

---

## 1. What it tests

For each of the nine points in `docs/0012` §6:

```
RUN 1   drive the write-ahead protocol; os._exit() at the chosen point
RUN 2   resume
ASSERT  the side effect happened AT MOST ONCE
```

`os._exit()` skips every `finally` block, `atexit` hook and buffered write —
as close to `kill -9` as a process can do to itself, and unlike a timed kill it
lands exactly where intended every time.

Two effect kinds, because they fail differently:

| | behaviour | why it matters |
|---|---|---|
| `git commit` | atomic from our side | the commit exists or it does not |
| file append | **non-atomic** | `mid_tool` leaves half a line on disk |

The append case is the nastier one and the reason `INCONCLUSIVE` exists.

## 2. Driving the kernel, not the SDK

`docs/0012` §6 sketched this as an SDK-level test. It is not.

The guarantee is a property of the **protocol**, and testing it at the kernel
makes the crash point *chosen rather than raced for*. It is also ~40s instead
of ~4 minutes, which is the difference between a suite that runs on every
commit and one that does not.

The SDK integration is already covered by experiments `0001`–`0003`. Those
prove the seams bind correctly; this proves the protocol is sound. Both are
needed and neither substitutes for the other.

**Making the points distinguishable** required wrapping the store:
`before_intent` and `after_intent` are on either side of a write that happens
*inside* `EffectGate.guard`, so the crash hook lives in a `CrashingStore`
subclass rather than in the test.

### An honest note on the nine

Pairs 6/7 (`after_tool`, `before_commit`) and 8/9 (`after_commit`,
`before_observation`) name the **same instant** from either side. The suite
therefore covers seven distinct states, not nine. Both names are kept because
the spec names them and because a future change could separate them — but the
count should not be read as nine independent cases.

## 3. What it found

Nothing. All 38 passed on the first run.

That is worth stating plainly rather than celebrating: the protocol had already
been shaped by four milestones of bugs found the hard way. The suite's value is
now **regression** — it is what stops any of that being quietly undone.

## 4. Proving the suite has teeth

A suite that cannot fail is worthless, and one that passes first time invites
exactly that suspicion. So it was verified by mutation.

Neutering the gate — treating every ambiguous `INTENT` as safe to re-run:

```python
if True:  # MUTATION: pretend everything is replay-safe
    return GateDecision(Verdict.EXECUTE, cls)
```

produces **7 failures**, precisely where the effect had already landed:

```
test_git_commit_never_happens_twice[after_tool]
test_git_commit_never_happens_twice[before_commit]
test_append_never_happens_twice[mid_tool]
test_append_never_happens_twice[after_tool]
test_append_never_happens_twice[before_commit]
test_resume_verdict[after_tool-SUBSTITUTE]
test_resume_verdict[before_commit-SUBSTITUTE]
```

It catches real duplicated effects counted from the filesystem, not merely
mismatched verdicts. The gate was restored and the suite is green again.

**Any change to the gate, the ledger or a probe should be mutation-checked the
same way** before being trusted.

## 5. The three layers of assertion

| Layer | Asserts | Guards against |
|---|---|---|
| **Effect count** | at most one effect, ever | the actual failure we exist to prevent |
| **Ledger state** | the state `docs/0008` §10 predicts | silent protocol drift |
| **Resume verdict** | the specific decision expected | a gate that blocks everything |

That third layer matters more than it looks: **a gate that refused every call
would pass the first two layers perfectly.** `test_the_commit_actually_happens_
when_nothing_crashes` closes the same hole from the other side.

## 6. Results

| Point | Ledger after crash | Resume verdict |
|---|---|---|
| `before_action_event` | — | EXECUTE |
| `after_action_event` | — | EXECUTE |
| `before_intent` | — | EXECUTE |
| `after_intent` | `INTENT` | EXECUTE (probe: did not land) |
| `mid_tool` | `INTENT` | EXECUTE (git) / BLOCK (partial append) |
| `after_tool` | `INTENT` | SUBSTITUTE (probe: landed) |
| `before_commit` | `INTENT` | SUBSTITUTE |
| `after_commit` | `COMMITTED` | SUBSTITUTE |
| `before_observation` | `COMMITTED` | SUBSTITUTE |

**Every point resolves without a human.** The probes cover the whole
ambiguous range for these two effect kinds — which is exactly what M4 was for,
and this is the evidence.

## 7. What this does *not* prove

- **Only two effect kinds.** `EXTERNAL` effects — HTTP, email, webhooks — have
  no probe and are untested here. They still fail closed, which is correct but
  unhelped.
- **Single process, single machine.** Fencing has unit tests; concurrent
  resume across hosts is not exercised.
- **Not the SDK path.** Experiments `0001`–`0003` cover that, at one crash
  point each.
- **Crash, not corruption.** A torn SQLite page or a filesystem that lies about
  `fsync` would defeat this. `synchronous = FULL` is the mitigation, not a
  proof.

## 8. Consequences

- `docs/0008` §10 → the table is now executable, not aspirational.
- `docs/0012` §6 → record that the suite drives the kernel, and why.
- `docs/0012` §8 → add mutation-checking as a rule for gate changes.
- `verify.py` → the suite is its own check.
- Next: **M5** (cost ledger) or an `EXTERNAL` idempotency-key probe.
