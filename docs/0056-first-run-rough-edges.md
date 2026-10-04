---
Number:        0056
Title:         Three Rough Edges from the First Real Run of 0.3.0
Type:          DECISION
Status:        ACCEPTED
Created:       2026-10-05
Supersedes:    —
Superseded-by: —
Depends-on:    0048, 0050
---

# 0056 — Three Rough Edges from the First Real Run of 0.3.0

The owner installed 0.3.0 from PyPI and gave it the practice task: fix
`add`, which subtracts, so `py test_calc.py` passes. It passed, in 6 requests,
$0.00, 12 s. Three things in the output were wrong, and none had shown up in
any test, because every test ran from a development environment.

| Seen | Why | Fixed in 0.3.1 |
|---|---|---|
| `changed 3 files`, two of them `__pycache__/calc.cpython-31x.pyc` | Running Python writes bytecode. The two versions show two writers: the agent's `python3`, and agentctl's own `--accept` run through `py` | `--accept` runs with `PYTHONDONTWRITEBYTECODE=1`. A **new, untracked** `__pycache__/`, `.pytest_cache/` or `*.pyc` is counted, not listed: `(2 generated files left out: __pycache__ and the like)`. A tracked file is listed whatever its name, since changing what git tracks is real |
| `python: command not found`, then the agent tried `python3` | The agent's shell (Git Bash, under a `uv tool` install) had `python3` but not `python`, and nothing said so | `tools.first_python()` tries `python`, `python3`, `py` once per process, in the agent's own shell. When `python` is not the one that works, the bash tool's description says which is, e.g. *"In this shell Python runs as `python3`, not `python`."* A candidate counts only if it prints, which excludes the Windows Store stub |
| `[10/05/26 02:01:38] INFO Created new conversation …` and `INFO Loaded 3 tools from spec`, inside agentctl's header | The OpenHands SDK logs at INFO by default | `runner._quiet_sdk_logs()` sets the `openhands` logger to WARNING, so warnings and errors still show. If `LOG_LEVEL`, the SDK's own switch, is set, it wins. Setting `LOG_LEVEL` here instead would have leaked into every command the agent runs |

## Evidence

**`tests/test_first_run.py`, 20 tests:**
- what counts as a byproduct;
- a new `__pycache__` is counted and not listed;
- a tracked `.pyc` that changes is still listed;
- `accept()` leaves no `__pycache__`;
- the report's wording, and `generated` in `--report-json`;
- `first_python` with `python`, with only `python3`, with a Store stub, and
  with none;
- the note's wording, and that the bash tool carries it;
- the SDK's level, and that `LOG_LEVEL` wins.

**One end-to-end run** repeats the owner's: the scripted model fixes `calc.py`,
then imports it, leaving bytecode, and the run is checked with `--accept`.
- Its report lists only `calc.py`, with `generated >= 1`.
- Neither INFO line is in the output.
- **On the 0.3.0 code it fails** with the owner's symptom:
  `['calc.py', '…cpython-313.pyc'] != ['calc.py']`.

**Found on the way:** `tests/scripted_model.bash()` named its tool
`execute_bash`. The model sees that tool as `bash`, and `execute_bash` is only
the registry name, so the SDK refused the call (*"Tool 'execute_bash' not
found"*). The helper now uses `bash`.

The full suite: 914 passed, 3 skipped.
