---
Number:        0018
Title:         M2b Results — Substitution, and the Correctness Story Closed
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0016, 0017
---

# 0018 — M2b Results

The last step. The agent now receives a *result* where it used to receive a
rejection.

**Run:** 2026-09-08 · `openhands-sdk 1.45.0` · zero cost.
Code: `agentctl/adapters/openhands/{seam_c,handoff}.py`.
Acceptance: `experiments/0003-m2b-substitute/`. **76 tests passing.**

---

## 1. The arc, in one table

Same crash, same scenario, three milestones:

| | M2a | M4 | **M2b** |
|---|---|---|---|
| Duplicate effect | none | none | none |
| Ledger state | `BLOCKED` | `COMMITTED` | `COMMITTED` |
| Probe verdict | — | `LANDED` | `LANDED` |
| Human needed | **yes** | no | no |
| Agent receives | rejection | rejection | **observation** |

Each milestone was correct. Only the last one is *invisible* to the agent,
which was the point of `docs/0008` §6: the work should continue as though the
crash never happened.

## 2. The design constraint that shaped it

`ToolExecutor.__call__(action, conversation)` receives the **action**, and
`Action` has no fields — `tool_call_id` lives only on the `ActionEvent`, which
Seam B sees and Seam C does not.

So the seam that can *identify* a call is not the seam that can *substitute*
for it. That forces a clarification worth stating plainly, and it simplifies
the design rather than complicating it:

> **Seam C is not a second gate.** Seam B makes every decision. Seam C exists
> only to honour the one verdict Seam B cannot deliver.

The consequence: a lookup miss at Seam C means "Seam B said EXECUTE", so
passing through is correct — Seam B would already have blocked anything
dangerous. Seam C needs no policy, no classifier, and no ledger access. It is a
lookup, a branch, and the inner call.

`SubstitutionHandoff` carries the decision between them: keyed on object
identity, with a content-fingerprint fallback so a mismatch degrades to a
*missed* substitution rather than a wrong one, and consumed exactly once so a
genuinely repeated call is not silently short-circuited twice.

## 3. The real gap M2b exposed

The first run failed, and the reason matters more than the fix.

**A probe-reconciled effect has no observation to substitute.** The crash
happened *before* the observation was recorded, so the ledger knows the effect
landed and holds no result. `rec.observation` is NULL. There is nothing to
revive.

This is inherent to fingerprint reconciliation (`docs/0017` §2): a probe proves
an effect *happened*; it cannot recover what the effect *returned*.

Three options, and the choice matters:

| Option | Verdict |
|---|---|
| Re-run the tool to get a result | **No.** That is the duplicate we exist to prevent. |
| Synthesize a plausible result | **No.** Inventing output the agent will reason over is worse than admitting ignorance. |
| Say plainly what is known | **Yes.** |

So the agent gets an observation that states the truth: *this already completed
before an interruption; the effect is confirmed; its original output was not
recorded and is unavailable; it was not run again.*

That is honest, actionable, and lets the loop continue. When a real observation
*was* recorded — the ordinary crash-after-commit case — it is revived verbatim
and none of this applies.

## 4. Two bugs

**C1 — `Observation.content` is `list[TextContent]`, not `str`.** Assigning a
bare string validated at construction and then produced 326 validation errors
when the message was assembled several steps later. A `ConversationErrorEvent`,
far from the cause.

*Generalisation:* pydantic validating on assignment does not mean the value is
usable. The failure surfaced at message-assembly time, in a different
component, with no reference to the field that caused it.

**C2 — the acceptance metric was too crude.** It counted any event kind
containing `"Error"` as a rejection, so a run-level `ConversationErrorEvent`
was scored as a failed substitution. The metric now distinguishes tool
rejections from run errors and reports both.

*Generalisation:* the same rule as `docs/0012` §6. A test that cannot tell two
failures apart will eventually attribute one to the other — and in this case it
was hiding a real bug behind a plausible-looking one.

## 5. What is now true

The correctness story from `docs/0008` §6 is complete for local effects:

- No duplicate side effect at the tested crash point.
- Ambiguity resolves automatically where the world can be interrogated.
- The agent resumes with a result, not a refusal.
- Every step degrades safely: no Seam C → block; no probe → block; broken gate
  → block.

## 6. What is still not true

- **`EXTERNAL` effects have no probe.** HTTP POSTs, emails, webhooks still fail
  closed. The idempotency-key probe is unwritten.
- **One crash point, not nine.** `docs/0012` §6 still wants the parametrised
  suite. This is now the largest gap in the correctness claim.
- **Built-in tools are not gated by default.** `install()` takes an explicit
  map; wiring the SDK's built-ins is untested.
- **Single process.** Fencing is implemented and tested, but multi-host is not
  exercised.

## 7. Consequences

- `docs/0012` §4 → record that Seam C is a substitution channel, not a gate,
  and document the handoff.
- `docs/0012` §6 → add the "distinguish failures" rule from §4 above.
- `docs/0008` §3.5 → the verdict split is now implemented as described.
- Next: **the nine-point chaos suite** (closes the correctness claim), or
  **M5** (cost ledger, which `docs/0013` §8 argues you would feel sooner).

## 8. Method note

Every milestone so far has been finished by a bug that only execution could
find: cp1252 in M0, the lease deadlock in M2a, CRLF in M4, and content-shape
here. None were visible by reading. The chaos harness has paid for itself four
times.
