# Experiments

Reproducible experiments. Each gets a directory named `NNNN-slug/` matching the
`docs/` number of the EXPERIMENT document that reports it.

Each experiment directory contains:

```
method.md      What is being tested, the hypothesis, and what would falsify it
setup.sh       Environment setup, including the exact pinned dependency versions
run.py         The experiment
results/       Raw output — logs, event dumps, ledger state
```

**Pin versions.** `docs/0009` R1 records that both OpenHands and LiteLLM move
fast enough that source-derived claims decay. Every experiment must record the
exact version it ran against, or its result is not interpretable later.

## Planned

### 0000-step-0-falsification

The gate for all build work. Resolves `docs/0009` Q1, Q2, and Q3.

Tests:
1. Does a tool re-execute after crash-resume? (Q1)
2. Is `tool_call_id` identical on the replayed action? (Q2)
3. Can a custom executor be injected via public API? (Q3)

Method sketch is in `docs/0006` §7 Part A. Extend it to capture the
`tool_call_id` comparison for Q2.
