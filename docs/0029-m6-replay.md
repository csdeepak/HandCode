---
Number:        0029
Title:         M6 — Replaying a Session Means Replaying the World Too
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-13
Supersedes:    —
Superseded-by: —
Depends-on:    0012, 0023, 0025
---

# 0029 — M6: Replaying a Session Means Replaying the World Too

A real session recorded against a real provider, then replayed with **no API
key in the environment, no network, no tokens and no sampling** — identical
file, identical gate decisions.

**332 tests passing** (was 308). Code: `control/replay/`,
`adapters/litellm/recorder.py`. Experiment: `0008-m6-replay`, now in
`verify.py`.

---

## 1. What it does

```bash
agentctl run "add type hints to utils.py" --workspace ./app --record s.jsonl
agentctl run "" --workspace ./app --replay s.jsonl        # $0.00, offline
```

```
turns_recorded 3   turns_replayed 3   misses 0   diverged false
file identical      True
decisions recorded  ['EXECUTE', 'EXECUTE']
decisions replayed  ['EXECUTE', 'EXECUTE']
```

The keys are deleted from the environment before the replay, so a run that
quietly reached the network fails rather than passing for the wrong reason.

## 2. A miss is the product

The obvious mistake is to make replay forgiving — serve something plausible
when the request does not match. That would produce runs that look like
replays and are not, which is the failure shape of `0024` (a crash that looked
like a decision) and `0028` (a guard that could not fail).

So the server answers a miss with **502 and a position**:

```
cassette miss -- turn 1: message 3 (tool) differs from the recording
```

A divergence is the regression signal M6 exists to produce. Stopping *early*
counts too: a run that plays 2 of 3 turns has changed behaviour even though
nothing missed.

## 3. Two names for one model

The first replay failed with `LLM Provider NOT provided ... you passed
model=nex-agi/nex-n2.5-pro:free`.

litellm strips the provider prefix before a logging callback sees `model`, so
the cassette recorded the **stripped** name. That form is what the request
carries and what the fingerprint is built from — but it is not routable, and
reconfiguring the replay run with it produces a model litellm cannot call.

Both are needed and they are different strings: `provider_model` for
reconfiguring, `model` for matching. The recorder cannot derive the first, so
the caller stamps it.

## 4. A deny-list cannot match two representations

The second failure: `same messages, different tools or model`. Everything that
mattered was identical. The diff:

| field | recorded | on the wire |
|---|---|---|
| `messages`, `model`, `tools` | — | **same** |
| `prompt_cache_key` | absent | **the conversation id** |
| `usage` | absent | `{"include": true}` |

A cassette is recorded from a **Python callback** and matched against an
**HTTP body**. Those are two representations of one call, and the wire carries
fields the callback never sees. `prompt_cache_key` is the conversation id —
different on every run *by definition* — so no cassette could ever replay.

The fingerprint used a deny-list; the recorder used an allow-list. Two lists,
maintained separately, that drifted.

> A deny-list has to predict every field any provider might add. It fails the
> moment one does, and it fails *silently*, as a miss.

They are now **one list, shared by identity** — a test asserts
`recorder._REQUEST_KEYS is SIGNIFICANT_FIELDS`, not that they are equal. The
cost of an allow-list is explicit: a field outside it is *asserted* not to
determine the response, so additions belong in review.

## 5. The replay re-recorded itself

After both fixes the round trip passed. The cassette had **6 turns instead of
3**, and turns 3–5 were byte-identical to 0–2.

`detach()` removed the recorder from `litellm.callbacks`. litellm copies
callbacks into its own per-kind lists the first time it initialises logging,
so the recorder stayed live in `success_callback` and kept writing — recording
the replay into the recording.

Two mechanisms now, because the first cannot be made sufficient:

- `detach` sweeps every known litellm callback list, **and**
- the recorder sets `closed` and refuses to write.

litellm decides where to copy a callback. A future version with a tenth list
would silently resurrect a sweep-only fix; refusing to write is the guarantee
that does not depend on someone else's internals.

## 6. Replay pins the model, not the world

The limitation worth stating plainly, because it is inherent rather than a gap
to close later.

