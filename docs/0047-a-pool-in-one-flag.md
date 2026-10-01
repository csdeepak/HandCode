---
Number:        0047
Title:         A Pool in One Flag
Type:          DECISION
Status:        ACCEPTED
Created:       2026-10-02
Supersedes:    —
Superseded-by: —
Depends-on:    0028, 0041, 0042, 0043, 0044
---

# 0047 — A Pool in One Flag

`0043` Phase 2, both parts. **Part A** is `agentctl init` and a `run` that
needs no flags (`09c1a83`). **Part B**, recorded here, is a proxy agentctl
installs, starts and stops itself, and the four defects the first live run
through it found.

---

## 1. Part A, briefly

| | Before (`0044`) | After |
|---|---|---|
| Default model | One hard-coded OpenRouter id, whatever key you held | `--model` > `AGENTCTL_MODEL` > `~/.agentctl/config.toml` > your first provider, free first. `run` prints which |
| Setting up | `keys --init`, edit the file, `keys --check`, `doctor` | `agentctl init`: finds or asks for one key (never echoed), proves it with one completion, records the model that answered |
| Live | — | From an empty home with one key: `init` in 16 s; then a flagless `run` in a repo, exit 0 in 57 s |

## 2. The managed proxy

```
agentctl run "..." --pool      starts the pool if needed, routes through it
agentctl proxy up | status | down
```

`~/.agentctl/proxy-env` is a venv holding `litellm[proxy]` and a **copy** of
agentctl's pure-Python package, which the hook needs. The OpenHands SDK is
never installed there.

The user's install never contains the proxy extra, so the `mcp` conflict
(`0028`) cannot arise. Live, the proxy env resolved litellm 1.103.2 with
`mcp` 2.2.0, so upstream may have relaxed the conflict anyway.

**Nothing goes on the proxy's `PYTHONPATH`.** The generated start scripts
point it at the main environment's `site-packages`. Under a non-editable
install that is the user's whole environment, conflict included. A test
pins this.

## 3. What the live run found

Each row is a defect no mock showed. Every one was fixed before the live run
that passed.

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | litellm exited during startup with `0xC000013A` (STATUS_CONTROL_C_EXIT), log empty | The `litellm.exe` console-script wrapper, launched `DETACHED_PROCESS` | Launch the env's own `python.exe` with `run_server`, using `CREATE_NO_WINDOW` and a new process group. Also `CREATE_BREAKAWAY_FROM_JOB`, so the proxy outlives the launcher that started it (falls back if the job forbids breakaway). Verified: `status` shows it running after `up` exits |
| 2 | 404 *"unavailable for free"* from `nex-agi`, which ended the run | Verification stopped at each provider's **first** answering model. With `nex-agi` moved last in part A, it was never tried, never marked gone, and stayed in the pool. `0042` I-11 part 1 | Pool verification checks **every** model id, one completion each. A rate limit or an overload does not mark a model dead. `keys --check` still stops at the first success |
| 3 | 400 from Groq: *"property 'prompt_cache_key' is unsupported"*, which ended the run | The run's model is `openai/pool`, so the SDK sends OpenAI's `prompt_cache_key`. litellm's Groq config inherits OpenAI's parameter list, so `drop_params: true` forwards it anyway | `Provider.reject_params`; Groq's deployments carry `additional_drop_params: [prompt_cache_key]`. Only what a live 400 showed |
| 4 | `2>/dev/null` prompted as *"writes outside the workspace"*; with no terminal, EOF refused it | `escaping_writes` treated a sink as a destination | `/dev/null`, `/dev/stdout`, `/dev/stderr`, `/dev/tty`, `NUL` and `CON` are exempt, by exact name: `/dev/sda` is still reported |

Two found by the tests rather than the live run:
- `up` refused port N when something answered on the *default* port.
- A test fixture leaked its listening socket.

**And one found by CI, after the push (`da1d0d1`).** Every Linux job died
with exit 143 (SIGTERM), 23 s into the unit tests.
- **Cause.** On POSIX, `proxy down` signalled the target's whole process
  group. The test's child shared pytest's group, so `down` killed pytest and
  the CI step with it. A pid file naming any process in the caller's group
  would do the same.
- **Fix (`63cf8ec`).** Signal the group only when it is not ours. A proxy
  `up` started is in its own session; anything else gets the pid alone.
- **Checked on Linux (WSL).** The old code SIGTERMed the calling shell. The
  fix stops a same-group child, and an own-session child together with its
  grandchild, and survives.

The same investigation found that importing `agentctl.runtime.lease`
eagerly loaded the tools, pydantic and the SDK through the package's
`__init__`. Those names now load lazily. Windows CI could not show either
problem, which is `0028`'s lesson again.

**Also measured.**
- A clean non-editable wheel install with `[openhands]` took **815 s**,
  against 4 m 20 s in Phase 0. One measurement, cause not captured. If it
  repeats, it is the largest single cost against the 5-minute target.
- Creating the proxy env took about 4 minutes, once.

## 4. The run that passed

`agentctl proxy up` built the pool:
- verification: 4 providers live; Cerebras `no-credit` and left out; the
  paid provider skipped;
- `nex-agi` left out *by name*;
- **42 deployments**, all 24 Groq entries carrying the drop.

Then `agentctl run "<fix clamp(), add tests, run them>" --pool`:
- **exit 0 in 40 s**, 3 tests passing;
- 8 EXECUTE and 1 BLOCK, the BLOCK being defect #4, fixed afterwards;
- `proxy down` stopped it, and port 4000 was free.

**The procedural error worth recording.** The first failing run used a pool
I had restarted with `--no-verify` to save time, and it died on Cerebras's
402: exactly `0041` §2.1. Verification is not optional for a pool, and the
default is right.

## 5. Left open

| | |
|---|---|
| **Package name** (D3, D4) | `agentctl` is taken on PyPI: one `0.0.1a1` placeholder, 2024-12-22, by another author. `agent-ctl` collapses to the same name and would be refused. `handcode`, `effectledger` and `agentctl-ledger` are free. The command stays `agentctl` whatever the distribution is called. **Owner's decision** |
| Publishing | Needs the owner's PyPI account. Not something to do on their behalf |
| Unattended confirmation (F7) | Still EOF-refuses with no terminal. Phase 4 |
| `pip install` by the agent | Ran unasked in part A's live run (`Requirement already satisfied`, so nothing changed). EXTERNAL, not DESTRUCTIVE, and not a write the path check sees, so no confirmation. It changes the user's Python environment. For I-26 |
| The 815 s install | Re-measure, then decide whether a lighter default install is worth it |
| Groq in the default pool | `0042` I-11 part 2 (turn-2 TPM). Still in `pool`. With #3 fixed it served; whether it carries turn 2 is unmeasured here |
