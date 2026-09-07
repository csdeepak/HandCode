# M2b — Acceptance

Does Seam C return the **result** instead of a rejection? **Yes** — `docs/0018`.

```bash
python run_substitute_chaos.py
```

Zero cost: reuses the M0 mock provider and the M4 commit tool.

## The arc

| | M2a | M4 | M2b |
|---|---|---|---|
| Duplicate | none | none | none |
| Ledger | BLOCKED | COMMITTED | COMMITTED |
| Human needed | yes | no | no |
| Agent receives | rejection | rejection | **observation** |

## Verdicts

`PASS`, `PARTIAL`, `FAIL`, `INCONCLUSIVE`. `PARTIAL` means no duplicate but the
substitution did not reach the agent cleanly — the distinction that caught a
real bug (`docs/0018` §4).
