---
Number:        0015
Title:         SDK Capability Findings — Q15, Q16, Q17 (and Q5)
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-08
Supersedes:    —
Superseded-by: —
Depends-on:    0008, 0012, 0014
---

# 0015 — SDK Capability Findings

Source reading against the pinned `openhands-sdk 1.45.0`. Four questions
answered, one of them a correction to `0008` §3.

**Confidence:** all claims below are **T1 (source code, read directly)** but
**not yet executed**. Per the project's own discipline, treat as VERIFIED-from-
source and confirm empirically in M2.

---

## 1. Summary

| # | Question | Answer | Effect on scope |
|---|---|---|---|
| Q15 | Does `prompt_cache_key` serve our affinity need? | **PARTIAL** | Provider-side shard key exists; cross-account affinity is still ours |
| Q16 | Is `hook_config` a fourth seam? | **PARTIAL — and it corrects `0008` §3** | Seam B *can* block. It cannot substitute. |
| Q17 | Does `max_budget_per_run` cover the budget guard? | **PARTIAL** | Per-run cap is free; per-day is not |
| Q5 | Does the SDK forward a trace id? | **YES** | Conversation-level attribution is free |

No milestone is deleted outright. Three shrink.

---

## 2. Q16 — the correction to `0008` §3

`0008` §3 states:

> **Seam B — Inside the agent, observing.** *Cannot: prevent anything.
> Callbacks are notification, not interception.*

**That is wrong.** The SDK publishes an enforcement primitive reachable from
any in-process callback:

```python
# openhands/sdk/conversation/state.py
def block_action(self, action_id: str, reason: str) -> None:
    """Persistently record a hook-blocked action."""
    self.blocked_actions = {**self.blocked_actions, action_id: reason}
```

And in `hooks/conversation_hooks.py`, the comment on its call site:

> *"Mark this action as blocked in the conversation state. The Agent will check
> this and emit a rejection instead of executing."*

`PRE_TOOL_USE` hooks fire from `HookEventProcessor.on_event` when an
`ActionEvent` is emitted — which per `0006:V1` is **before the tool runs**.
The timing is right, and `block_action` is a plain public method.

### What this changes

**Seam B can BLOCK.** It cannot **SUBSTITUTE**.

That distinction decides everything. Our gate has four verdicts
(`0012` §3.2), and they split cleanly:

| Verdict | Seam B via `block_action` | Seam C via executor wrap |
|---|---|---|
| `BLOCK` | ✅ | ✅ |
| `ESCALATE` | ✅ | ✅ |
| `EXECUTE` | ✅ (do nothing) | ✅ |
| **`SUBSTITUTE`** | ❌ agent gets a *rejection*, not the stored observation | ✅ |

`SUBSTITUTE` is the common good path on resume: the effect already landed, so
return the recorded observation and let the agent continue as if nothing
happened. Blocking instead would tell the model its tool was rejected, which is
both false and likely to derail the plan.

**So Seam C stays.** But `0008` §3's claim that Seam B is powerless is wrong and
must be corrected.

### Do not use the hook system itself

`HookType` is `AGENT | COMMAND | PROMPT` — all external. There is no in-process
callable hook type, so using the hook system would mean a subprocess per tool
call. Since `block_action` is public, **call it directly from our own event
callback** and skip the hook machinery entirely.

The hook system remains interesting for a different reason: it is the
user-facing extension point, so a future `agentctl` could ship as a
`COMMAND` hook for people who don't want to embed our adapter.

---

## 3. Q15 — `prompt_cache_key`

Traced: `LocalConversation.get_llm_call_context()` →
`LLMCallContext(prompt_cache_key=self._prompt_cache_key or conv_id)` →
`apply_call_context()` → `out["prompt_cache_key"]`.

It is **OpenAI's `prompt_cache_key` request parameter** — a provider-side hint
that improves routing to their internal prefix cache. It defaults to the
conversation id, and sub-conversations can share a parent's shard.

### What it does and does not give us

- ✅ A **stable per-conversation cache key already exists** and is sent. We do
  not need to invent or thread one.
- ❌ It says nothing about **which of our accounts or deployments** to route
  to. That is the whole of `0008` §7 and remains ours.

