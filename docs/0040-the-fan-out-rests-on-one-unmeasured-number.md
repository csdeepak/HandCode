---
Number:        0040
Title:         The Fan-Out Rests on One Unmeasured Number
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-21
Supersedes:    —
Superseded-by: —
Depends-on:    0038, 0039
---

# 0040 — The Fan-Out Rests on One Unmeasured Number

`research/phase-10-5` §6.3 concluded that pinning read-only scouts to
different providers yields **×4.33 more recon tasks per day**. Research
documents are frozen on arrival (`CONVENTIONS.md`), so this corrects it here.

Two inputs changed after it was written:

1. **Gemini is one quota, not six.** All six keys are in one Google project,
   and Google bills per project (`docs/0039` §7, thirteenth entry).
2. **Groq cannot serve a scout at all.** §6.3 computed 579 tokens of
   conversation headroom for a read-only worker and called it *"better and
   still useless"* — a scout's first request is 3,405. That was in the
   research; it was not carried into the ×4.33 row, which assumed three
   working legs.

---

## 1. The answer

**There is no single number.** The fan-out's throughput now depends on one
quantity nobody has measured — Gemini's free-tier requests per day — and
across its plausible range the result runs from *worse than a single agent*
to the original ×4.33.

```
tasks/day = min( 300/3 ,  gemini_rpd/7 ,  6 × mistral_rpd/7 )
              OpenRouter    one quota       six quotas
```

| gemini RPD | tasks/day | versus single agent (23.1) |
|---:|---:|---|
| 50 | 7.1 | **×0.31 — worse than doing nothing** |
| 100 | 14.3 | **×0.62 — worse** |
| **162** | **23.1** | **break-even** |
| 200 | 28.6 | ×1.24 |
| 250 | 35.7 | ×1.55 |
| 500 | 71.4 | ×3.09 |
| **700** | **100.0** | **×4.33 — OpenRouter binds again** |
| 1,500 | 100.0 | ×4.33 (no further gain) |

**Two thresholds are the whole result:**

- **Gemini RPD ≥ 162** — below this, the fan-out is *worse than not doing it*.
- **Gemini RPD ≥ 700** — above this, Gemini stops binding, OpenRouter binds,
  and the original ×4.33 is recovered in full.

Between them the gain scales linearly with a number that is not published.

---

## 2. Why the shape changed

With Groq unusable the corpus splits two ways instead of three, so each leg
carries six files instead of four — and a scout's cost is linear in files
because every request resends the history:

| | requests | tokens | vs single |
|---|---|---|---|
| single agent | 13 | 285,697 | — |
| 3 scouts (as published) | 18 | 161,142 | ×1.38 req, ×0.56 tok |
| **2 scouts (Groq removed)** | **17** | **193,817** | **×1.31 req, ×0.68 tok** |

The token advantage survives and shrinks: **32% fewer tokens, not 44%.** That
part of §6.3 stands — scouts return summaries instead of dragging file bodies
into a context that carries them forever.

What does not survive is the throughput claim, because throughput is set by
whichever pool runs out first, and the fan-out moved 14 of 17 requests onto
legs whose limits are unknown.

---

## 3. Why Gemini binds and Mistral probably does not

Mistral has **six real quotas**; its per-key limit would have to be under ~39
RPD before it bound ahead of OpenRouter. Gemini has **one**, so it binds at
anything under 700.

That asymmetry is the whole practical lesson of `docs/0039`'s thirteenth
entry, in arithmetic rather than prose: *six keys behind one quota are not six
keys.* The fan-out design implicitly bet on breadth, and one of its three legs
turned out to be a single allowance wearing six labels.

**A cheaper design follows directly.** Two scouts both on *Mistral*, using two
of its six independent quotas, has no single-quota leg at all and needs
`mistral_rpd ≥ 233` to reach the same ceiling. Whether that is better than one
Gemini leg depends on two numbers, neither of which is measured. It is named
here as the alternative to evaluate first, not as a recommendation.

---

## 4. What would close this

One lookup, and it is free: **[aistudio.google.com/rate-limit](https://aistudio.google.com/rate-limit)**,
RPD for `gemini-3.6-flash` on the free tier. It needs a Google sign-in, which
is why it is not recorded here.

Second, and nearly free: Mistral's per-key RPD from the console.

Until then the honest statement about cross-provider fan-out is **"between
×0.31 and ×4.33, and which end depends on a number we have not looked up"** —
not ×4.33.

---

## 5. What this does not change

The read-only subagent itself is unaffected. Its value was never throughput:
it is that a subagent which cannot produce an effect needs none of the four
single-writer invariants (`docs/0038` §4.2), and that argument does not touch
quotas.

`docs/0038` §4's SKIP for *writing* multi-agent also stands, and stands on
safety rather than budget — which the checkpoint-2 audit said was the stronger
half to lead with, and which this document is another reason to believe. The
budget half has now been re-derived twice and moved by an order of magnitude
both times.
