# Nine-point chaos suite

The specification. Everything else exists so that this passes.

Run via pytest (it is part of the normal suite):

```bash
pytest tests/test_chaos_nine_point.py -q
```

`worker.py` runs one pass of the write-ahead protocol and can die at any named
point via `os._exit()` — a real crash that skips every finally block, atexit
hook and buffer flush.

## Why the kernel, not the SDK

The guarantee in `docs/0008` §10 is a property of the *protocol*. Driving it
directly makes the crash point **chosen rather than raced for**, and fast
enough to run on every commit. Experiments `0001`–`0003` cover the SDK
integration.

## Two effect kinds

| | behaviour |
|---|---|
| `git` | atomic from our side — the commit exists or it does not |
| `append` | non-atomic — `mid_tool` leaves half a line on disk |

The append case is the nastier one, and it is why `INCONCLUSIVE` exists.

## Does the suite have teeth?

Verified by mutation. Neutering the gate so every ambiguous `INTENT`
re-executes produces **7 failures**, exactly at the points where the effect had
already landed. See `docs/0019` §4.
