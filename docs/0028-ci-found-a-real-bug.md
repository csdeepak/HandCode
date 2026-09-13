---
Number:        0028
Title:         CI Found a Bug That Only Existed on Someone Else's Machine
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-13
Supersedes:    —
Superseded-by: —
Depends-on:    0012, 0021
---

# 0028 — CI Found a Bug That Only Existed on Someone Else's Machine

305 tests, a public repository, and nothing ran them. Everything had only ever
executed on one Windows laptop. The first CI run failed three jobs and found a
real correctness bug in the substitution path.

**308 tests passing.** Fixes in `adapters/openhands/handoff.py`,
`pyproject.toml`. New: `.github/workflows/ci.yml`, `constraints.txt`.

---

## 1. The first run

| Job | |
|---|---|
| `tests` ubuntu 3.13 | ✅ |
| `tests` windows 3.13 | ✅ |
| `tests` ubuntu **3.12** | ❌ 2 failed |
| `tests` windows **3.12** | ❌ 2 failed |
| `pinned` ubuntu / windows | ✅ ✅ |
| `verify` | ❌ install failed |

The Linux jobs passing on 3.13 was the reassuring half. The interesting half
was 3.12 — the floor the README claims and which nothing had ever run.

## 2. `id()` is unique only among LIVE objects

`SubstitutionHandoff` is the mailbox that carries a `SUBSTITUTE` verdict from
Seam B to Seam C. It keyed entries on `id(action)` **while holding no
reference to the action**:

```python
self._by_identity[id(action)] = (call, observation)     # nothing keeps `action`
```

CPython reuses addresses. So a pending action could be collected, an unrelated
action allocated at the same address, and the new one would claim the first
one's entry. Two symptoms, both seen:

- two offers collapse into one — `pending()` returns 1 (the CI failure), or
- **`claim()` returns another call's recorded observation.**

The second is the serious one. The module docstring asserted the opposite:

> *"falling back to a content fingerprint so a mismatch degrades to a missed
> substitution rather than a wrong one"*

That was false for the identity path. A wrong substitution hands the agent a
result for a call that never ran.

The fix keeps the action alive in the entry, which makes its address
unreusable for as long as the entry exists, and re-checks identity with `is`
on read so a stale entry degrades to a miss — which the fingerprint path is
then free to answer correctly.

**This was never a 3.12 bug.** Re-running the new tests against the old code on
3.13 locally also fails. The allocation pattern decides, so the earlier
305-green run was luck. CI on a second interpreter is what converted a latent
flake into a reproducible failure.

## 3. A second bug, in the same function

Fixing the first exposed the second. The fingerprint path cleaned up with:

```python
self._by_identity.pop(id(hit[0]), None)     # hit[0] is the CALL
```

The dictionary is keyed by `id(action)`. Popping `id(call)` removed nothing,
so the identity entry survived a fingerprint claim and could be claimed
again — violating the contract stated three lines above it, that a
substitution is *"honoured exactly once"*.

Both bugs sat in the seam whose entire job is to not return the wrong result.

## 4. The `proxy` extra was never installable

```
litellm[proxy] 1.100.0 depends on mcp<2.0 and >=1.28.1
agentctl[proxy]        depends on mcp>=2.2.0
ERROR: ResolutionImpossible
```

`docs/0021` §7 recorded the hazard — `litellm[proxy]` silently downgrading
`mcp` below what `fastmcp` and therefore the SDK need — and "fixed" it by
adding `mcp>=2.2.0` to the extra. That did not fix it. It made the extra
**uninstallable**, and nobody noticed because the local environment already
had both packages from separate installs that pip never re-resolved.

> A range specifier cannot reconcile two packages that genuinely disagree. It
> can only turn a silent downgrade into a hard refusal.

The conflict is real and the combination works anyway, so the override is now
explicit and two-step, rather than a declaration pip rejects:

```bash
pip install -e ".[dev,openhands,proxy]"
pip install --upgrade "mcp>=2.2.0"      # knowingly past litellm's bound
```

