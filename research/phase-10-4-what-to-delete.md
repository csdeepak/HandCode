<!--
Phase 10.4 — What to delete.
Frozen 2026-09-21. Static analysis only. No provider API call was made for
this document. Zero quota spent.

Repo state: main @ b061b05 (`fix: a subagent could read another workspace,
and un-gate Seam C`), on top of 093fb26, 2ab2a74, and b040b72.
595 tests collected locally via `pytest tests/ -q --collect-only`.

Note on method: this document's own research pass (reading the newly-frozen
`research/phase-10-5-subagent-orchestration.md`) surfaced a live confidentiality
bug in `runtime/subagent.py`. Between that reading and this document being
finalized, `b061b05` landed and fixed it — in the same repository, the same
day, independently of this document. §2 V7 and §6 record both the bug this
phase found and the fact that it no longer needs a §6 action, because it was
already taken. The draft is not rewritten to hide that sequence; it is the
most concrete evidence in this document for the executive answer.
-->

# Phase 10.4 — What to Delete

**Frozen 2026-09-21.** Every claim is tiered VERIFIED / INFERRED / UNKNOWN and
cited to `file:line`. This is the one phase of `docs/0037` never run — asked
for twice, recorded as silently dropped by two audits (`docs/0038` §9.1). It
answers the owner's third original ask: *integrate into OpenHands and strip
out the features I don't need.*

---

## 1. Executive answer

**Yes, delete something — but narrowly, and not where the brief expected it.**
`control/matrix/`, `control/replay/`, `kernel/policy.py` and `experiments/`
were named as the likely dead weight, and every one of them turned out to be
load-bearing: `control/replay/` backs `agentctl run --record/--replay` and
`verify.py`'s M6 check; `kernel/policy.py`'s budget, pools and escalation
gates are exercised by `runner.py::_enforce_before_spending` and `verify.py`'s
M7 check; `control/matrix/data/tools.yaml` is the classifier's only input. The
reason the obvious candidates came back clean is that `docs/0038`'s own
seven-item work list and its two audits have, in the single day between
`0038`'s draft and this phase, already closed almost every gap a Phase 10.4
run would otherwise have found — the source picker, the read-only subagent,
the worktree probe test, the concurrency pin, the Groq headroom warning, the
live-pool dashboard read, and the batch-fingerprint correctness bug are all
now in `main`. What *is* left to delete is one precisely-scoped policy
sub-feature that was flagged as unconsumed in `docs/0030` (the M7 decision
document itself, eight documents before `docs/0038`) and has stayed
unconsumed through 17 commits and every document since. Separately, this
phase's own research pass surfaced something more consequential than a
deletion: `runtime/subagent.py`, the newest module in the tree, shipped with
a confirmed cross-workspace confidentiality bug and a default example that
crashed before it reached the network. Between that finding and this document
being finalized, both were fixed on `main` (`b061b05`) — not by this
document's own action, but by the same day's work this phase's reading was
part of. §2 V7 keeps the finding rather than deleting it, because the fact
that it was real, found, and closed within a day is itself the strongest
evidence in this document that the codebase is actively maintained rather
than accumulating exactly the kind of dead weight Phase 10.4 was convened to
find.

---

## 2. VERIFIED

Every item below is direct observation of source in this repository, or of
the installed SDK at `.venv/Lib/site-packages/openhands/`, or a test/CI
artifact already in the repo (T1). File:line citations are exact as of
`093fb26`, except where V7 explicitly re-checks against `b061b05` (HEAD) —
`subagent.py` and `tools.py` changed substantially between the two, and V7
names both states so a citation is never left pointing at superseded code
without saying so.

**V1 — `control/matrix/` as a Python package is empty; the data beside it is
not.** `agentctl/control/matrix/__init__.py` is a zero-byte file. Nothing
imports `agentctl.control.matrix` or `agentctl.control.matrix.data` as Python
(`grep -rn "control.matrix\|control import matrix" agentctl/ tests/
experiments/` outside the directory itself returns no import statement).
`agentctl/kernel/classify.py:20-23` reads `control/matrix/data/tools.yaml` by
raw filesystem path — `DEFAULT_MATRIX = Path(__file__)... / "control" /
"matrix" / "data" / "tools.yaml"` — never through the package. The 149-line
YAML file is the whole capability matrix the classifier, the idempotency-field
lookup (`classify.py:60-67`), and the probe-selection logic
(`kernel/reconcile/base.py:84-86`) all depend on, and 24 tests
(`tests/test_classify.py`, `test_classify_corpus.py`) exercise it. `docs/0013`
§2's *separate* `control/matrix/data/allowances.yaml` (the free-tier
orchestrator's consumption model) does not exist anywhere in the tree —
`find . -iname "*allowance*"` (excluding `.venv`/`.git`) returns nothing. That
feature was designed, never built; there is nothing to delete because nothing
was ever there.

