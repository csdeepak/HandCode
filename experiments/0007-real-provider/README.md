# Real provider — the full stack against OpenRouter

**Opt-in.** Needs `OPENROUTER_API_KEY`; skips cleanly without it.

```bash
python run_real.py
```

Free-tier models only, one tool call, capped output. ~11k tokens, $0.00 billed.
The key is read from the environment and never printed.

## Why it exists

Everything else runs against mocks, and **a mock agrees with whatever you
assumed**. This run found two real bugs on its first attempt — see `docs/0023`:

1. A real model filled a `cwd` field the mock left at its default, sending the
   commit into the wrong repository.
2. Two models in one pool minted **different `tool_call_id`s for the identical
   call**, so the ledger missed and the commit repeated. That invalidated the
   M0 answer to `docs/0009` Q2, which had been an artifact of the mock always
   returning a fixed id.

## Not in `verify.py`

`verify.py` stays free and key-free. Run this by hand, deliberately.
