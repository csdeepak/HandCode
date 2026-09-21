---
Number:        0041
Title:         The First Live Validation
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-21
Supersedes:    —
Superseded-by: —
Depends-on:    0034, 0039
---

# 0041 — The First Live Validation

The owner's objection, in his words: *"we are building a lot of micro features
without even looking into working."* He was right. `verify.py` proves the
correctness core against a **mock** provider; nothing had run the harness end
to end against real APIs on a real workspace.

So it was run. A git repo, a real defect, a real task, through the pool.

---

## 1. It works

```python
def divide(a, b):
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

Plus a matching test. **3 passed**, the existing tests still passing.

| | |
|---|---|
| `doctor` | flagged Groq headroom and OpenRouter quota before spending |
| proxy | all four source groups served tool calls |
| ledger | 14 effects: 6 `PURE_READ`, 2 `IDEMPOTENT_WRITE`, 6 `EXTERNAL` |
| gate | 11 EXECUTE, 1 BLOCK — and the blocks were right |

The two blocked effects were failed `bash` commands whose outcome the gate
could not determine. Fail-closed, working.

**That is the claim the badge could not make.** Everything else in this
repository's suite runs against a mock.

---

## 2. Three defects, all invisible to 637 tests

### 2.1 One dead deployment ended the whole run

Cerebras returned 402 *"Payment required"* and the run died. `docs/0034` §7
predicted this word for word — *"a 402 that litellm does not treat as
retryable"* — and `--verify` existed to exclude such keys. It was **not the
default**, so `agentctl proxy` generated a config known to contain deployments
that cannot serve.

**Fixed by making verification the default**, with `--no-verify` for speed and
a printed warning when it is used. Generating a knowingly-broken pool is not a
default worth having.

### 2.2 The pool did not route around it

litellm gives `AuthenticationError` and `BadRequestError` **zero** retries.
That is correct for one endpoint and wrong for a pool: here the deployments
are interchangeable, so a 401/402 means *that key* is bad and a 404 means
*that model id* is gone. Neither says anything about the request, and the next
deployment would have served it.

The generated config now carries a `retry_policy` for deployment-shaped errors
and an `allowed_fails_policy` that cools a bad key down on the first failure
rather than the second.

**Measured, 12 requests through a pool containing six dead deployments:**

| | result |
|---|---|
| before | died on the first hit |
| retry policy only | 10/12 |
| retry policy + `--verify` default | **12/12** |

The retry policy alone is not enough, and the measurement says why: Cerebras
returns a generic `APIError`, which is not one of the six classes `RetryPolicy`
covers. **Verification is the fix; the retry policy is defence in depth for the
transient case.** Recorded in that order deliberately — the opposite reading
would put confidence in the weaker mechanism.

### 2.3 `resolve` was unusable with Gemini

The blocked effect's id:

```
call_2524396__thought__EpgBCpUBAWkUfRPnWX0Lt8BPLrlMw+a8VH8OX4n+CcTixZNY7aM15rYX...
```

Over 300 characters. Gemini smuggles a **thought signature** through
`tool_call_id` (`research/phase-10-3` V4), and the ledger keys on that id — so
`agentctl resolve` was asking a human to retype 300 characters of base64 to
answer a blocked effect.

That is the human half of fail-closed, and `docs/0013` §3 calls it the thing
without which the design is *"correct and unusable"*. It had become exactly
that — against one provider, and only against that provider.

Ids now print short and are accepted by prefix, the way git takes a SHA. An
ambiguous prefix is refused with its candidates rather than guessed at: this is
the command that records an effect as having happened.

One detail worth keeping. The printed hint carries the **bare prefix**, not the
`...`-marked display form. A suggested command you have to edit before it works
is worse than no suggestion.

---

## 3. What this says about the method

All three were invisible to 637 passing tests and ten `verify.py` checks, for
one reason: **they are properties of the boundary with a real provider**, and
everything else in this repository mocks that boundary.

`docs/0039` §3 tabulated what found each of fifteen defects, and noted the
suite found none of them on the machine that wrote them. This adds a row:

| Found by | Defects |
|---|---|
| Running the whole thing against real APIs, once | 2.1, 2.2, 2.3 |

The cost was about forty requests of free-tier quota.

**The owner's objection was the correct engineering call**, and it is worth
recording as a rule rather than an anecdote:

> A feature that has never been run against the real boundary is not done,
> however well it is tested.

Three of the last four features shipped in that state.
