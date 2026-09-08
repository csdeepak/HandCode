# M1 — Seam A acceptance

Does the LiteLLM hook actually fire, and does failover work? **Yes** — `docs/0021`.

```bash
python run_m1.py
```

Zero cost: two local mock backends, one of which can be told to return 429.

## Why "actually fire" is the assertion

LiteLLM silently bypasses `async_pre_call_hook` on the Anthropic endpoint
(#27518) and never fires it for MCP calls (#25011). **A Seam A that does
nothing looks exactly like one that works** — so `docs/0012` §0 requires
proving it, not assuming it.

## Gotchas this experiment encodes

- **UTF-8 in the child env.** LiteLLM's startup banner is non-ASCII; under a
  redirected cp1252 pipe the proxy dies with `Application startup failed`.
- **Read telemetry at the end.** The logging callback is async, so an early
  read undercounts and makes a working hook look broken.
- **Metadata lives under `litellm_params.metadata`** on the logging callback,
  not `kwargs["metadata"]`. See `docs/0021` §4.
