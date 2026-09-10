# Full stack — THE integration test

Every piece at once, for the first time. See `docs/0022`.

```bash
python run_full_stack.py
```

```
OpenHands agent
    -> LiteLLM proxy          Seam A: hook, turn-pinning, telemetry
        -> two mock accounts
    + agentctl gate           Seams B and C: ledger, probes, substitution
```

Crash the agent mid-commit, resume through the same proxy, assert one commit.

Zero cost: local mock backends, no API key, no network.

## Why it exists

Each seam was proven alone. This is the only test that would notice them
drifting apart.
