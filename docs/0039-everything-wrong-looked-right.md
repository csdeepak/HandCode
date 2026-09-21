---
Number:        0039
Title:         Everything That Was Wrong Looked Right
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-21
Supersedes:    —
Superseded-by: —
Depends-on:    0024, 0034, 0038
---

# 0039 — Everything That Was Wrong Looked Right

Thirteen commits, `2f534d3` through `32c5546`. Eleven defects. **The test
suite found none of them**, and it was green before, during and after — 502
tests at the start, 605 at the end, passing throughout.

That is the finding. The individual fixes are recorded in their commit
messages and in `docs/0038` §9; this document exists for the pattern they
share, because the pattern is more useful than any of them.

---

## 1. The eleven

Every one was **confidently wrong**. Not crashing, not empty, not obviously
broken — each produced a plausible answer that a reasonable person would have
believed.

| # | What it claimed | What was true |
|---|---|---|
| 1 | `git probe: the effect already landed` | The commit never ran. A *sibling* in the same batch had moved HEAD |
| 2 | `0038` §2: Claude-Code features "already present" | Present in a library `agentctl` never imported. `grep` returned zero |
| 3 | `proxy_config.yaml`: 42 deployments | Six live Gemini accounts were held and absent. The config was stale |
| 4 | `openrouter no-credit` | One of six keys was daily-capped. Eighteen deployments dropped |
| 5 | `FAILOVER READY — 31 accounts` | Seven could not serve. Directly above a panel answering UNKNOWN |
| 6 | A subagent's report on `alpha` | It had read `bravo`'s file. Different workspace entirely |
| 7 | Seam C gating three tools | A subagent had re-registered them plain. Log warning only |
| 8 | A subagent's answer | Its own prompt, handed back |
| 9 | `tiering:` compiled and validated | Read by nothing, for 17 commits |
| 10 | A green test for the workspace fix | Compared against a value an earlier test had leaked |
| 11 | `deepseek-chat-v3.1:free` in the registry | Gone from the catalogue; 404 on a call |

All eleven were found this day. **Six pre-existed it** — #1, #3, #4, #5, #9,
#11, one of them true for seventeen commits — and **five were introduced by
it**: #2, #6, #7, #8 and #10 are all defects in work written the same day they
were found.

That split matters more than the total. Half of a day's output was wrong on
arrival, and the half that was wrong was not the rushed half — #6 and #7 are
in a module whose docstring argues carefully for its own safety, and #10 is a
test written specifically to catch #6.

---

## 2. Why they share a shape

A crash is self-reporting. A wrong answer is not, and **every mechanism in
this list had a legitimate reason to return the answer it returned.**

The git probe's rule is sound: *HEAD moved, and there is a single writer, so
it was our commit.* Its own comment says so. The premise simply stopped being
true inside a batch, and nothing told the probe that.

`check_inference`'s docstring argues the case correctly — *"the tier is an
account-level property"* — and then draws the opposite conclusion from it. One
sentence, two clauses, and the second contradicts the first.

`register_tool` replaces a duplicate and logs a warning. The SDK's own source
carries a `TODO` saying it should raise. Nobody reads a warning in a passing
run.

This is `docs/0034`'s subject — four ways a check can lie — arriving four more
times, and `docs/0024`'s — the right outcome by the wrong route — arriving
twice, once in the product and once in a test written to catch it.

---

## 3. What actually found them

This is the part worth keeping.

| Found by | Defects |
|---|---|
| Reading source to answer a specific question | 1, 9 |
| A `grep` for callers | 2, 9 |
| Running the thing for real | 3, 8, 11 |
| A measurement against a live provider | 3, 4 |
| A concurrency experiment against a local stub | 6, 7 |
| An adversarial review of work already accepted | 2, 5 |
| Distrusting a green test | 10 |
| An unrelated edit changing an unrelated number | 4 |
| **The 605-test suite** | **none** |

The suite is not failing at its job. It is doing a different job: it pins
behaviour that someone has already understood. **Not one of these eleven was
understood before it was found**, so there was nothing to pin.

#4 deserves its own note. It was found because an edit to a *model registry*
changed the *deployment count* — 48 to 30 — and that number had no business
moving. Nobody was looking for it. The only reason it surfaced is that the
count was printed where a human would see it.

---

## 4. The rule

**A component that returns a verdict must be able to say it does not know,
and the paths that produce "yes" must be outnumbered by the paths that
produce "I cannot tell".**

Applied to the eleven:

- The git probe now checks its own premise before trusting a world-state
  verdict, and downgrades `LANDED` to `INCONCLUSIVE` when a sibling committed
  inside the window (`gate.py::_sole_writer`).
- `check_inference` asks every account before condemning a provider, and where
  they disagree the most *encouraging* verdict wins — a provider with one
  capped key works again tomorrow.
