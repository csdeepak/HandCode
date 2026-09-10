---
Number:        0023
Title:         The Real Provider Run — and the Bug Only It Could Find
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0014, 0021, 0022
---

# 0023 — The Real Provider Run

The first run against a real provider found a **real duplicate side effect**,
invalidated an M0 answer, and produced the most important correction in the
project.

**Run:** 2026-09-08 · OpenRouter free-tier models · ~11k tokens · $0.00 billed.
Code: `experiments/0007-real-provider/`. **175 tests passing.**

---

## 1. Why mocks were not enough

`docs/0022` §3 listed it as the last honest gap: *"Never run against a real
provider. The first live API key will find something."*

It found two things, and one of them was a duplicated `git commit`.

The general lesson is worth stating plainly: **a mock agrees with whatever you
assumed.** Every assumption baked into the mock is invisible until something
real disagrees.

## 2. Model selection is itself a finding

Of 436 models on OpenRouter, **18 are free *and* support tool calling.** Of
four probed, three worked and one returned a live `RateLimitError` — a genuine
429 in the wild, unprompted.

The three that worked returned three completely different id formats:

```
call-9c88d5f6-a43c-489b-bf66-05196a5fcfb6   nvidia
call_d381b5bbac5f43d7af9dc5a2                nex-agi
chatcmpl-tool-a0e0c69423d4cdfc               openrouter/free
```

That variance is not cosmetic. It is the next section.

## 3. First bug — the model chose where the effect landed

`CommitAction` exposed a `cwd` field. The mock only ever filled *required*
fields, so it stayed at its default. A real model filled it with `"."` — a
plausible, wrong value — and the commit landed in whatever directory the
process happened to be in.

**It committed twice into this project's own repository.** Two empty commits,
removed with a soft reset; no file changes were involved.

Two fixes, and the second is the general one:

1. `cwd` is gone from the action schema. Where an effect lands is
   configuration.
2. **`GitProbe` now prefers its configured `repo_root` over anything in the
   arguments.** A model that can choose the path can choose the blast radius —
   and worse, the probe would then faithfully fingerprint the wrong world and
   report confidently about it.

> **Rule: an effect's *location* must never be model-supplied when a probe's
> fingerprint location derives from the same field.** Trusted configuration
> wins; arguments are a fallback, never an override.

## 4. Second bug — `tool_call_id` is not stable, and M0 said it was

The rerun produced a genuine duplicate:

```
ledger: INTENT     id=call-c939dc5f-6473-47e7-8567-bad4f94858c5   (nemotron)
ledger: COMMITTED  id=call_03ee2666c2834d6b8944488a               (nex-agi)
commits: 2 -> 3
```

Two runs, two models from the same pool, two ids for the identical call. The
ledger is keyed on `tool_call_id`, so the lookup missed, the gate saw a first
sighting, and the commit repeated.

### This invalidates `docs/0009` Q2

M0 asked *"is `tool_call_id` stable across crash and resume?"* and answered
**CONFIRMED** (`docs/0014`). That answer was an artifact: **the mock returned a
fixed id on every call.** The test could not have failed.

A real multi-model pool breaks it immediately. Q2 is corrected to:

> **`tool_call_id` is minted by the model. It is stable only when the same
> model answers the same question. Nothing about a pool, a retry, or a fallback
> guarantees that.**

This is the same shape as the M0 lesson in `docs/0014` §5 — a harness that
agrees with the hypothesis proves nothing — arriving a second time, in the
component the whole project rests on.

### The fix: key on something we own

`intent_hash` — tool name plus canonicalised arguments — is computed by us, not
supplied by a model. Identical logical effect, identical hash, whoever asked.

Before treating a call as a first sighting, the gate now asks whether this
exact effect is already on record under a different id, scoped to the
conversation. `LedgerStore.find_by_intent`.

**Deliberately conservative.** A genuine repeat of an identical call also
matches and is treated as the same effect. For a non-idempotent effect that is
the safe direction, and the probe or a human resolves it. Only dangerous
classes pay for the extra lookup; reads skip it.

Covered by five tests, including
`test_the_same_effect_under_a_different_id_is_not_a_first_sighting`, which
reproduces the real scenario deterministically rather than relying on a pool
shuffle to land the right way.

## 5. The passing run

```
commits_before          1
commits_after_crash     2
commits_after_resume    2      <- no duplicate
hook_calls              3
records_with_trace_id   3/3
real tokens             11,284 prompt + 284 completion
records_with_cost       0
```

A real model, real tokens, a real crash, and one commit.

**One honest caveat:** the shuffle sent both runs to `nex-free`, so this
particular pass did not exercise the cross-model id case. The unit tests do,
deterministically. A single passing live run is evidence, not proof — which is
precisely why it took three attempts to get one.

## 6. Q18 in the wild

Every record reported `cost: 0.0` against a real provider. These are free-tier
models, so it may well be true — **and LiteLLM offers no way to tell that apart
from an endpoint it cannot price.**

Exactly the hazard `docs/0021` §5 predicted, now observed outside the mock. The
cost ledger's `priced` column earns its place: `agentctl cost` reports
`unknown` here rather than a confident `$0.00`.

## 7. What this run does not prove

- **One provider, one key.** OpenRouter only; no Anthropic, OpenAI or Gemini.
  The `/v1/messages` bypass (`#27518`) remains untested against a real
  Anthropic endpoint.
- **Free tier only.** No paid model, so no meaningful pricing coverage data.
- **One crash point.** The nine-point suite is still mock-driven.
- **No real `EXTERNAL` effect.** No real HTTP POST was made; the idempotency
  probe is proven against a local dedup server only.

## 8. Not added to `verify.py`

`verify.py` stays free and key-free. The real-provider run is opt-in:

```bash
python experiments/0007-real-provider/run_real.py     # needs OPENROUTER_API_KEY
```

It also degrades to `SKIPPED` rather than failing when no key is present.

## 9. Consequences

- `docs/0009` Q2 → **CORRECTED.** The M0 answer was a mock artifact.
- `docs/0008` §6.2 → the ledger's primary key needs the intent-hash fallback
  documented; `tool_call_id` alone is insufficient.
- `docs/0012` §5.1 → record that effect location must not be model-supplied.
- `docs/0014` → its Q2 finding should carry a pointer here.
- Next: **M7** (policy compiler), or a run against a second provider family to
  test the `/v1/messages` path.
