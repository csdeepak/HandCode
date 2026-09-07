# M0 — Falsification Spike

**Zero cost.** Runs against a local mock provider. No API key, no network, no tokens.

## Run it

```bash
python -m venv .venv
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on Unix
pip install openhands-sdk
python run_all.py
```

Results land in `results/report.md`.

## What it answers

| # | Question | If it fails |
|---|---|---|
| H3 / Q3 | Can a `ToolExecutor` be wrapped without forking? | Seam C is gone. The architecture dies. |
| H1 / Q1 | Does a side effect re-execute after crash + resume? | The Effect Ledger is not the product. |
| H2 / Q2 | Is `tool_call_id` stable across resume? | The ledger's primary key is invalid. |
| H4 / Q13 | Does the SDK call `/v1/chat/completions`? | Seam A hooks are silently bypassed. |

## Order

`probe_00_api.py` runs first and **gates the rest**. The later scripts are
written against an SDK API taken from docs, not from execution. If probe 00
reports a mismatch, `run_all.py` aborts rather than producing confusing
tracebacks — send `results/api_surface.json` back and the scripts get adjusted.

## Files

| File | Purpose |
|---|---|
| `method.md` | Hypotheses and what would falsify each |
| `mock_provider.py` | OpenAI-compatible mock; scripted tool call; records paths |
| `probe_00_api.py` | Discovers the real SDK surface + pins versions |
| `probe_01_wrap.py` | H3 — wrap and register an executor |
| `run_03_crash.py` | H1, H2, H4 — the crash/resume experiment |
| `run_all.py` | Orchestrates, writes `results/report.md` |

## After it runs

1. Record verdicts in `docs/0009` → Resolution log.
2. Write a numbered DECISION doc for anything falsified.
3. Only then promote `docs/0008` out of DRAFT.

Do not build here. M1 goes somewhere else.