- Panel 1 has **no code path returning anything but `UNKNOWN`**, and a
  parametrised test over every pool shape asserts it.
- `tiering` is **refused at compile time** rather than compiled into nothing.
  M7's own title is that a policy failing open is worse than no policy; a
  block that validates cleanly reads like protection you do not have.
- `_final_text` returns a marker rather than an empty string, so "found
  nothing" is distinguishable from "never ran".

The corollary, learned from #10: **a test that asserts a green outcome must be
shown to fail without the fix.** That one compared against the ambient value
and passed because an earlier test in the same file had leaked the same path.
It now sets a known sentinel, and removing the fix makes it fail —
mutation-checked, per `docs/0019`.

---

## 5. What is still believed on trust

Stated because a document about confident wrongness that ended with a
confident summary would be its own example.

- **Groq's metering mechanism.** That the 8,000 TPM ceiling counts
  `prompt + max_tokens` is T3-sourced. The arithmetic is measured; the
  mechanism is inferred. `doctor` says so in its own output.
- **Gemini's free-tier limits are no longer published.** Google's page now
  punts to AI Studio. The cross-provider fan-out arithmetic in
  `research/phase-10-5` leans on that number, and it is currently a gap.
- **`escalation()` has no callers either**, and was left in place. It is a
  larger user-facing surface than `tiering` and removing it needs a decision
  about what the policy DSL promises. Recorded here so it is not forgotten a
  second time.
- **`service_id=` is silently discarded** in both `runner.py` and
  `subagent.py` — `LLM` has `extra="ignore"` and the field is `usage_id`. Two
  call sites believe they are labelling telemetry and are not. Inert, not
  harmful, unfixed.
- **Subagent concurrency is unproven.** The two globals that raced are fixed,
  and three further candidates were refuted by experiment, but no orchestrator
  exists yet and nothing exercises the concurrent path.

---

## 6. What changed

Correctness: the batch-fingerprint fix (`c8113f3`), `tool_concurrency_limit`
pinned with a `raise` rather than an `assert`, the account-level provider
probe (`093fb26`), and the two subagent globals (`b061b05`).

Capability: source groups and `agentctl models` (`b040b72`), read-only
subagents (`2ab2a74`), the plugin broker (`6b95a57`), `dash` reading the live
pool, and the only honest quota number any provider exposes.

Subtraction: `tiering`, deleted by Phase 10.4 (`099edf7`) — the phase
`docs/0037` scoped, nobody ran, and two audits recorded as dropped.

`0038` remains **DRAFT** and its §9 records the two audits that corrected it.
It should not be accepted until someone other than its author reads it.

---

## 7. Postscript — the twelfth, found after this was accepted

*Added 2026-09-21, after this document was committed as ACCEPTED at `610f347`.
`CONVENTIONS.md` rule 4 says an accepted document is not edited in place, and
this appends rather than revises for that reason: §1–§6 stand exactly as they
were written, and everything below happened afterwards. A document arguing
against confident revision should not quietly revise itself.*

Within the hour of `610f347` being pushed, CI went red on all three Linux jobs.

| # | What it claimed | What was true |
|---|---|---|
| 12 | `_FIXED_PREFIX_TOKENS = 3593`, measured | 3,593 on Windows, **3,591 on Linux**. Same commit, same SDK, same encoding |

It is the same shape as the other eleven — a measured constant, correct where
it was measured, asserted everywhere. And **the cause is still not
identified**: neither the system prompt nor the tool schemas contain an OS
string or a path, and the Linux side is not reproducible from the machine that
wrote it. That is recorded as unexplained rather than guessed at, which is §4's
rule applied to this document's own subject matter.

### What it changes about §3

§3 says the suite found none of the eleven. This one **the suite did catch** —
and the row it belongs in is the useful part:

| Found by | Defects |
|---|---|
| The suite, **run on a machine that did not write the code** | 12 |

So the claim in §3 was true and slightly too flattering to itself. The precise
version: *the suite found none of them **on the machine where they were
written***. Every local run was green. The badge is not decoration; it is the
only part of the arrangement that tested a different environment, and it
earned its place inside an hour.

### The sub-lesson

The tripwire was written well. Its docstring said *"do not widen this test
instead"* — correct, and aimed at drift over **time**, which is what a stale
constant usually means. It did not anticipate drift across **environment**,
where no single constant satisfies both platforms and updating it only moves
the failure to the other one.

**A guard written against one axis of change will be silent, or wrong, on
another.** The repair was to widen the band to 32 tokens — chosen against the
~130 that gaining or losing one tool would move, so it still catches what it
was built for — and to add a second test asserting the *conclusion* rather
than the constant: that measured headroom still lands where "turn 2 will 413"
is the right thing to tell the user. A tolerance band is only honest if the
thing it protects is insensitive across it.

Fixed in `c1ed32f`. 606 tests, seven CI jobs green.