CI asserts the installed `mcp` major version and imports `fastmcp` — the thing
that actually breaks — rather than trusting either package's metadata, because
`pip check` reported nothing the first time this happened.

## 5. A guard that could not fail

With the extra installable, `verify.py` still failed on Linux:

```
ImportError: FastMCP client support is not installed.
```

The proxy install leaves only `fastmcp-slim`, which has no client support,
while the SDK does `from fastmcp import Client` on nearly every import path.
The local machine had both `fastmcp` and `fastmcp-slim` at 4.0.3, so it never
appeared.

The part worth recording is that **a guard written for exactly this hazard
passed anyway**:

```python
import fastmcp      # succeeded, and proved nothing
```

`fastmcp/__init__.py` resolves names lazily through `__getattr__`. Importing
the package always works; only attribute access raises. The assertion could
not fail, so it was decoration.

That is the fifth appearance of one pattern in this project:

| Where | The trap |
|---|---|
| `0014` §5 | A harness failed silently *toward* the hypothesis |
| `0023` §4 | A mock returned a fixed id, so a test could not fail |
| `0024` | A fail-closed gate crashed while its tests passed |
| `0026` §4 | A corpus tuned against its own rules |
| **here** | A guard whose check could not fail |

Written an hour after `0026` restated the rule. Knowing the pattern does not
confer immunity to it.

The step now imports `Client` and then walks the real SDK import chain —
asserting the symbol the dependent code uses, not that a package name resolves.

## 5a. The result

```
PASS  unit tests          9.6s
PASS  nine-point chaos    7.7s
PASS  M0  falsification  27.7s
PASS  M2a gate           11.2s
PASS  M4  probe          11.3s
PASS  M2b substitution   11.9s
PASS  M1  Seam A         11.1s
PASS  FULL STACK         20.6s

all 8 checks passed (111s)   -- ubuntu-latest, CPython 3.13.15
```

Seven jobs green across two operating systems and two interpreters. The
correctness claim now reproduces on a machine that is not mine, which is the
only version of it worth anything.

One detail worth keeping: on Linux the broken runs reported **INCONCLUSIVE**,
not PASS or FAIL, and printed *"an INCONCLUSIVE result is a broken harness,
not a broken system."* The `0012` §6 rule — that a harness must distinguish
"did not happen" from "could not observe" — held up under conditions it had
never seen.

## 6. `constraints.txt`, four months late

`docs/0012` §8 principle 1 has said since the start:

> **Pin everything.** One `constraints.txt` with exact SDK and LiteLLM
> versions. Upgrade deliberately, never incidentally.

It did not exist. Every dependency was `>=`. It exists now: 173 packages, with
`sys_platform` markers on `pywin32` so one file serves both operating systems,
and a `pinned` CI job proving it still reproduces.

## 7. What CI is actually for here

Not the badge. The classifier targets bash and the project was built on
Windows; `docs/0026` §6 admits Windows shells are unhandled, which implies the
reverse was never checked either. And `verify.py` is what this repository asks
strangers to run.

Three jobs, three different questions:

| Job | Question |
|---|---|
| `tests` | does a cold, unpinned install work today, on someone else's machine |
| `pinned` | does the recorded set still reproduce |
| `verify` | does the correctness claim hold on Linux |

Two details that would otherwise fail immediately: CI configures a git identity,
because the chaos suite makes real commits and a runner has git but no author;
and it forces UTF-8, because CI redirects everything and four separate cp1252
bugs came from not doing that (`docs/0012` §6).

## 8. Consequences

- `0021` §7 → its fix was wrong in a way only a clean install could show. This
  supersedes the mechanism, not the finding.
- `0012` §8 → principle 1 is now enforced by a job, not by intention.
- `0012` §6 → new rule: **run the suite on a second interpreter.** A
  single-version green is not evidence about allocation-dependent behaviour.
- `adapters/openhands/handoff.py` → the strong reference is load-bearing and
  documented as such.