**Scope effect:** small reduction. Cache intelligence keeps its BUILD verdict,
but the "give each conversation a stable cache identity" sub-task is already
done. Reuse this key as the affinity map's key rather than hashing prefixes
ourselves — simpler, and consistent with what the provider already sees.

---

## 4. Q17 — `max_budget_per_run`

```python
# LocalConversation
# "Hard cost ceiling (USD) for a run; None disables the budget check."
spent = self.conversation_stats.get_combined_metrics().accumulated_cost
if spent < self.max_budget_per_run: return None
return f"Agent reached maximum budget limit (${...}); accumulated cost ${...}."
```

Real, and better than expected: it bounds **combined** spend across every LLM in
the run — agent *and* condenser — complementing the iteration cap.

| `0013` §2 policy | Covered? |
|---|---|
| `per_task_usd` | ✅ **configure, do not build** |
| `daily_usd` | ❌ still ours — nothing tracks across runs |
| `on_exceeded: block` | ✅ the run fails with a limit error |

**Caveat found in M0:** it depends on litellm's cost calculation, which emitted
`Cost calculation failed: This model isn't mapped yet` for our mock model
(`0014` §5). Any endpoint litellm cannot price is invisible to this cap —
directly relevant to the free-tier pool in `0013` §2, where custom and
self-hosted endpoints are common. **Verify pricing coverage per endpoint before
relying on it.**

---

## 5. Q5 — trace-id forwarding (bonus)

```python
if ctx.session_id:
    out["extra_headers"] = {**existing, "x-litellm-session-id": ctx.session_id}
```

The SDK **already sends** `x-litellm-session-id` set to the conversation id on
every call. `0006:V10` records that LiteLLM populates `LiteLLM_SpendLogs
.session_id` from that header.

**So conversation-level cost attribution works with zero code.** `0008` §8's
join exists at conversation granularity today.

The gap is turn granularity: `0008` §8 wants `(conversation_id, turn_id)`. Our
Seam A hook adds the turn component. That is a smaller job than designed.

`0009` Q5 → **RESOLVED**.

---

## 6. Revised seam table

Replaces `0008` §3.

| Seam | Mechanism | Can block | Can substitute | Porting cost |
|---|---|---|---|---|
| **A** | LiteLLM `CustomLogger` | ✅ (reject request) | n/a | zero — harness-independent |
| **B** | Event callback + `ConversationState.block_action` | ✅ **(new)** | ❌ | low |
| **B′** | `HookConfig` `PRE_TOOL_USE` | ✅ | ❌ | low, but subprocess per call |
| **C** | `ToolDefinition.executor` wrap | ✅ | ✅ | the real cost |

**Design consequence.** Split the gate across two seams by verdict:

- **Seam B** handles `BLOCK` and `ESCALATE` — cheap, no wrapping, and it works
  even if the executor wrap fails on some tool.
- **Seam C** handles `SUBSTITUTE` — the only verdict that needs it.

This makes the system degrade gracefully: lose Seam C and you still fail closed
correctly, you just lose clean resume. That is a materially better failure mode
than `0008` assumed, and worth building deliberately.

---

## 7. Consequences

- `0008` §3 — **must be corrected**; §12 porting table too.
- `0008` §7 — reuse `prompt_cache_key` as the affinity key.
- `0008` §8 — conversation-level attribution is free; only turn-level to build.
- `0012` §3.2 — split gate verdicts across seams B and C per §6 above.
- `0013` §2 — `per_task_usd` becomes configuration; `daily_usd` stays a build.
- `0009` — Q5, Q15, Q16, Q17 resolved. New: Q18.

### New question

**Q18 — does litellm price every endpoint in the free-tier pool?** If not,
`max_budget_per_run` silently under-counts and the budget guard is unreliable
exactly where budget matters most.

---

## 8. Verdict on the exercise

Roughly an hour of source reading. It did not delete a milestone, but it:

- corrected a **wrong claim** in the core architecture document,
- found a **better failure mode** for the gate,
- turned one policy field into configuration,
- resolved a fifth question (Q5) that was not being asked,
- and surfaced a new risk (Q18) about pricing coverage.

Reading the source before building remains the highest-return activity in this
project. Do it again before M2.
