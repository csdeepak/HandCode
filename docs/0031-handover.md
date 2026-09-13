---
Number:        0031
Title:         Handover — The Flaws a Real User Found in an Hour
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-13
Supersedes:    —
Superseded-by: —
Depends-on:    0025, 0029, 0030
---

# 0031 — Handover: The Flaws a Real User Found in an Hour

M0–M7 were complete, 362 tests green, CI green. Then someone tried to do actual
work with it and hit four things in a row, none of which any test covered.

**413 tests passing** (was 362). New: `runtime/doctor.py`, `control/proxy.py`,
provider-error translation in `runtime/runner.py`.

---

## 1. What actually happened

A run against a real project: **15 effects COMMITTED, nothing blocked, and the
target file unchanged.** Then a second attempt died with a thirty-line
traceback ending in:

> *"please file a bug report at github.com/OpenHands/software-agent-sdk"*

It was not an SDK bug. The OpenRouter free-model daily allowance — 50 requests,
account-wide — was exhausted.

Four separate flaws, in the order they bit:

| # | Flaw | Fix |
|---|---|---|
| 1 | The task was unfalsifiable | nothing to fix in code |
| 2 | No way to check readiness before spending | `agentctl doctor` |
| 3 | A provider refusal looked like an agent bug | error translation |
| 4 | One account, so nothing to fail over to | `agentctl proxy` |
| 5 | `execute_bash` ran **cmd.exe**, not bash | run `bash -c` explicitly |
| 6 | A command that **failed** was recorded `COMMITTED` | read `is_error` at Seam B |

The last two are not usability complaints. They are correctness bugs in the
part of the system this repository exists to be right about, and neither was
visible until someone did real work.

## 2. The prompt was impossible, and that is worth recording

The task was *"fix the off-by-one in parse_range"* against a file containing
only `def parse_range(s):` — an empty stub. **There was no off-by-one.** The
model re-read the file looking for something that did not exist.

It is tempting to file this under "free-tier models are unreliable", which is a
warning this project already makes and which is generally true. But the failure
started with the task. A stronger model would probably have said "this function
is empty" and stopped; a weaker one loops. The tier changed the *symptom*, not
the cause.

Worth stating because the wrong lesson here — *buy a better model* — costs
money and fixes nothing.

## 3. Could a write commit without landing?

The report said 15 effects COMMITTED with an unchanged file, which raises a
real possibility: a **phantom commit**, a write recorded as landed that never
happened. That would weaken every correctness claim in this repository.

Checked: `WriteExecutor` writes the file, and the gate reconciles to COMMITTED
only after the executor returns. A `COMMITTED` `IDEMPOTENT_WRITE` therefore
implies the write ran. Fifteen `PURE_READ` rows from a read loop is consistent
with everything observed.

The mechanism does not admit the failure, and that was worth verifying before
accepting the comfortable explanation.

**Then the ledger itself turned up**, still on disk in the workspace, and
settled it — differently and worse than either guess. There were no phantom
commits. There were seven *real* writes, all issued through `bash`, five of
which had **failed** and been recorded as successes. See §8 and §9.

## 4. You cannot know the quota, and saying so is the feature

`agentctl doctor` checks packages, the `fastmcp` client (which `import fastmcp`
alone does not — `docs/0028` §5), the SDK import chain, git, Python version,
policy, workspace writability, and whether the workspace has uncommitted
changes before an agent starts editing it.

What it **cannot** do is tell you how many free requests remain. Probed both
`auth/key` and `credits`: neither returns rate-limit headers. `auth/key` gives
dollar usage and `is_free_tier`, nothing else. The counter appears only in the
`X-RateLimit-Remaining` header of a 429 — which you get by hitting the wall.

So it reports the cap and says the remaining count is unknowable:

```
!!  openrouter quota  FREE TIER: 50 model requests/day, account-wide across
                      every `:free` model. The remaining count is not exposed
                      by any endpoint — you find out at the 50th request.
```

A preflight that guessed would be worse than one that admits the gap.

## 5. An error must not send you to the wrong place

A 429 now reads:

```
the provider is rate limiting you. This is not an agent error.
  remaining    0
  resets       2026-09-14 05:30 local
  note         the free-model cap is account-wide across every `:free`
               model, so switching model does not help
  options      wait for the reset, use a different provider key,
               or run offline:  agentctl run '' --replay <cassette>
```

**Unrecognised errors are not translated.** `_explain_provider_error` returns
`None` for anything it does not recognise, and the original exception
propagates. Guessing at an unfamiliar error hides it; an ugly traceback is
worse to read and better to have than a confident wrong explanation. There is a
test asserting the translator stays silent on a `TypeError`.

## 6. The charter said pools, the install had one key

`docs/0001` is about surviving a rate limit without work stopping. That needs
somewhere to fail over **to**. `agentctl proxy` generates a LiteLLM config from
the keys actually present — a config naming providers you have no key for will
not start, since litellm resolves `os.environ/` at load.

The honest table, which the command prints:

| failure | one OpenRouter key | plus a second provider |
|---|---|---|
| transient overload (*"Upstream error from Nvidia"*) | **fixed** | fixed |
| per-model rate limit | **fixed** | fixed |
| free-models-per-**day** cap | **not fixed** | fixed |

