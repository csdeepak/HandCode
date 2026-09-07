---
Number:        0016
Title:         M2a Results — The Gate Works
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0012, 0014, 0015
---

# 0016 — M2a Results

M0 proved the disease. M2a proves the cure.

**Run:** 2026-09-08 · `openhands-sdk 1.45.0` · Python 3.13.7 · zero cost.
Code: `agentctl/`. Acceptance: `experiments/0001-m2a-chaos/`.

---

## 1. The result

```
                       M0 (no gate)      M2a (gate at Seam B)
effects after crash          1                    1
effects after resume         2  ← duplicate       1  ← prevented
resume decision              —                    BLOCK (NON_IDEMPOTENT_WRITE)
ledger pending               —                    0
```

Same scenario, same harness, same crash point. **The duplicate is gone.**

`0009` **Q16 → RESOLVED empirically.** `ConversationState.block_action` does
prevent execution, not merely record disapproval. `0015` read that from source;
this executes it.

## 2. What shipped

| Component | Spec | Status |
|---|---|---|
| `kernel/ledger/models.py` | `0012` §2.3 | Effect classes, states, legal transitions |
| `kernel/ledger/schema.sql` | `0012` §2.1 | WAL, `synchronous=FULL`, lease table |
| `kernel/ledger/store.py` | `0012` §3.1 | Write-ahead protocol, leases, **fencing** |
| `kernel/classify.py` | `0012` §5.1 | Capability matrix, argument-aware rules |
| `kernel/gate.py` | `0011` §3 | The decision. Never raises. |
| `adapters/openhands/seam_b.py` | `0008` §3.5 | `block_action` binding |
| `control/matrix/data/tools.yaml` | `0012` §5.1 | 12 bash rules, MCP defaults |

**49 tests, all passing.** No executor wrapping, no fork.

## 3. Two design flaws the tests found

### C1 — "first match wins" was unsafe

The classifier originally returned the first matching rule. Under test:

```
ls && rm -rf /important   ->   PURE_READ      ✗ WRONG
```

The benign `ls` prefix matched first, and a destructive command would have gone
straight through the gate. **A safety classifier must take the most dangerous
match, not the first.**

Fixed by adding `EffectClass.severity` and taking the maximum. This is the same
principle as defaulting unknown tools to `EXTERNAL`: when rules disagree, err
toward danger.

`docs/0012` §5.1 should state this explicitly — it is not obvious from the YAML
that rule *order* does not determine precedence.

### C2 — a crashed process locked out its own recovery

The chaos run deadlocked, and the reason was instructive: the killed process
still held a live 300-second lease, so the resume refused to start. The safety
property held perfectly and the system was unusable.

The wrong fix is a weaker lease. The right fix is **making takeover safe**:

- `acquire(..., takeover=True)` steals a live lease and bumps the fence token.
- **Every write is now fenced.** A zombie — a process that crashed, or hung and
  later wakes — carries an older token and is rejected by `StaleFence` on its
  next write.
- Default TTL cut 300s → 60s, with `renew()` for long runs.

Fencing was in the `0012` schema but **nothing enforced it**. It was a column,
not a guarantee. Now it is checked on every state transition, which is what
makes takeover something other than a hole in the design.

> **Generalisation.** A safety mechanism that has no recovery path is not a
> safety mechanism; it is an outage. Both halves have to be designed together.

## 4. What M2a cannot do

Honest limits, so nobody mistakes this for finished:

- **No `SUBSTITUTE`.** When an effect already landed, Seam B blocks rather than
  returning the recorded observation. Correct, but the agent sees a rejection
  where it could have seen a result. **M2b (Seam C) fixes this.**
- **No reconciliation probes.** Every ambiguous non-idempotent effect fails
  closed. With the git probe (M4), most would resolve automatically.
- **Nine crash points untested.** The suite covers one. `0012` §6 wants all
  nine, parametrised.
- **One harness.** The adapter is ~170 lines, as `0008` §12 requires.

## 5. Is it worth running daily?

Yes, and that was the point of splitting M2. Today it converts *silent
duplicate side effects* into *visible blocked turns*. A blocked turn is
annoying; a duplicated `git push` is not recoverable.

The blocked effects are queryable now — `store.blocked()` is what `0013` §3
Panel 3 will render.

## 6. Consequences

- `0009` Q16 → RESOLVED.
- `0012` §5.1 → add the most-dangerous-match rule.
- `0012` §2.1 → document fence enforcement and `takeover`.
- `0013` §3 → Panel 3 has real data to show.
- Next: **M2b** (Seam C, `SUBSTITUTE`) or **M4** (git probe). M4 gives more
  value per hour — it turns most blocks into automatic resolutions.

## 7. Method note

Every bug in this milestone was found by a test or by the chaos run, not by
reading. The classifier flaw in particular would have shipped: it looked
correct, the YAML looked correct, and it was wrong in the one direction that
matters.

`0012` §6's rule earned itself immediately — the chaos harness reported
`INCONCLUSIVE` twice, with the reason, rather than a false `FAIL`. A harness
that fails silently toward your hypothesis is worse than no harness.
