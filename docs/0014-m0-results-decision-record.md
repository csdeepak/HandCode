---
Number:        0014
Title:         M0 Results — Decision Record
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0012
---

# 0014 — M0 Results

First code executed. Four hypotheses, four confirmations.

**Run:** 2026-09-07 18:58 UTC · `openhands-sdk 1.45.0` · `litellm 1.100.0` ·
`pydantic 2.13.5` · Python 3.13.7 · Windows.
Raw evidence: `experiments/0000-falsification/results/`.

---

## 1. Verdicts

| # | Hypothesis | Verdict | Consequence |
|---|---|---|---|
| H1 / Q1 | Double execution is real | **CONFIRMED** | The Effect Ledger is the product. `0007` stands. |
| H2 / Q2 | `tool_call_id` stable across resume | **CONFIRMED — later CORRECTED** | See `0023` §4: this was an artifact of the mock returning a fixed id. A real multi-model pool mints a different id per model. |
| H3 / Q3 | Executor wrappable without a fork | **CONFIRMED** | Seam C exists. Option 3 holds. |
| H4 / Q13 | OpenAI-format endpoint in use | **CONFIRMED** | Seam A hooks will fire. |

**The architecture in `0008` survived contact with the real system.**

## 2. The central evidence

```
effects_after_crash        1
effects_after_resume       2          <- the duplicate
tool_call_ids_before       ['call_m0_fixed_0001']
tool_call_ids_after        ['call_m0_fixed_0001']
endpoint_paths             ['/v1/chat/completions']
```

A side-effecting tool ran once, the process was hard-killed after the effect
landed but before the observation was recorded, and on resume **the effect ran
a second time**. This is no longer an inference from reading source
(`0006:V1`,`V2`) — it is reproduced behaviour on a pinned version.

The same run shows `tool_call_id` surviving the crash byte-identical, which was
the highest-risk unverified assumption in `0012`.

## 3. Corrections to `0012`

### C1 — Seam C binds on a field, not a subclass

`0012` §4 specified subclassing `ToolExecutor` and re-registering the tool. The
real API is better: **`ToolDefinition` carries the executor in a field**, so the
binding is

```python
gated = tool.model_copy(update={"executor": GatedExecutor(tool.executor)})
```

Less invasive than designed, and it keeps the adapter smaller — which matters,
because `0008` §12 makes adapter size the whole portability cost.

### C2 — `register_tool` takes a ToolDefinition, not an executor

Real signature:
`register_tool(name: str, factory: ToolDefinition | type[ToolDefinition])`.
The resolver calls `create(conv_state=conv_state, **params)` and expects
`Sequence[ToolDefinition]`.

### C3 — API details that differ from the spec

| `0012` assumed | Actual |
|---|---|
| `ToolExecutor.__call__(action)` | `__call__(action, conversation=None)` |
| `conversation_id: str` | `uuid.UUID` |
| `persistence_dir` alone | `workspace` is a separate required parameter |
| `include_default_tools: bool` | a **list** |
| Tool name used verbatim | SDK **strips a `_tool` suffix** — `side_effect_tool` resolves to `side_effect` |

`0012` §2.1 and §4 should be revised against these before M2.

## 4. Findings worth keeping

**F1 — `LocalConversation` already accepts `prompt_cache_key`.** Directly
relevant to `0008` §7 cache affinity; investigate before building anything
there.

**F2 — `hook_config: HookConfig` exists on `Conversation`.** A possible fourth
seam that `0008` §3 did not consider. Worth a look — it may offer interception
the event callbacks cannot.

**F3 — `max_budget_per_run` exists on `LocalConversation`.** Partially serves
the budget guard in `0013` §4. Configure before building.

All three are scope-reduction opportunities. Record as questions, not features.

## 5. Engineering notes from the run

Three bugs, all found by executing rather than reasoning:

1. **Windows cp1252 `UnicodeEncodeError`** — probes crashed printing `→`.
   Fixed with a UTF-8 stdout reconfigure and ASCII console output.
2. **Subprocess pipe deadlock** — the SDK's visualizer output filled the pipe
   buffer with no reader draining it, blocking the child mid-run. The parent
   was polling for a marker at that moment, so it timed out and reported a
   false negative. **Child output now goes to files, never to an undrained
   pipe.** This one would have produced a wrong M0 verdict.
3. **Tool-name normalisation** — the mock called `side_effect_tool` while the
   agent exposed `side_effect`. The mock now reads the offered name from the
   request rather than hard-coding it.

Bug 2 is the instructive one: it presented as "the tool never ran" when the
tool ran fine. **A test harness that fails silently in the direction of your
hypothesis is worse than no test.** The chaos suite in `0012` §6 must be built
to fail loudly and distinguish "did not happen" from "could not observe."

## 6. Consequences

- `0009` Q1, Q2, Q3, Q13 → **RESOLVED**.
- `0008` may move DRAFT → ACCEPTED once §15 is updated with these results.
- `0012` §4 needs revision per C1–C3 before M2 begins.
- Next: **M1** (LiteLLM wiring, live hook proof), then **M2** (ledger + gate).

## 7. What this cost

Zero. No API key, no tokens, no network — the spike runs entirely against a
local mock provider. Re-run it on every SDK upgrade; `0009` R1 requires exactly
that, and there is now no excuse not to.
