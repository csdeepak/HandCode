---
Number:        0048
Title:         A Run You Can Read
Type:          DECISION
Status:        ACCEPTED
Created:       2026-10-03
Supersedes:    —
Superseded-by: —
Depends-on:    0021, 0042, 0043, 0044, 0046
---

# 0048 — A Run You Can Read

`0043` Phase 3, with `0042` I-09 and I-10, which it named as preconditions
("the report's `used` line is worthless until both land").

**The test, from `0043`:** a user can answer four questions from the report
alone, without opening the ledger. Did it work? What changed? What did it
use? What is left for me?

---

## 1. The report

Phase 0 ended every run with `decisions {'EXECUTE': 9}`, and both of its
successful tasks exited 1 (`0044` F6, F10, N15). A run now ends:

```
  ── result ──────────────────────────────────────────────────────────
  outcome     PASS   `python -m pytest -q` exited 0 (run by agentctl after the agent finished)
  changed     1 file  +6 -1
                cal.py  +6 -1
  agent said  "The fix for the `is_leap` function in `cal.py` has been successfully verified. ..."
  used        18 requests · 88.1K tokens · $0.00 (free-tier model) · 34s
  actions     16 actions: 9 commands, 6 reads, 1 file write
  needs you   nothing
  resume      agentctl run "" --workspace ... --resume 12119d8d-...
```

| Line | Rule |
|---|---|
| `outcome` | **Only what was checked.** `--accept "<cmd>"` runs after the agent finishes, outside its loop and outside the ledger, so the result is the harness's observation rather than the agent's claim. Without it: `not checked`, which is neither a pass nor a failure |
| `changed` | git, measured against the commit the run started from, so agent commits count. New untracked files count. `.agentctl/` never does. Files already dirty before the run are flagged, because their diff mixes your edits with the agent's |
| `agent said` | The agent's last message, the same extraction the subagent uses (it once returned the user's own prompt, `0039` #8) |
| `used` | Requests and tokens are the difference across the run in the SDK's persisted metrics, so a resume counts only its own part. Cost is labelled with what it can be trusted for |
| `actions` | The ledger's classes and verdicts in the user's words: read, file write, command, dangerous command; "already done, reused"; "paused" |
| `needs you` | Paused actions, with the command that answers them |

**Exit code:** 0 when nothing failed a check and nothing waits on you;
otherwise 1.

**Vocabulary at the point of contact.**
- The live `[agentctl]` lines say `paused` and `reused`, not `BLOCK` and
  `SUBSTITUTE`.
- A superseded process's block now reads *"another process has taken over
  this conversation…"* rather than *"gate error, failing closed:
  StaleFence(…)"* (left open in `0046` §5).
- Genuine gate errors keep the words "gate error", which M6 counts.

## 2. Found while building it: a workspace inside a bigger repository

The capture run for I-09 used a scratch workspace that is not itself a
repository, but sits inside the owner's **home-directory** repository.
Unscoped, the report's git queries would have described the whole home repo.

`rev-list`, `diff` and `status` are now limited to the workspace's subtree,
with paths relative to it. The report adds *"(inside the repository at …)"*.
That is the README's own warning about this layout, now said at the moment it
matters.

## 3. I-09: conversation attribution through the proxy

**Captured, not assumed** (`0021` §4's lesson). A debug callback recorded the
real pre-call `data` dict at a litellm 1.103.2 proxy, during an
`agentctl run`. Its top-level keys:

```
litellm_call_id, litellm_logging_obj, litellm_session_id, litellm_trace_id,
max_completion_tokens, messages, metadata, model, prompt_cache_key,
proxy_server_request, secret_fields, temperature, tools
```

- `litellm_session_id` and `metadata.session_id` both held the agentctl
  conversation id; the persisted conversation directory is the same UUID.
- `extra_headers` does not exist at the proxy. It is a client-side keyword,
  and it was the only place the hook looked.

**Fix.** The hook reads `litellm_session_id`, then `metadata.session_id`,
then `extra_headers` last, for a direct caller. It is tested against the
captured shape.

**Live (E-14).** 18 of 18 calls and records carried the conversation id,
against 23/23 and then 10/10 `unknown:` before. The proxy's count equals the
report's "18 requests", which is E-14's pass condition. `cost --conversation`
returns rows for the first time.

## 4. I-10: known-free is not unpriced is not priced

The same live run then showed the two commands disagreeing:

| | Said |
|---|---|
| The report | $0.00 (free-tier model) |
| `agentctl cost` | **$0.0141 + unknown (12/18 priced)** |

The pool contains only free deployments. The figure was list prices
litellm attached to free Gemini, Mistral and Groq calls, plus OpenRouter
`:free` calls it could not price. It was wrong in both directions, and the
`daily_usd` cap was counting it.

**Fix.**
- The hook records the config's own `model_info.free`.
- The cost ledger stores it as a third state: a known zero, excluded from
  spend, and counted as known for coverage.
- It is displayed as **"free tier, per proxy config"**, because "free" is a
  configuration claim, not an observation (`0042` I-10's concern).
- Only a literal `true` counts.
- Older ledgers are migrated in place.
- Free deployments are no longer listed as "unpriced".

**Live.** Report: 11 requests, $0.00. `cost --conversation`: 11 calls,
`$0.0000 (11 call(s) free tier, per proxy config)`. They agree.

## 5. Evidence

| | |
|---|---|
| Tests | `test_report.py` (25), plus `test_hook.py` (+2, from the captured dict), `test_cost.py` (+7) and `test_one_driver.py` (the zombie wording) |
| Live, direct | Gemini-free path: `--accept` PASS, exit 0, 9 requests, `$0.00 (free-tier model)` |
| Live, pooled | Managed pool: PASS, exit 0, 18 requests, all attributed. Then a third run: report and cost ledger agree at 11 calls, $0.00 |

## 6. Left open

- **The run time excludes CLI start-up.** The report's `12s` was from a
  22-second command; about 10 s of it is importing the stack before the
  runner starts.
- **No per-turn progress line.** The SDK's visualizer already prints every
  action, and a second stream would duplicate it. That stays with `0042`
  I-18's open question: is "print more" enough?
- **A live `FAIL` outcome was not exercised.** Its rendering is unit-tested,
  and `accept()` runs a real subprocess in every test.
- **The capture run itself exited 1, with no effects recorded.** Probably the
  2-step task against a rate-limited Gemini group. Not investigated; the
  capture was what it was for.
- **Phase 4 is next:** a run index, `agentctl resume`, clean Ctrl-C, approvals
  that do not need a terminal (F7), and the wait-only half of I-05.
