---
Number:        0024
Title:         The Right Outcome by the Wrong Route
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-11
Supersedes:    —
Superseded-by: —
Depends-on:    0023
---

# 0024 — The Right Outcome by the Wrong Route

A demo run passed. The commit was not duplicated. The gate was crashing.

**176 tests passing.** Fix in `agentctl/kernel/gate.py`.

---

## 1. What the passing run was hiding

Running the real-provider demo produced `VERDICT: PASS` — one commit before the
crash, one after the resume, no duplicate. Correct.

The ledger told a different story:

```
ledger: INTENT probe=None id=call_bdc840008e6041d792b70667
```

`INTENT`, not `COMMITTED`. No probe verdict. A resolved effect should not look
like that, so the decision log was worth reading:

```
resume decision: BLOCK
reason: "gate error, failing closed:
         IllegalTransition('no record for call_ea0bdfddec0344db96783c18')"
```

The gate had **crashed**, and the fail-closed wrapper turned the crash into a
`BLOCK`. The commit was prevented by an exception, not by a decision.

## 2. The bug

`docs/0023` added intent-hash aliasing: when a call arrives under an id the
ledger has never seen, look for the same logical effect under a different id
before treating it as a first sighting.

That lookup worked. What followed did not. Every ledger write in
`_resolve_ambiguous` addressed **`call.tool_call_id`** — the caller's id — while
the record being decided about was the twin's. Under aliasing those differ, so
the write hit a row that does not exist:

```python
self.store.reconcile(call.tool_call_id, verdict, landed=True)   # no such record
```

Six writes, all with the same defect: `block`, `reconcile` ×3, the destructive
escalation, and the final fail-closed block. All now address
`rec.tool_call_id` — the record actually examined.

## 3. Why nothing caught it

Two layers failed in the same way, and the way is worth naming.

**The unit test asserted the verdict, not the mechanism.**
`test_an_aliased_ambiguous_effect_still_blocks` checked
`d.verdict is Verdict.BLOCK`. **A crashing gate also returns `BLOCK`** — that is
what fail-closed means. The test could not distinguish "decided to block" from
"fell over and blocked", so it passed throughout.

**The acceptance test asserted the outcome, not the route.** It counted commits.
One commit is one commit whether the gate reasoned or exploded.

Both now assert the mechanism:

- `test_an_aliased_ambiguous_effect_blocks_WITHOUT_a_gate_error` requires the
  absence of `"gate error"` in the reason, and requires the outcome to land on
  the **original** record while the alias keeps none of its own.
- `test_an_aliased_probe_result_lands_on_the_original_record` covers the
  `LANDED` path the live run actually hit.
- Both acceptance harnesses now count gate errors and **fail on any**, with the
  note: *a correct result via an incorrect mechanism is not a pass.*

## 4. The general lesson

This is the third appearance of one pattern, and it deserves to be stated as a
rule rather than rediscovered a fourth time.

| Where | The trap |
|---|---|
| `docs/0014` §5 | A harness failed silently *toward* the hypothesis |
| `docs/0023` §4 | A mock returned a fixed id, so a test could not fail |
| **here** | A safety fallback produced the right answer for the wrong reason |

> **Fail-closed makes failures look like decisions.** Any component whose error
> path and success path share an outcome must be tested on the *route*, not the
> result. Assert the mechanism: which record moved, which reason was given,
> whether an exception was swallowed.

The corollary is uncomfortable: **fail-safe designs are harder to test than
fail-fast ones**, because the safe failure is indistinguishable from correct
operation at the boundary. That is a cost of the design in `docs/0008` §6.5,
and it should be paid deliberately rather than discovered.

## 5. The run after the fix

```
commits_before          1
commits_after_crash     2
commits_after_resume    2
gate_errors             0

fresh id                call-f5d55045-9e08-4930-8046-05b16b1a3bed
resume id               call-8182ce3c-f8bf-4fe4-a59a-ebbe14c080e6
resume decision         SUBSTITUTE -- "git probe: the effect already landed"
ledger                  COMMITTED  probe=LANDED
```

Two different ids across the crash, matched by intent hash, resolved by the git
probe, reconciled onto the original record. The mechanism from `docs/0023`
working end to end against a real provider — which the earlier "passing" run
never actually demonstrated.

11,435 prompt + 580 completion tokens, $0.00 billed.

## 6. Consequences

- `agentctl/kernel/gate.py` → `_resolve_ambiguous` documents the rule that
  every write targets the record, never the caller.
- `docs/0012` §6 → the testing rules gain: assert the route when the error path
  and the success path share an outcome.
- `docs/0023` §4 → its fix was correct in principle and incomplete in code; this
  completes it.
- Both acceptance harnesses now fail on a gate error.
