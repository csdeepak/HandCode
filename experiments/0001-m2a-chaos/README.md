# M2a — Acceptance

Does the gate prevent a duplicate effect? **Yes** — see `docs/0016`.

```bash
python run_chaos.py
```

Zero cost: reuses the M0 mock provider. No API key, no network.

## What it does

| | |
|---|---|
| RUN 1 | Gate writes `INTENT` → tool runs → hard kill before the observation |
| RUN 2 | Resume with the gate. `INTENT` + `NON_IDEMPOTENT_WRITE` + no probe → `BLOCK` |
| Assert | The side effect happened exactly **once** |

M0 produced 2 effects at this crash point. M2a produces 1.

## Verdicts

`PASS`, `FAIL`, or `INCONCLUSIVE`. Note the third: if the tool never ran, or
the crash landed in the wrong place, the harness reports `INCONCLUSIVE` with a
reason rather than guessing. A timeout is never a verdict (`docs/0012` §6).
