---
Number:        0036
Title:         A Timeout That Did Not Time Out
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-15
Supersedes:    —
Superseded-by: —
Depends-on:    0025, 0035
---

# 0036 — A Timeout That Did Not Time Out

A live demonstration: a real bug, a real fix, tests red to green. It also
produced three defects, all in this codebase, none caught by 497 tests.

**502 tests passing** (was 497). Fixes in `runtime/tools.py`, `runtime/runner.py`.

---

## 1. What the demo showed

`cart.py` had a discount bug — `apply_discount(100, 10)` returned `-900`.

```
3 failed, 1 passed      ->      4 passed in 0.03s
```

```diff
 def apply_discount(total, percent):
-    return total - (total * percent)
+    return max(0, total - (total * percent / 100))
```

Both halves of the bug in one line, on a free-tier model, for $0.00, with a
94.93% cache hit. The ledger recorded one `PURE_READ` and one
`IDEMPOTENT_WRITE`, both `COMMITTED`, nothing waiting.

## 2. The timeout was advisory

The first attempt hung. The model wrote `cd / && find . -name "test_cart.py"`
— a scan of the entire filesystem — and the executor's 120-second limit never
fired. Reproduced exactly:

```
sleep 60 | cat      limit 3s      returned after 60.1 seconds
```

`subprocess.run(timeout=...)` kills its **direct child** and then drains the
pipes. A grandchild still holds the write end, so the drain blocks until that
grandchild exits on its own. The shell was dead and the call was still waiting.

So the one safety property the executor advertised did not hold: a single bad
command could hold the agent open for as long as its grandchildren lived,
without bound. That is worse than a slow tool — an agent that never returns
also never reaches the ledger, so the effect stays `INTENT` and the workspace
stays locked (§4).

Now the process **tree** is killed — `taskkill /F /T` on Windows, a process
group signal elsewhere — and the post-kill drain is itself bounded:

```
grandchild holds the pipe    13.2s   exit=124 'timed out after 3s and was killed'
plain long sleep              3.2s   exit=124
normal fast command           0.0s   exit=0 'hello'
```

**Bounded, not instant.** Some git-bash grandchildren survive `taskkill /T`, so
the contract is `limit + 10s grace` and the test asserts that rather than
something prettier. Losing the tail of the output is a far smaller loss than an
agent that never returns.

## 3. The proxy instructions were wrong

`agentctl proxy` prints *"no key needed client-side"*, which is the right
design — the credentials live in the proxy. It was also false: the runner
passed `api_key=None`, and litellm answered

> *Missing credentials. Please pass an `api_key` ... or set the
> `OPENAI_API_KEY` environment variable.*

which sends you hunting for a key you deliberately do not have. A placeholder
is now supplied whenever a `base_url` is set and no key is found. The genuinely
missing-key case still refuses, and a test covers both.

## 4. A hung run holds its ledger open

While the first attempt was stuck, its workspace could not be cleaned:

```
rm: cannot remove '.../ledger.db': Device or resource busy
```

SQLite holds the file for the life of the process, and the process was the one
that would not return. §2 removes the cause rather than the symptom: a bounded
tool call means a bounded lease. **Not fixed:** there is still no way to
release a lease held by a process that is alive but wedged. `takeover=True`
handles a *dead* holder (`docs/0016` §3); a live-but-stuck one has no
equivalent, and `agentctl run --resume` would refuse.

## 5. What this says, again

Three defects in one demonstration, all in this repository, none surfaced by
497 tests, CI on two operating systems, or ten verification checks.

The pattern from `docs/0031` §10 and `docs/0035` §5 holds a third time. The
executor's tests drove it with commands that finish: `echo`, `ls`, a heredoc.
None spawned a grandchild that outlives its parent, so the drain never blocked
and the timeout was never actually exercised. **A suite built from the inside
tests the shapes you thought of.**

The correction is not "write more tests". It is that a *property* worth
claiming — "this call is bounded" — needs a test that attacks the property,
not one that exercises the happy path and infers the rest.

## 6. Consequences

- `docs/0012` §6 → new rule: a timeout is not enforced until something has
  tried to outlive it. Test the adversarial shape, not the common one.
- `docs/0025` → `execute_bash` now documents `limit + grace`, not `limit`.
- **Open:** no way to release a lease from a live but wedged process.