**V2 — `control/replay/` is wired into the normal run path, not just an
experiment.** `agentctl/runtime/runner.py:142,149-150,283-285` imports
`Cassette`, `ReplayServer`, `summarise` from `agentctl.control.replay` on the
`--record`/`--replay` path of `agentctl run`, the command the README documents
as ordinary usage. `agentctl/adapters/litellm/recorder.py:25` imports
`SIGNIFICANT_FIELDS, Cassette` from `control.replay.cassette` — the *same*
list object, not a copy, per `recorder.py:29-31`'s comment about the drift bug
`docs/0029` §4 found. `tests/test_replay.py` (24 tests) and `verify.py`'s "M6
replay" check (`verify.py:50-52` →
`experiments/0008-m6-replay/run_replay.py`) both exercise it. No duplication
with `adapters/litellm/recorder.py`: the module docstrings state the split
explicitly (`control/replay/__init__.py:5-7`: *"the recorder lives in
adapters/litellm/ because it is vendor-specific... cassette.py is pure...
server.py is stdlib only"*), and the code matches — recorder.py writes,
cassette.py defines the format, server.py replays.

**V3 — `kernel/policy.py` and `control/policy/` are consumed for budget,
effects, and pool boundaries, but not for `tiering`.**
`runtime/runner.py:191` calls `pol.requires_approval("DESTRUCTIVE")`;
`runner.py:408` calls `pol.check_budget(...)`; `runner.py:418-422` reads
`pol.default_pool`, `pol.pool(default)`, and `pol.escalation` to gate spending
outside the default pool behind a confirmation prompt. All three are
exercised by `verify.py`'s "M7 policy" check
(`experiments/0009-m7-policy/run_policy.py`), which asserts the budget cap
blocks, escalation asks first, and a broken policy refuses to load
(checks 1-4 in that script), plus 23 tests in `tests/test_policy.py`.

Separately: `kernel/policy.py:157-158`'s `min_tier()` method and
`control/policy/compile.py:220-232`'s `_tiering()` compiler function are the
**only** three sites in `agentctl/` that reference `tiering` at all
(`grep -rn "tiering" --include="*.py" agentctl/` returns exactly those three
plus the one line that writes the compiled key, `compile.py:78`). Nothing
calls `Policy.min_tier()` — not `runner.py`, not `cli.py`'s `cmd_policy`
(`cli.py:620-670`, which prints `effect_rule`, `limit`, `default_pool`,
`pool`, `escalation`, `on_exceeded`, `on_unpriced`, and nothing tiering-shaped),
not `dash.py`. No test in `tests/test_policy.py` names `tiering` or asserts on
the compiled artifact's `tiering` key. `docs/0030-m7-policy.md:142-145`
(ACCEPTED, written at M7, the 30th of the 38 documents in the stream) already
recorded the reason: *"`pools` and `tiering` are declarations. Routing across
a pool is the LiteLLM proxy's job... Which member of a pool gets picked is not
decided here."* The intended consumer — "the proxy's routing loop" — was
checked directly: `agentctl/control/proxy.py`, which generates the LiteLLM
proxy config, contains zero references to `policy`, `Policy`, or `tiering`
(`grep -n "policy\|Policy\|tiering" agentctl/control/proxy.py` — no output).
17 commits after `21c0cc9` (the commit that added `0030`) named the intended
consumer, it still does not exist. The same paragraph in `docs/0030` also disclosed
`escalation.when.or_after_failures` and `.requires_capability`: *"recorded,
not acted on."* Verified still true: `runner.py:418-433`'s escalation block
reads only `esc.get("pool")` and `esc.get("require_confirmation", True)`;
`cli.py:668-670`'s display reads only the same two fields.

**V4 — the shipped default policy declares the dead field.**
`agentctl/control/policy/data/policy.yaml:38-41` ships a `tiering:` block
(`planning: {min_tier: strong}`, `edit: {min_tier: mid}`, `read: {min_tier:
cheap}`) as part of what its own header comment calls *"the real daily
driver"* (`policy.yaml:1`). A user who reads this file to learn what the
policy system does will conclude tiering is enforced. It is compiled,
validated, and then never read again.

**V5 — every item in `docs/0038` §7's seven-item work list has landed.**
Checked against `git log --oneline -12` and the corresponding code:

| # | `0038` §7 item | Landed at | Evidence |
|---|---|---|---|
| 1 | Fix the batch false-`LANDED` bug | `c8113f3` | `kernel/ledger/store.py:221-226` (`write_intent`'s fence), `tests/test_batch_ordering.py` (5 tests) |
| 2 | Pin `tool_concurrency_limit=1` explicitly | `17207c3` | `runtime/runner.py:40-65` (`_build_agent`, raises if the pin does not take), `tests/test_tool_concurrency_pin.py` |
| 3 | Confirm Groq's 413 and report it in `doctor` | `17207c3` | `runtime/doctor.py:53-116` (`_groq_headroom`), `tests/test_doctor_groq_prefix.py` |
| 4 | Land the worktree probe test | `17207c3` | `tests/test_worktree_probe.py` (4 tests, including 120 concurrent commits) |
| 5 | `modify_params: true` | `17207c3` | `control/proxy.py:287` |
| 6 | `dash` reads `/model/info` | `17207c3` | `control/dash.py:88-178` (`_providers`, source-tagged) |
| 7 | OpenRouter quota in `dash` | `17207c3` | `control/dash.py:261-290` (`_quota` → `probe.py::openrouter_quota`) |

Plus two items `docs/0038` §9.1 flagged as *asked for but dropped from the
work list*, now also landed: the source picker (`b040b72`;
`control/proxy.py:44,139-165` `sources()`/`SOURCE_PREFIX`; `cli.py:227-250`
`cmd_run --source`; `cli.py:494-554` `cmd_models`; `tests/test_source_picker.py`,
10 tests) and the read-only subagent (`2ab2a74`; `runtime/subagent.py`;
`cli.py:428-493` `cmd_subagent`; `tests/test_subagent.py`, 13 tests at that
commit). A ninth change, `093fb26`, hardened `control/probe.py::check_inference`
to poll every account instead of one and fixed a payment/rate-limit
misclassification order bug — not on `0038`'s list, found by the owner's own
dogfooding of `agentctl proxy --verify`. Nothing left unaddressed by the
seven-item list was left as scaffolding; the things that were unfinished are
now built. A tenth change, `b061b05`, landed *during this phase's research*
and is treated separately at V7 because of that timing.

**V6 — `runtime/subagent.py` is reachable, covered by 15 tests including two
that are mutation-checked, but still not exercised by `verify.py` or against
a live model.** Reachable from `agentctl subagent <name> "<task>"`
(`cli.py:428-493`). `tests/test_subagent.py` (15 tests as of `b061b05`, up
from 13) covers `validate()`, `discover()`, `rejection()`, that the tool list
handed to the agent comes from the `READ_ONLY_TOOLS` constant rather than
`definition.tools` (`test_subagent.py:71-86`), and — new in `b061b05` — that
`register_all(overwrite=False)` cannot clobber an existing (gated)
registration, and that the scoped workspace is restored on every exit path,
including a raise inside `_build_agent` before a `Conversation` exists. The
commit message states one of the older tests "passed for the wrong reason":
it compared the scoped workspace to a value an earlier test in the same file
had already leaked to the same path, so it stayed green whether or not the
fix under test worked at all (the shape `docs/0024` names). It was rewritten
against a sentinel value instead. Unchanged by any of this: `subagent` still
does not appear in `verify.py`'s `CHECKS` list (`grep -n "subagent" verify.py`
— no output), unlike every other milestone `verify.py` names (V5's table: M0,
M1, M2a, M2b, M4, M6, M7, plus the nine-point suite and the full-stack
check), each of which has a dedicated zero-cost experiment script. Every test
in `test_subagent.py` stubs the LLM/Conversation boundary; no test in the
repository drives `subagent.run()` to a real or even a locally-mocked-HTTP
completion, and the mutation-checked tests prove the *fix* holds, not that
the feature works end to end.

**V7 — a bug this phase's own reading surfaced was real, and was fixed on
`main` before this document was finalized.**
`research/phase-10-5-subagent-orchestration.md` (frozen 2026-09-21, nine local
zero-cost experiments E1-E9, CONVENTIONS.md-frozen, T1 for this document)
found three defects in `runtime/subagent.py` as it stood at `093fb26`.
Checked again just now against the current `subagent.py` and `tools.py`: all
three are fixed, in `b061b05`, whose own commit message independently
describes the same two-agent, local-stub-provider experiment method
`phase-10-5` used, and lands the same three fixes `phase-10-5` §5.4 specified
almost line for line.

- **The shipped `--init` example could not run (E5) — fixed.** At `093fb26`,
  `EXAMPLE_SUBAGENT`'s `model: inherit` collapsed to `LLM(model=None)` with no
  `--model` default, raising a pydantic `ValidationError` before any network
  call. Current `subagent.py:194-195`: `chosen = (model or DEFAULT_MODEL) if
  declared in ("inherit", "", None) else declared`, falling back to
  `runner.DEFAULT_MODEL` (`runner.py:37`,
  `"openrouter/nvidia/nemotron-3-super-120b-a12b:free"`). No `--model` is
  needed for the command `--init` prints to run.
- **`AGENTCTL_WORKSPACE` leaked between workspaces, confirmed with two real
  agents and a local stub provider (E7) — fixed.** At `093fb26`, `subagent.py`
  set the process-global `os.environ[WORKSPACE_ENV]` and never restored it,
  so a concurrent subagent scoped to one workspace read another's file and
  reported it with no error, and the same leak reproduced sequentially with
  no threads at all (E4). Current `tools.py:60-69` defines
  `_scoped_workspace: ContextVar[str | None]`, checked by `_workspace()`
  before falling back to the env var; current `subagent.py:162-170` sets it
  with `rt._scoped_workspace.set(str(ws))` inside a `try`/`finally` that
  resets it on every exit path, "even when construction fails" per its own
  comment — closing exactly the gap `phase-10-5` §5.4's Fix A specified (a
  bare `try/finally` around the body, not just around `conv.run()`).
  `tests/test_subagent.py::test_the_subagent_workspace_does_not_leak_back_to_the_parent`
  now guards it, deliberately raising inside `_build_agent` to prove the
  `finally` fires before a `Conversation` exists.