Tool observations feed the next request. Replaying the same session against a
**different workspace** produces different observations, therefore different
messages, therefore a miss on the first turn that reads a file. Verified: same
task, `utils.py` with different contents, and the run failed at turn 0 rather
than pretending.

That is correct behaviour, and it means:

> **A cassette is only replayable together with the filesystem it was recorded
> against.** Replay is deterministic in the model, not in the world.

`0008-m6-replay` therefore seeds its workspace to a fixed state before
replaying. A cassette shipped without its starting conditions is not a
reproducible test.

### And the world is bigger than the workspace

CI then failed the way that actually settles this. The experiment passed on
Windows and came back `INCONCLUSIVE` on Linux:

```
cassette miss -- turn 0: message 0 (system) differs from the recording
```

Message 0 is the **system prompt**, and the recorded one contains the word
`powershell`. The SDK builds it from the host, so a Windows recording cannot
replay on Linux no matter how correct the matching is. The workspace was
identical; the machine was not.

So a cassette is a fixture of an **environment**, not of a model and not of a
directory. Each turn now records `platform`, `python` and `openhands_sdk`, and
the experiment refuses up front:

```
SKIPPED - recorded on win32, replaying on linux -- the SDK puts the shell
          name in the system prompt, so turn 0 cannot match
```

**SKIP is a third outcome, distinct from PASS and from FAIL**, alongside the
`INCONCLUSIVE` that `0012` §6 already required. Reporting this as a divergence
would have been a lie: the code did not change, the machine did. Reporting it
as a pass would be worse. `verify.py` prints every skip in the summary, because
a skip nobody sees is a check that quietly stopped existing.

Only `platform` is refused. A different SDK version is *reported* but still
attempted — a changed prompt should surface as an honest miss, which is
information, rather than being pre-empted by caution.

The consequence for coverage is worth stating plainly: **CI cannot run the
real-session round trip**, because the cassette was recorded on a machine
unlike the runner. What CI does cover is the replay machinery itself —
`tests/test_replay.py`, 24 tests, everywhere. Recording a Linux cassette would
close the gap and needs a key in CI, which is not a trade worth making.

### It caught a real regression, unprompted

The first time M6 earned itself was not a test. Fixing `write_file` to preserve
line endings (`docs/0035`) changed a write from 107 bytes to 111 — four extra
carriage-return characters — and that byte count appears in the observation the model
reads:

```
recorded:  "written (107 bytes)"
now:       "written (111 bytes)"

cassette miss -- turn 2: message 5 (tool) differs from the recording
```

`verify.py` went from 10/10 to `INCONCLUSIVE`, naming the turn and the message.
Nothing else in 497 tests noticed that the fix had altered what the agent sees.

So the invalidation rule is broader than §6 says. A cassette is bound to the
platform, to the workspace, **and to the behaviour of every tool in the loop**.
Any change to what a tool returns invalidates every recording that contains it
— which is exactly the property that makes a miss a regression signal rather
than an inconvenience. The cassette was re-recorded and committed alongside the
fix that changed it.

## 7. What determinism hides

Replay pins `tool_call_id`, because the recorded response carries the one the
model minted. Convenient, and a trap: `0023` found `tool_call_id` is **not**
stable across a real model pool, and that bug duplicated a real git commit. A
suite that only ever ran under replay would never have found it.

Replay tests *our* logic against fixed inputs. It cannot test how the world
varies, and it must not become the only way the system is exercised.

## 8. Cassettes are logs, not fixtures

Every recorded request holds the full message history — source, file contents,
whatever the agent was working on. Credentials are never captured, because they
live in headers this never sees, and the committed cassette was scanned before
it went in. But a cassette is as sensitive as the workspace that produced it.

## 9. Consequences

- `0012` §7 → **M6 is complete**, and `verify.py` now has 9 checks.
- `0012` §6 → new rule: when two components must agree on a list, share the
  object rather than maintaining two copies.
- The demo problem from `0025` §6 is solved. A live run against a free-tier
  provider is a coin flip — one died mid-session on *"Upstream error from
  Nvidia"*. `--replay` makes a real session reproducible in front of an
  audience, at zero cost and with no network.
