---
Number:        0017
Title:         M4 Results — Reconciliation Probes
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0012, 0016
---

# 0017 — M4 Results

M2a made dangerous effects fail closed. Correct, but every ambiguous
`git commit` needed a human. M4 asks the world instead.

**Run:** 2026-09-08 · `openhands-sdk 1.45.0` · zero cost.
Code: `agentctl/kernel/reconcile/`. Acceptance: `experiments/0002-m4-probe/`.

---

## 1. The result

```
                    M2a (no probe)        M4 (git probe)
commits after crash        2                    2
commits after resume       2  no duplicate      2  no duplicate
ledger state          BLOCKED               COMMITTED
probe verdict              —                 LANDED
human needed             YES                   NO
```

Both are *correct*. Only one is usable. **65 tests passing.**

## 2. The design change

`docs/0012` §3.3 specified injecting the intent hash into the effect itself —
a git trailer — so the probe could find its own marker later. That requires
mutating the command before execution, which only Seam C can do. It would have
forced M2b before M4.

**Replaced with world fingerprinting:**

```
capture()   before execution   record what the world looked like
probe()     after a crash      compare; did it change?
```

| | Trailer injection (`0012` §3.3) | Fingerprinting (this) |
|---|---|---|
| Needs command mutation | yes | no |
| Works at Seam B | no | **yes** |
| Needs tool cooperation | yes | no |
| Generalises beyond git | poorly | yes |

`docs/0012` §3.3 should be superseded by this section.

### The probes

**`GitProbe`** — captures `HEAD`, the working-tree hash, and the repo toplevel.

- HEAD moved → `LANDED`
- HEAD same *and* tree identical → `DID_NOT_LAND`
- anything else → `INCONCLUSIVE`

`git push` is deliberately excluded: it is `EXTERNAL`, and a local probe cannot
see whether the remote accepted it.

**`FileAppendProbe`** — captures size, content hash, and the bytes to be
appended. On resume it verifies the **prefix is intact and our bytes are at the
tail**. That is a stronger claim than "the file changed": it proves *our* effect
landed, not merely that something happened.

## 3. Three bugs the tests caught

### C1 — the append check was broken on Windows

The first design predicted the exact post-file hash. On Windows a text-mode
writer turns `\n` into `\r\n`, so the prediction never matched and **every text
append would have failed closed**. Replaced with a prefix check plus a
newline-normalised tail comparison — more robust *and* a stronger statement.

### C2 — the git probe could attach to an ancestor repo

Found by accident: a temp directory sat inside an enclosing git repository, so
`capture()` succeeded against a repo the agent never touched. Whose HEAD moves
for reasons that have nothing to do with the agent.

The fingerprint now records `rev-parse --show-toplevel` and `probe()` returns
`INCONCLUSIVE` if it no longer matches. **A probe that attaches to the wrong
repo is worse than no probe** — it would confidently report `LANDED` because a
human committed elsewhere.

### C3 — a declared probe must beat a heuristic

`GitProbe.handles()` sniffs for `"git commit"` in the command string. A
dedicated `commit` tool carries no such string, so the probe was never selected
and the effect stayed blocked.

**Fix:** when the capability matrix explicitly names `probe: git`, trust it
without consulting `handles()`. The matrix is an operator declaration and knows
things a heuristic cannot. `handles()` now governs auto-selection only.

## 4. Harness lessons

Two more for `docs/0012` §6:

**Tool classes must be importable.** Defined inside a function, the SDK cannot
resolve them to deserialize a persisted `ActionEvent` on resume — and the replay
silently does nothing. It presented as "no resume decision at all". Module
level, always.

**The mock must derive tool arguments from the offered schema.** Hard-coded
arguments broke the moment a second tool with a different action shape arrived.
It now reads `function.parameters` and fills only required fields.

Both cost real time, and both are the same failure shape as `0014` §5: the
harness broke in a way that *looked like* a result.

## 5. What is still not done

- **`EXTERNAL` effects have no probe.** HTTP POSTs, emails, webhooks all still
  fail closed. The idempotency-key probe is unwritten.
- **`SUBSTITUTE` still blocks at Seam B.** The gate now *decides* `SUBSTITUTE`
  and the ledger reconciles correctly, but the agent still sees a rejection.
  M2b fixes the last step.
- **One crash point, not nine.** `docs/0012` §6 still wants the parametrised
  suite.

## 6. Consequences

- `docs/0012` §3.3 → superseded by §2 above.
- `docs/0012` §5.1 → document that a declared probe overrides `handles()`.
- `docs/0012` §6 → add the two harness lessons.
- `docs/0009` Q14 ("can the gate inject a git trailer?") → **WONTFIX.** The
  question is moot; fingerprinting removed the need.
- Next: **M2b** (so `SUBSTITUTE` actually substitutes) or **M5** (cost ledger).

## 7. Method note

Every bug in M4 was found by execution, none by reading. C1 in particular was
invisible on a Unix-like reading of the code and would have made the filesystem
probe useless on the machine it runs on.