- **`rt.register_all()` un-gated Seam C's tools under the same names (E8) —
  fixed.** At `093fb26`, `register_all()` took no arguments and
  unconditionally re-registered plain tool classes, silently overwriting
  whatever `protect()` had registered under the same names, because the SDK's
  `register_tool` replaces a duplicate with only a log warning (its own
  source carries a `TODO` to raise instead, per the fix commit's own
  description). Current `subagent.py:151`: `rt.register_all(overwrite=False)`;
  current `tools.py:324`: `def register_all(overwrite: bool = True) -> list[str]`,
  skipping any name already registered when `overwrite=False`. Guarded by
  `tests/test_subagent.py::test_registering_plain_tools_never_un_gates_seam_c`.
- **No key discovery, no proxy placeholder (E6) — fixed, plus `--source`
  landed (matching `phase-10-5` §7's step 4, not merely step 1).** Current
  `subagent.py:196-206` calls `runner._key_for(chosen)` when no `base_url` is
  given, and substitutes `"proxy-holds-the-credentials"` when one is —
  mirroring `runner.py:154-164`'s own logic, which `093fb26`-era `subagent.py`
  did not call at all. `cli.py`'s `subagent` parser now takes `--source`
  (`cli.py`, the `sa.add_argument("--source", ...)` block), the same
  provider-pinned-with-failover mechanism `cmd_run --source` already used
  (V5), which `phase-10-5` §7's build order priced as step 4, after the
  blockers.

**What this means for §5 and §6:** none of V7's four fixed items changes
`runtime/subagent.py`'s verdict — it was KEEP before this phase and remains
KEEP. What it does mean is that the DELETE #2 this document originally drafted
("stop advertising `agentctl subagent` as ready") was overtaken by events
between being drafted and being finalized, and is recorded at §6 as resolved
rather than removed from the record.
- **`rt.register_all()` un-gates Seam C's tools under the same names
  `protect()` gated (E8).** Latent today because `agentctl run` finishes
  registering before a subagent could run, and `Agent` locks its tool list
  once initialized — but the same shape `docs/0038` §4.3 closed for the
  concurrency pin, left open here.

None of this is an argument to delete `runtime/subagent.py` — `phase-10-5` §7
verdicts it fixable in roughly a day (§5.4, a ~130-line, test-guarded plan
already specified) and it remains the architecturally correct, cheap slice of
multi-agent `docs/0038` §4.4 named. It is an argument that the module's
current CLI-level advertisement ("the example works, try it") overstates what
is safe to run today.

**V8 — `README.md`'s test count is stale, the exact class of drift this
project's own audits keep catching.** `README.md:12` and `README.md:309` both
say "507 tests." `pytest tests/ -q --collect-only` on this checkout (HEAD =
`093fb26`) collects **593**. `093fb26`'s own commit message — the tip commit
of this very checkout — states "592 tests." The three-way discrepancy (507
documented / 592 stated in HEAD's own message / 593 measured here) is not
investigated further in this document — it is
recorded because `docs/0038` §9 exists precisely to catch this shape of claim,
and a document about what to delete should not itself repeat an unmeasured
number.

**V9 — `pyproject.toml`'s packaging makes `control/matrix/__init__.py`
non-trivial to delete, contrary to first appearance.**
`pyproject.toml:42-46` uses `[tool.setuptools.packages.find] include =
["agentctl*"]` with no `find_namespace_packages`/`namespaces = true`
directive, which means setuptools' classic package discovery applies:
a directory without `__init__.py` is not a package and is not installed.
`pyproject.toml:46` separately declares `"agentctl.control.matrix.data" =
["*.yaml"]` under `[tool.setuptools.package-data]`, naming a directory
(`control/matrix/data/`) that itself has no `__init__.py` and is not a
package by that same rule — so the existing packaging metadata is already
slightly inconsistent, and untested by anything in this repository, because
the only documented install path is `pip install -e ".[dev,openhands]"`
(`README.md:41`), and an editable install does not go through
`packages.find`/`package-data` the way a built wheel does. Deleting
`control/matrix/__init__.py` would not change anything for the only install
path this project exercises, but would be an *unverified* change for a
hypothetical future non-editable build. This is the one place in this phase
where a change that looked free on first read was not verified free.

---

## 3. INFERRED

**I1 — the docs/ stream's reading-cost tax is real but not yet binding.** 38
numbered documents (`0001`-`0038`, confirmed no gaps and no duplicate numbers:
`ls docs/*.md | sed -E 's/.*\/([0-9]{4})-.*/\1/' | sort | uniq -d` returns
nothing), ~9,100 lines total (`wc -l docs/*.md`), zero currently `SUPERSEDED`
(`0002` predates the front-matter convention entirely and has none — a gap in
the convention's own history, not a live problem). `INDEX.md`'s own reading
order claims ~40 minutes for a new contributor (`0001`→`0007`→`0008`→`0011`).
Inferred, not measured: at the current growth rate (38 documents in roughly
two weeks of project time, per the `Created` dates), a "digest" REGISTER
document — not a deletion, `CONVENTIONS.md` correctly forbids that — becomes
worth building somewhere past 50-60 documents, when the reading order itself
would need its own summary of summaries. Not there yet. `CONVENTIONS.md`'s
rule is still serving the project: this document itself depends on being able
to cite `0030`, an eight-documents-old ACCEPTED decision from M7, and having
it frozen and never edited in place is exactly why the "recorded, not acted
on" sentence was still there, word for word, to find.

**I2 — `experiments/0007-real-provider/` and `experiments/0010-dogfood/` are
historical evidence, not regression tests, and should not be graded as
either.** Both are absent from `verify.py`'s `CHECKS` list (`grep -n
"0007-real-provider\|0010-dogfood" verify.py` — no output), require real
provider keys, and cost real tokens. Both are the source scripts behind
ACCEPTED decision documents (`docs/0023` cites `0007-real-provider`;
`docs/0035` cites `0010-dogfood`). `CONVENTIONS.md`'s directory table
designates `experiments/` for exactly this: "scripts, configs, and logs for
reproducible experiments" — a category distinct from `tests/`. Inferred
verdict: keep both, but the project's own `verify.py` docstring ("zero
cost... everything runs against a local mock provider") does not describe
them, and nothing currently says so at the point a new contributor would find
them. A one-line `README.md` in each directory stating "not part of
`verify.py`; requires live keys; frozen evidence for `docs/00NN`" would cost
nothing and close a real, if minor, gap between what `verify.py`'s green
checkmark promises and what these two scripts are.

**I3 — `experiments/0006-full-stack/run_full_stack.py` and
`experiments/0007-real-provider/run_real.py` construct `Agent(...)` directly,
bypassing the concurrency pin `runner.py::_build_agent` enforces.** VERIFIED
at the file level (`run_full_stack.py:111-113`, `run_real.py:116-118`: `agent
= Agent(llm=llm, tools=[...], include_default_tools=[])`, no
`tool_concurrency_limit` argument, no call to `_build_agent`); INFERRED as a
live risk because `run_full_stack.py` **is** in `verify.py`'s `CHECKS`
(`verify.py:48-49`, the "FULL STACK" check) and therefore runs on every
`verify.py` invocation without exercising the pin that
`test_tool_concurrency_pin.py` exists to guard. This matches `docs/0038`
§4.3's own finding about the hazard being latent because nothing has raised
the limit yet — here it is latent for a different, adjacent reason: the
check that is supposed to prove the "correctness core" end to end constructs
its `Agent` through a different path than the one real users go through
(`agentctl run` → `runner.py::run` → `_build_agent`). Not a deletion
candidate — a correctness-test gap worth a follow-up, named here because the
brief specifically asked whether these scripts are "documentation, regression
tests, or liabilities," and the honest answer for these two is "a regression
test with an unexercised gap in exactly the property the rest of the project
is most careful about."

**I4 — the owner's "39-document" framing in the brief is off by one against
what exists.** `0037`'s own text is not being second-guessed here (it was not
re-read for this claim); the brief handed to this phase said "the 39-document
`docs/` stream." `ls docs/*.md | wc -l` returns 38. Immaterial to any verdict
in this document, recorded because the brief itself says "several claims in
`docs/0038` were found false by exactly [not re-verifying counts]," and a
one-off count is the cheapest possible thing to get wrong twice in the same
project.

---

## 4. UNKNOWN

**U1 — whether the packaging inconsistency in V9 has ever mattered in
practice.** No evidence either way was sought beyond reading `pyproject.toml`
and confirming the only documented install path is editable. Whether a CI job
or a downstream consumer ever does a non-editable build is not knowable from
this repository alone.

**U2 — whether any user has actually run `agentctl subagent` against a live
provider and hit the bugs `phase-10-5` found statically.** `phase-10-5`'s
experiments are all local/mocked; this document adds no new evidence here.
The `.agentctl/conversations/9a86c1bb19054b558ed54a652e3957fc/` directory
present in the working tree (one conversation, `base_state.json` plus an
`events/` subdirectory) shows `agentctl run` has been used for real at least
once; it does not establish whether `agentctl subagent` specifically has.

**U3 — whether deleting the `tiering` YAML block from the shipped
`policy.yaml` example, without deleting the compiler support, would be
sufficient instead of removing the compiler code.** This document recommends
removing both (§6); a narrower fix (leave `_tiering()`/`min_tier()` in place,
just stop shipping the example block) was not costed and is not ruled out.

---

## 5. Component table

Verdict definitions per the brief: **KEEP** (load-bearing) / **KEEP BUT
UNUSED** (correct, currently dead, named future consumer) / **DELETE** (cost
exceeds value) / **EXTRACT AS LIBRARY** (valuable, not this project's job).
Test counts are `grep -c "^def test_"` per file, current checkout.

### `kernel/` — in-band, must not fail

| Module | Verdict | Evidence |
|---|---|---|
| `ledger/models.py` | **KEEP** | Core types (`EffectClass`, `ToolCall`, `EffectState`), imported by every other kernel module and by `cli.py:32-33`. No I/O, the module's own docstring states it is "imported by everything in the kernel." |
| `ledger/store.py` | **KEEP** | The durable, fsynced, fenced SQLite ledger — `docs/0012` §2.1/§3.1. `kernel/gate.py:26` imports `LedgerStore`; 14 tests (`test_ledger.py`); exercised by every M-series `verify.py` check. |
| `classify.py` | **KEEP** | The tool→`EffectClass` classifier; reads `control/matrix/data/tools.yaml` by path (V1). 9+6=15 tests across `test_classify.py`/`test_classify_corpus.py`; used by `gate.py`, `runner.py`, `subagent.py`, every experiment script. |
| `gate.py` | **KEEP** | "The correctness core, and deliberately small" per its own docstring. 20 tests (`test_gate.py`); the subject of the M2a/M2b/nine-point/full-stack `verify.py` checks. |
| `hook.py` | **KEEP** | Seam A logic. Bound to LiteLLM via `adapters/litellm/hook.py:14,19`; that binding is written into every generated proxy config by `control/proxy.py:369-380` (`HOOK_MODULE`), so Seam A is live in ordinary `agentctl proxy` usage, not only in the M1 experiment. 20 tests (`test_hook.py`); "M1 Seam A" `verify.py` check. |
| `paths.py` | **KEEP** | `escaping_writes()`, the `--confirm-destructive` mechanism (`docs/0027`). Called from `runner.py:309`. 20 tests (`test_paths.py`). |
| `policy.py` | **KEEP**, with one dead sub-feature | Budget/effects/pools/escalation.pool/escalation.require_confirmation are all read by `runner.py` and exercised by the M7 `verify.py` check (V3). `min_tier()`/`tiering` are compiled, validated, never read (V3, V4) — see §6 DELETE #1. |
| `reconcile/base.py` | **KEEP** | `ProbeRegistry`, `ReconciliationProbe` base, the "prefer the named probe" logic `classify.py`'s matrix drives. Imported by `gate.py:16-18`. |
| `reconcile/external.py` | **KEEP** | `IdempotencyProbe` — the only recovery path for `EXTERNAL` effects (`docs/0020`). 13 tests (`test_external.py`), including `test_matrix_declares_the_key_field`. |
| `reconcile/filesystem.py` | **KEEP** | `FileAppendProbe`, one of the two chaos-tested effect kinds (nine-point suite). |
| `reconcile/git.py` | **KEEP** | `GitProbe`, `docs/0017`, made worktree-aware by `17207c3` after `c8113f3`'s batch-fingerprint fix exposed the single-writer assumption. 4 dedicated tests (`test_worktree_probe.py`) plus coverage in `test_reconcile.py`. |

### `control/` — out-of-band, may fail

| Module | Verdict | Evidence |
|---|---|---|
| `matrix/__init__.py` | **KEEP** (unexpectedly) | Zero-byte, zero Python imports of it anywhere (V1) — looks like free deletion. Verified NOT free: `pyproject.toml`'s classic `packages.find` requires `__init__.py` to discover `agentctl.control.matrix` as installable, which is what makes `control/matrix/data/tools.yaml` shippable in a non-editable build (V9). Kept because deleting it is an unverified risk for zero measured benefit — an empty file costs nothing to leave. |
| `matrix/data/tools.yaml` | **KEEP** | The capability matrix itself. Load-bearing per V1; see `kernel/classify.py`. |
| `replay/cassette.py`, `replay/server.py`, `replay/__init__.py` | **KEEP** | M6, `docs/0029`. Wired into `agentctl run --record/--replay` (V2). 24 tests (`test_replay.py`); "M6 replay" `verify.py` check. No duplication with `adapters/litellm/recorder.py` (V2). |
| `policy/__init__.py`, `policy/compile.py` | **KEEP**, with the same dead sub-feature as `kernel/policy.py` | Compiles `pools`/`budget`/`effects`/`escalation.pool`/`escalation.require_confirmation`, all consumed (V3). `_tiering()` and `escalation.when.{requires_capability,or_after_failures}` are compiled and validated, never read anywhere (V3) — see §6 DELETE #1. |
| `cost/ledger.py` | **KEEP** | `CostLedger`; `cli.py`'s `cmd_cost`/`cmd_ingest`; consumed by the M7 policy check's budget arithmetic. 14 tests (`test_cost.py`). |
| `keys.py` | **KEEP** | `agentctl keys` (init/check/install-hook), `docs/0032`/`0033`. 404 lines; part of 43 tests in `test_keys_and_dash.py`. |
| `dash.py` | **KEEP** | `agentctl dash`, the four panels `docs/0013` §3 specified. Now reads `/model/info` and OpenRouter quota live (V5, item 6-7). 659 lines; 20 tests (`test_dash_proxy.py`) plus part of `test_keys_and_dash.py`. |
| `probe.py` | **KEEP** | Connectivity checks behind `agentctl keys --check` and `agentctl proxy --verify` (`cli.py:358,375`). `check_inference` rewritten in `093fb26` to poll every account and fix a classification-order bug (V5). 18 tests (`test_probe.py`) plus new `test_probe_accounts.py` (130 lines added in `093fb26`). |
| `providers.py` | **KEEP** | "One registry, the single source of truth" (its own docstring, citing `docs/0029` §4's drift finding). Used by `cli.py`, `doctor.py`, `probe.py`, `proxy.py`. |
| `proxy.py` | **KEEP** | Generates the LiteLLM proxy config, now with source groups (`b040b72`). 449 lines; 18 tests (`test_proxy_config.py`) + 10 tests (`test_source_picker.py`). |

### `adapters/` — harness-specific, the portability cost

| Module | Verdict | Evidence |
|---|---|---|
| `openhands/__init__.py` (`protect()`) | **KEEP** | The library's main entry point; the README's "or embed it" example calls it directly. |
| `openhands/seam_b.py` | **KEEP** | Block/escalate binding via `ConversationState.block_action`. Core to the correctness claim. |
| `openhands/seam_c.py` | **KEEP** | Substitution binding; site of the `c8113f3` batch-fingerprint fix. 5 dedicated tests (`test_seam_c.py`) + `test_batch_ordering.py`. |
| `openhands/handoff.py` | **KEEP** | `SubstitutionHandoff`, imported by `seam_c.py:35` and referenced in `runtime/subagent.py`'s own docstring as one of the four things multi-agent would need to fix. |
| `litellm/hook.py` | **KEEP** | Seam A's LiteLLM binding (V5, item 1 in the how-it-works table). Written into every generated proxy config by `control/proxy.py`. |
| `litellm/recorder.py` | **KEEP** | Cassette recording for `--record`; not a duplicate of `control/replay/` (V2). |

### `runtime/`

| Module | Verdict | Evidence |
|---|---|---|
| `runner.py` | **KEEP** | `agentctl run`'s implementation; 493 lines; the thing every other module ultimately serves. |
| `tools.py` | **KEEP**, secondary **EXTRACT AS LIBRARY** flag | The minimal bash/read/write toolset, deliberately not `openhands-tools` (avoids ~55 transitive dependencies per its own docstring). Load-bearing here; also generically useful to any `openhands-sdk` user who wants a lean toolset independent of the ledger/gate. Not proposed for removal from this repo — flagged as a candidate for its own package once this project has spare capacity, the same "not this project's job, eventually" logic `docs/0013` §7 applies to the kernel. |
| `doctor.py` | **KEEP** | `agentctl doctor`, preflight checks including the Groq headroom warning added in `17207c3`. 312 lines; 29+2 tests. |
| `subagent.py` | **KEEP** | Reachable via `agentctl subagent` (`cli.py:428-493`); 15 mocked tests including 2 mutation-checked ones. `research/phase-10-5-subagent-orchestration.md` found a crashing default example, a cross-workspace confidentiality leak, and a Seam-C gate bypass at `093fb26`; all three were fixed at `b061b05`, landed during this phase's own research (V7). Still absent from `verify.py`'s `CHECKS` and still never driven against a live or locally-mocked completion (V6) — the one gap this phase leaves open rather than closes. The architecture matches `docs/0038` §4.4's "affordable slice" verdict. |

### `experiments/` (11 directories)

| Directory | Verdict | Evidence |
|---|---|---|
| `0000-falsification`, `0001-m2a-chaos`, `0002-m4-probe`, `0003-m2b-substitute`, `0005-m1-seam-a`, `0006-full-stack`, `0008-m6-replay`, `0009-m7-policy` | **KEEP** | Each is a named `verify.py` check (V5's table plus M0/M2a/M4/M2b entries), zero cost, real regression tests. |
| `0004-nine-point` (`worker.py`) | **KEEP** | Wrapped by `tests/test_chaos_nine_point.py`, itself a dedicated `verify.py` check. |
| `0007-real-provider` | **KEEP, not a regression test** | Not in `verify.py` (I2). Frozen evidence behind `docs/0023` (found a real duplicate, corrected the `tool_call_id` assumption). Constructs `Agent(...)` directly, bypassing the concurrency pin (I3) — a latent risk in the *script*, not grounds to remove the script. |
| `0010-dogfood` | **KEEP, not a regression test** | Not in `verify.py` (I2). Frozen evidence behind `docs/0035` (the agent fixed its own repository). |

### `docs/` (38 documents) and `research/` (5 files)

| Item | Verdict | Evidence |
|---|---|---|
| The numbered `docs/` stream | **KEEP, in full** | `CONVENTIONS.md` rule 3: never deleted. 38 documents, ~9,100 lines, zero currently `SUPERSEDED`, curated reading order in `INDEX.md` (I1). The rule is still earning its cost — this document's own §3/V3 finding depended on `docs/0030` being frozen and unedited. |
| `research/phase-10-1a/1b/2/3` | **KEEP** | Frozen per `CONVENTIONS.md`'s RESEARCH type; the primary sources `docs/0038` interprets. |
| `research/phase-10-5` | **KEEP** | Frozen, cited extensively above (V6, V7); the most consequential single source this document used that was not explicitly named in the brief. |

### Top level

| Item | Verdict | Evidence |
|---|---|---|
| `verify.py` | **KEEP** | The zero-cost proof of the correctness core; 10 checks (V5's table plus unit tests and nine-point chaos). |
| `cli.py` | **KEEP** | 838 lines, the single entry point for every subcommand this table verifies as reachable. |
| The `kernel/` correctness core as a whole (ledger + gate + reconcile + classify) | **KEEP**, secondary **EXTRACT AS LIBRARY** flag | `docs/0013` §7 already names this: "Effect-safety as a standalone library — plausibly the most reusable thing here, and worth extracting once M4 proves it." M4 is proven (`docs/0017`, the M4 `verify.py` check, green). Not proposed for removal from this repo — the charter (`docs/0001`) makes effect safety the whole point — flagged because the project's own forward-looking document already made this call and nothing since has overturned it. |

**Verdict counts:** 31 modules/directories tabulated. **KEEP: 29. KEEP with a
named dead sub-feature: 2** (`kernel/policy.py`, `control/policy/`, counted
once each above but sharing one root cause). **DELETE: 0 whole modules** — the
one deletion this phase found (§6) is a sub-feature inside two already-KEEP
modules, not a module in its own right. **EXTRACT AS LIBRARY (secondary flag,
not primary verdict): 2** (`kernel/` correctness core, `runtime/tools.py`).

---

## 6. The DELETE list

Ordered by confidence. Every item accounts for the tests that go with it, per
the standing constraint. Two items are live recommendations; the middle slot
is kept as a resolved item rather than renumbered away — see its entry for
why.

### DELETE #1 — the `tiering` policy sub-feature and the two inert
`escalation.when` fields (HIGH confidence)

**What:** `control/policy/compile.py:78` (the `out["tiering"] = _tiering(raw,
problems)` line), `compile.py:220-232` (the `_tiering()` function),
`kernel/policy.py:157-158` (`min_tier()`), the `tiering:` block in
`control/policy/data/policy.yaml:38-41`, and — same root cause, same fix —
`compile.py:125-129`'s validation of `escalate_to.when.or_after_failures` and
`.requires_capability`, plus their fields in the compiled `escalation` dict
(`compile.py:130-138`).

**Why it is safe:** V3 establishes zero runtime consumers on either side —
neither `kernel/policy.py`'s own reader methods nor the intended consumer
`docs/0030` named (`control/proxy.py`, "the proxy's routing loop") ever call
`min_tier()` or read `escalation.when.*`. V3 also establishes zero test cost:
no test in `test_policy.py` names `tiering` or asserts on
`escalation.when.requires_capability`/`.after_failures`; every test that
implicitly exercises `_tiering({})` → `{}` (because `compile_policy` always
calls it) keeps passing with the function removed and the key simply absent
from the output dict, since nothing asserts the key's presence either.

**What is lost:** the *appearance* that tiering and escalation triggers are
policy-enforced. `docs/0030` already said, in the ACCEPTED decision document
itself, that they are not — "declarations," "recorded, not acted on." Nothing
that currently works stops working. The shipped `policy.yaml` example becomes
honest about what it actually does.

**Cost of the removal itself:** roughly 25 lines across two files, one YAML
edit. `policy.yaml` is not a numbered `docs/` document — `CONVENTIONS.md`'s
"never delete" rule does not apply to it — so it can be edited in place.

**What is NOT recommended:** removing `pools`, `routing.default_pool`, or
`escalation.pool`/`.require_confirmation`. Those are read, tested, and
exercised end to end by the M7 `verify.py` check (V3).

### DELETE #2 (RESOLVED before this document was finalized) — was: stop
advertising `agentctl subagent` as ready

**What this originally targeted:** the implicit promise in `cli.py`'s
`--init` hint and in `cmd_subagent` generally, that the command was ready to
use today, given V7's findings against `093fb26`: a confirmed cross-workspace
confidentiality leak and a default example that crashed before it reached the
network.

**Why it is not a live recommendation:** by the time this document was
finalized, `b061b05` had fixed all three defects V7 found (workspace leak,
Seam-C gate bypass, the crashing default) and shipped two mutation-checked
regression tests for the first two. There is nothing left to hide behind a
"do not advertise" caveat — re-verified directly against the current source
in V7, not assumed from the commit message. This slot is kept, rather than
silently dropped, because a document about drift should show its own drift
being caught and closed rather than erase the trace.

**What remains, and is not itself a DELETE:** `runtime/subagent.py` still has
no `verify.py` check and has never been driven to a real or locally-mocked
completion end to end (V6). That is a coverage gap to close with a new
zero-cost `verify.py` entry, in the shape of `experiments/0008-m6-replay`
against a stub endpoint — not a deletion, and not scoped further here because
it was not this phase's question.

### DELETE #3 — the stale test-count claim in `README.md` (LOW confidence as
a priority, HIGH confidence as correct)

**What:** `README.md:12` and `README.md:309`, both currently reading "507
tests."

**Why:** V8 — measured 593 tests against `093fb26`, rising to 595 against
`b061b05` (HEAD's own commit message says 594) purely from the fixes and
tests landed *during this phase*. `README.md` is `LIVING`, not a numbered
`docs/` document, so `CONVENTIONS.md`'s edit restriction does not apply and
there is no reason for the number to be stale at all — nor, evidently, to
stay accurate for more than a few hours in a repository moving this fast.

**Cost:** two one-line edits. Included in this list because it is the exact
shape of claim `docs/0038` §9 was built to catch, and a "what to delete"
document that leaves a known-false number sitting in the file everyone reads
first would be repeating the mistake it exists to prevent.

---

## 7. What "strip unneeded features" means here

**The ask, taken literally, is not coherent, and the reason is not
pedantic — it is the exact confusion this phase exists to resolve.**
"OpenHands" the application — a FastAPI server with its own UI — is not
vendored, copied, or included anywhere in this repository. `docs/0038` §6
already established that the OpenHands application, if it were somehow in
scope, would be dropped outright: it pins `openhands-sdk==1.34.0`, eleven
releases behind what this project uses, and "has no agent loop." There is no
OpenHands installation, configuration, or UI in this codebase to strip
features *from* in the sense the phrase would mean for, say, a VS Code fork
where you delete panels and menu items from someone else's application.

What actually exists is `openhands-sdk` (`pyproject.toml:14`:
`openhands = ["openhands-sdk>=1.45.0"]`), declared as an optional pip
dependency, imported piecemeal by function and class name —
`from openhands.sdk import LLM, Conversation` (`runtime/subagent.py:136`),
`ToolDefinition`, `AgentDefinition`, `load_agents_from_dir`
(`runtime/subagent.py:107`), and so on — from inside `agentctl/adapters/
openhands/` and `agentctl/runtime/`. Nothing about a pip dependency can be
"stripped": Python does not pay for code it does not call beyond the cost of
importing the package once, which this project already accepts as the price
of the `openhands` extra. There is no partial-uninstall operation that would
do anything meaningful here.

So the ask, translated into something this repository can actually answer, is
one of two questions, and this document answers both:

1. **"Reduce agentctl's own surface — the code this project wrote."** §5's
   component table is the answer, and the honest result is that there is
   almost nothing to strip: 29 of 31 tabulated components are load-bearing,
   evidenced module by module against imports, `verify.py` reachability, and
   CLI reachability. The one real reduction (§6, DELETE #1) is a policy
   sub-feature that `docs/0030` already recorded as inert, 17 commits and 8
   documents ago, and nothing since has consumed it.
   `docs/0007` — the Phase 0 decision this brief holds up as the standard to
   match — deleted two whole components because two whole components were
   genuinely unused at that point in the project's life. This project is
   38 documents further along, and the gaps `0007`-style deletion would have
   found have, in the day between `docs/0038`'s draft and this phase running,
   already been closed by 9 landed commits (`git rev-list --count
   2f534d3..HEAD`, from the research-and-decision commit through `b061b05`;
   V5 and V7 account for what each one fixed, including one landed while this
   phase was running) rather than left to be found here.

2. **"Call less of the SDK's own surface."** This is already true almost
   everywhere, not because anyone deleted anything, but because `agentctl`
   never opted in. `docs/0038` §2's own table lists four SDK capabilities
   ("Pre-tool hook that can refuse," "Claude Code plugin manifests,"
   "Parallel tool execution," and the subagent *runtime* as opposed to its
   format) that ship in the dependency and are called from `agentctl` nowhere
   — re-checked at HEAD: `grep -rn "PRE_TOOL_USE\|HookDecision\|claude_code"
   agentctl/` returns zero hits, and `parallel_executor` returns exactly one,
   `runtime/tools.py:55`, which is a comment explaining *why* the workspace
   fix (V7) uses a `ContextVar` — "the SDK's parallel executor copies the
   calling context into each worker thread" — not a call into that executor.
   Reading about a capability to explain a design choice is not calling it.
   The one actual opt-in, and the only SDK surface this project has *grown
   into* since `0038` was drafted, is `AgentDefinition` / `load_agents_from_dir`,
   called by `runtime/subagent.py` for the read-only subagent — a single,
   narrow, deliberately-scoped opt-in, not a drift toward using more of the
   SDK than needed.

There is no third reading under which the owner's ask points at code that
exists and is safe to delete. The owner's intuition that something should be
smaller was not wrong on its own terms — it is answered here — but the
target it was pointed at does not exist in this repository.

---

## 8. Sources

### T1 — source code, this repo @ `093fb26` (unchanged by `b061b05`)
`agentctl/kernel/classify.py:1-67`; `agentctl/kernel/gate.py:1-30`;
`agentctl/kernel/policy.py:1-164`; `agentctl/kernel/paths.py`;
`agentctl/kernel/reconcile/__init__.py`, `base.py`, `external.py`,
`filesystem.py`, `git.py`; `agentctl/kernel/ledger/store.py:221-260`;
`agentctl/control/matrix/__init__.py` (0 bytes); `agentctl/control/matrix/
data/tools.yaml`; `agentctl/control/replay/__init__.py:1-15`, `cassette.py`,
`server.py`; `agentctl/control/policy/compile.py:1-250`; `agentctl/control/
policy/data/policy.yaml:1-46`; `agentctl/control/probe.py:1-333`;
`agentctl/control/proxy.py:44,139-165,275-380`; `agentctl/control/dash.py:
17-290`; `agentctl/adapters/litellm/hook.py`, `recorder.py:1-31`;
`agentctl/adapters/openhands/__init__.py`, `handoff.py`, `seam_c.py:35`;
`agentctl/runtime/runner.py:37,40-65,132,142-164,177,191,268,283-285,309,
340-433`; `pyproject.toml:1-46`; `.github/workflows/ci.yml`;
`verify.py:25-56`; `README.md:1-355`; `tests/test_boundaries.py`.

### T1 — source code, this repo @ `b061b05` (HEAD; re-checked specifically
for V6/V7 because these two files changed materially)
`agentctl/runtime/subagent.py:127-227` (full `run`/`_run_scoped`); `agentctl/
runtime/tools.py:38-69,324` (`_scoped_workspace`, `_workspace`,
`register_all`); `agentctl/cli.py:227-670,719,755-775,823` (the `--source`
argument on the `subagent` parser is new here); `tests/test_subagent.py`
(full, 15 tests); `git show b061b05` (commit message and diffstat).

### T1 — this repo's own frozen documents
`docs/0001-project-charter.md`; `docs/0007-phase-0-decision-record.md`
(referenced, not re-read line-by-line — cited via `docs/0037`'s own framing);
`docs/0013-personal-use-and-future-scope.md` §2, §7; `docs/0027`;
`docs/0029` §4; `docs/0030-m7-policy.md:140-150`; `docs/0037-harness-pivot-
research-brief.md` §10.4; `docs/0038-harness-pivot-decision.md` (full,
including §9 "Checkpoint-0 drift audit"); `CONVENTIONS.md`; `INDEX.md`.

### T1 — this repo's own frozen research
`research/phase-10-5-subagent-orchestration.md` §2.1, §2.2, §2.3, §2.6, §2.7,
§5.4, §7 (cited extensively; this document's V6/V7/DELETE #2 would not exist
without it — it was found by directory listing, not named in the brief).

### T1 — installed dependency, for one negative check
`.venv/Lib/site-packages/openhands/` — confirmed via `grep` that
`PRE_TOOL_USE`, `HookDecision`, `AgentDefinition`, `subagent`, `claude_code`
have zero hits in `agentctl/` outside the one new `subagent.py` call site,
repeating and reconfirming `docs/0038` §2's own check rather than trusting it.

### Method note

Every claim above that names a file:line was produced by running the `grep`
or reading the file, in this session, against the checkout current at the
time of writing — `093fb26` for most of the tree, re-checked against `b061b05`
(HEAD) wherever `subagent.py`/`tools.py` were cited, per the sources note
above — not inferred from what an earlier document said the code did. Three
items in this document (V3's `escalation.when` fields, V9's packaging risk,
V7's whole content) were not named anywhere in the brief that requested this
phase; they were found by treating "run the greps" as the actual instruction
rather than a formality. V7 additionally required re-running those same greps
a second time, late in this document's drafting, because the repository
changed under it — `b061b05` landed between this document's first pass over
`subagent.py` and its last. The alternative (leaving the first pass's
findings uncorrected, or quietly deleting the record of a bug that got fixed
before publication) would have made this document exactly the kind of stale
artifact `docs/0038` §9 exists to catch.
