---
Number:        0020
Title:         The EXTERNAL Idempotency-Key Probe
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0017, 0018, 0019
---

# 0020 — The EXTERNAL Idempotency-Key Probe

The last unguarded effect class. It needed a different mechanism from every
other probe, and a fourth verdict.

**136 tests passing.** Code: `agentctl/kernel/reconcile/external.py`.

---

## 1. Why fingerprinting cannot work here

`docs/0017` established world fingerprinting: look at the world before acting,
compare after a crash. Git has `HEAD`; the filesystem has a content hash.

**A remote API has neither.** The world in question is somebody else's server,
and we cannot see it without its cooperation. There is no observation to make.

So the question `docs/0017` answers — *did it land?* — is not merely hard here.
It is the **wrong question**. The right one is:

> Is it safe to send this again?

If the call carries a stable idempotency key, the answer is yes *regardless of
what happened*, because a compliant server collapses the retry into the
original effect. That is Stripe's mechanism, and it is the only general way to
make a remote non-idempotent effect replay-safe.

## 2. A fourth verdict

The probe protocol gains `SAFE_TO_RETRY`:

| Verdict | Meaning | Gate |
|---|---|---|
| `LANDED` | the effect happened | SUBSTITUTE |
| `DID_NOT_LAND` | it provably did not | EXECUTE |
| **`SAFE_TO_RETRY`** | **unknown, and it does not matter** | **EXECUTE** |
| `INCONCLUSIVE` | unknown, and it does matter | BLOCK |

`SAFE_TO_RETRY` is the interesting one: it is the first verdict that resolves
ambiguity **without resolving the uncertainty.** We still do not know whether
the charge went through. We know that asking again cannot make it two.

## 3. The mechanism, and its precondition

A probe that only observes cannot help here, so this one depends on something
having been done *before* the crash: the key must have gone out with the
original request.

**Seam C stamps it.** That is a deliberate widening of Seam C's role — from
"substitution channel" (`docs/0018` §2) to "substitution channel and the one
place a call can be modified before it executes". It stays narrow: the key is
computed by the kernel and merely written onto the call. Seam C still decides
nothing.

Without Seam C, nothing stamps, the probe declines, and `EXTERNAL` effects stay
fail-closed. That is the same graceful degradation as `docs/0008` §3.5 — losing
a seam costs capability, never correctness.

A key the *model* supplied is equally good. What the probe refuses is a request
that carried **no** key, or a **different** one.

## 4. The circularity bug

The first implementation derived the key from the call's `intent_hash`, which
hashes all arguments — including the key field. So:

```
stamp the key  ->  the args change  ->  the intent_hash changes  ->
the key we would compute on retry differs  ->  probe declines
```

Self-defeating, and it presented as a plain assertion failure rather than
anything obviously circular. The fix: derive the key from the arguments
**excluding the key field itself**.

The invariant was wrong too, and correcting it simplified things. It is not
*"the key equals what we would compute now"* but **"the same key went out both
times."** That accommodates a model-supplied key, needs no agreement about how
keys are generated, and is exactly what the remote actually requires.

## 5. The proof

`test_retry_after_a_crash_charges_once` runs against a **real HTTP server that
really deduplicates** — not a mock, not a stub:

```
run 1   gate admits -> POST -> ch_1 created -> crash before commit
run 2   probe: SAFE_TO_RETRY -> gate admits -> POST again
assert  one charge exists; the retry really was sent
```

`_Charges.attempts == 2` and `len(_Charges.charges) == 1`. The retry genuinely
went out and the customer was charged once.

Its companion, `test_without_a_key_the_same_scenario_charges_twice`, sends the
same pair unkeyed and gets two charges. That is what the gate is protecting
against, demonstrated rather than asserted.

## 6. Mutation check

Per the rule in `docs/0019` §4, applied to the new code. Two mutations.

**Mutation 1 — disable the "no key went out" check.** *Survived.* Not a test
gap: the check is **redundant**, because the subsequent key-match comparison
already rejects an empty recorded key. It stays for clarity and as a guard
against a future change, but it carries no weight today.

**Mutation 2 — disable the "same key must go out again" check.** *Caught*, by
`test_a_changed_key_means_inconclusive`.

Worth recording the general lesson: **a surviving mutant means either a test
gap or dead code.** Both are worth knowing, and only investigating tells you
which. Reporting "mutation testing passed" without looking would have missed
both readings.

## 7. What this does not give you

- **The original response.** A deduped retry returns the server's recorded
  response, which is usually what you want — but the agent sees the retry's
  return value, not the pre-crash one.
- **Anything for APIs without idempotency support.** `send_email` with no key
  field stays fail-closed, correctly. There is genuinely no safe retry.
- **Protection against a non-compliant server.** We trust the remote to honour
  the key. If it does not, the guarantee is void and nothing local can detect
  that.
- **Coverage in the nine-point suite.** `EXTERNAL` is tested here, not there.
  The suite still covers git and filesystem only.

## 8. Consequences

- Every effect class now has a defined recovery path:
  `PURE_READ` / `IDEMPOTENT_WRITE` re-execute; `NON_IDEMPOTENT_WRITE` probes
  the world; `EXTERNAL` retries under a key or blocks; `DESTRUCTIVE` always
  escalates.
- `docs/0012` §5.1 → document `idempotency_key` in the matrix schema.
- `docs/0008` §6.3 → the effect-class table gains a recovery column.
- Next: **M5** (cost ledger), or extend the nine-point suite to `EXTERNAL`.