Three `:free` models on one key is **one account and one quota**, so `accounts()`
counts credentials rather than deployments and the CLI says so out loud. The
first two rows are real wins — a transient overload did interrupt a genuine run
— and claiming the third would be the comfortable lie.

Fallbacks are ordered free-first, paid-last: an outage degrades toward *slower*,
never silently toward *billed* (`docs/0002` §5).

## 7. The generator emitted invalid YAML and did not notice

Writing §6 produced `fallbacks: [{"pool": ["or-nemotron" "or-deepseek"]}]` — a
missing comma. It was returned happily. The proxy would have failed to start
with a YAML parse error pointing at a file the user never wrote.

Caught only because the config was parsed as a check rather than read.

`build()` now parses its own output and asserts the properties that make it a
pool: one shared `model_name`, every key referenced from the environment rather
than inlined, fallbacks shaped as a list of mappings. And the tests check the
validator **can reject** — a validator that accepts everything is the shape of
`docs/0028` §5 all over again.

Seventh instance of the same lesson in this repository. It arrived while
writing the fix for the sixth.

## 8. The tool named `execute_bash` was not running bash

The user's own ledger, which they still had, answered §3 and then opened
something larger. Every one of the 36 effects was `bash` — the model never
called `write_file` once — and five of the write-classified ones read:

```
exit=1
<< was unexpected at this time.
```

`<<` unexpected is **cmd.exe** rejecting a heredoc. `subprocess.run(shell=True)`
uses `COMSPEC` on Windows, so a tool called `execute_bash` was running cmd.exe.
Confirmed directly: `echo $0` printed `$0`.

The gap is not cosmetic. The capability matrix splits commands on `&&`, `||`,
`;` and `|`, and matches `rm -rf`, `git reset --hard` and `>` redirects — all
**bash** rules, built in `docs/0026` against a 75-command corpus. Under cmd.exe
the classifier was guarding a shell nobody was running, while `del /s /q`, the
thing that actually deletes on Windows, matched nothing at all.

`0026` §6 listed "Windows shells are unhandled" as a gap. It was worse than a
gap: the development machine was *using* the unhandled shell.

Fixed by running `bash -c` explicitly when bash is present — Git for Windows
ships one, so it usually is. Heredocs, `$0`, `;`, `&&` and pipes all work now,
and the classifier is finally reasoning about the shell that runs.

## 9. A failed command was recorded as COMMITTED

The more serious half. Those five `exit=1` commands were all `COMMITTED`.

`SeamB._close` decided success from the SDK **event type**: `AgentErrorEvent`
meant failure, anything else meant success. A tool that ran and failed still
arrives as an ordinary `ObservationEvent`, so its `Observation.is_error` flag
was never read.

Demonstrated against the old code path:

```
OLD logic, command exited 1 -> COMMITTED
```

The consequence runs **opposite** to this project's usual worry. It does not
duplicate an effect; it makes a resume treat work that never happened as done
and skip it. Under-execution, silently — and `agentctl status` reports a clean
ledger while the file is untouched.

### The fix had to resist over-correcting

Marking every error `FAILED` would be wrong. `FAILED` means *provably did not
land*, and a non-zero exit is not proof: `echo x > a.txt && bad` writes the file
and exits 1. Asserting it did not land permits a duplicate — the direction
`docs/0008` §6.5 says must fail closed.

So it splits on what the effect class already encodes:

| | |
|---|---|
| `replay_safe` (read, idempotent write) | `FAILED` — retrying costs nothing |
| everything else | `BLOCKED` — nobody knows whether it landed, which is the definition of the ambiguous case |

And `_tool_error` returns `None` when it cannot tell, because "cannot tell"
must not become "failed" — that would block work for no reason.

The regression test drives `SeamB._close` with a failed observation, which is
where the bug actually lived. Asserting on the helper alone would have passed
against the broken wiring.

## 10. What this says about the testing

Four milestones, 362 tests, ten `verify.py` checks and green CI on two
operating systems did not catch either bug. One hour of a person doing real
work found both.

Neither is exotic. They are what you get when every test drives the kernel
directly with a synthetic `ToolCall`: the suite never asked *which shell runs*,
and never produced an observation with `is_error=True`. The chaos suite kills
processes at nine points and asserts the effect lands at most once — it never
asserts that a **failed** effect is not recorded as a success.

> A suite built from the inside tests the parts you thought of. It cannot test
> the assumptions you did not know you had made.

## 11. Consequences

- `docs/0012` §6 → new rule: a generator must parse its own output, and the
  parser must be shown to reject something.
- `docs/0025` §6 → "free-tier models are unreliable" is now too vague to act
  on. The specific failures are: an account-wide daily cap, transient upstream
  overload, and per-model limits. They have different fixes.
- `README` → `agentctl doctor` is the first command, before `run`.
- `docs/0026` §6 → "Windows shells are unhandled" understated it; the
  development machine was running the unhandled shell.
- `docs/0012` §6 → new rule: the suite must include at least one test that
  drives the real tool through the real seam, not the kernel directly.
- §3 is **closed**: the ledger showed the writes were bash redirects that
  failed, not phantom commits. The mechanism was sound; the recording was not.
