---
Number:        0012
Title:         Low-Level Design & Build Plan
Type:          ARCHITECTURE
Status:        DRAFT
Created:       2026-09-05
Supersedes:    —
Superseded-by: —
Depends-on:    0008, 0010, 0011, 0014, 0015
---

# 0012 — Low-Level Design & Build Plan

`0008` decided the shape. This decides the code: modules, interfaces, schemas,
file formats, tests, and the order to build them in.

Written for long-term single-developer use. Every choice optimises for
*surviving contact with a moving upstream* over elegance.

---

## 0. Findings that change the LLD

*Revised 2026-09-08 with `0014` (M0 execution) and `0015` (source reading).*

**Seam C is confirmed reachable without a fork — executed, not inferred**
(`0014`). But the binding is simpler than this document originally specified.
`ToolDefinition` carries the executor in a **field**, so Seam C binds as:

```python
gated = tool.model_copy(update={"executor": GatedExecutor(tool.executor)})
```

No subclassing, no re-registration. `0009` Q3 → **RESOLVED**.

**Two LiteLLM hook gaps constrain Seam A.** Both are open issues:

| Issue | Effect on us |
|---|---|
| `async_pre_call_hook` bypassed on the Anthropic `/v1/messages` endpoint (#27518) | **Not a problem in practice** — `0014` confirms the SDK drives `/v1/chat/completions`. Still assert it live in M1; a future SDK change would break Seam A silently. |
| `async_pre_call_hook` never fires for `/mcp/` tool calls — local registry dispatch bypasses hooks (#25011) | **MCP cannot be governed at Seam A.** Confirms the Capability Broker must bind at Seam C, where we control dispatch ourselves. |

The second one is a genuine architectural confirmation: it independently proves
the seam analysis in `0008` §3 — the tool boundary is the only place tool
governance can live.

> **Design rule added:** Seam A is best-effort and must be *verified live*, not
> assumed. M1's acceptance test asserts the hook actually fires.

### API corrections from M0

Five assumptions in the original draft were wrong. Corrected throughout, and
recorded here because they are easy to re-introduce:

| Assumed | Actual |
|---|---|
| `register_tool(name, ToolExecutor)` | `register_tool(name, ToolDefinition \| type[ToolDefinition])` |
| `ToolExecutor.__call__(action)` | `__call__(action, conversation=None)` |
| `conversation_id: str` | `uuid.UUID` |
| `persistence_dir` alone | `workspace` is a separate required parameter |
| `include_default_tools: bool` | a **list** |
| Tool names used verbatim | SDK **strips a `_tool` suffix** — `side_effect_tool` resolves to `side_effect` |

The resolver calls `create(conv_state=conv_state, **params)` and expects
`Sequence[ToolDefinition]`.

---

## 1. Package layout

The directory structure encodes the seam boundaries, so a violation is visible
in an import statement.

```
agentctl/
├── kernel/                  ▓ IN-BAND — must not fail. No network. No control-plane imports.
│   ├── ledger/
│   │   ├── schema.sql
│   │   ├── models.py        EffectRecord, EffectState, EffectClass, GateDecision
│   │   └── store.py         LedgerStore — SQLite, WAL, fsync, fencing
│   ├── gate.py              EffectGate — the decision in 0011 §3
│   ├── classify.py          Classifier — tool → EffectClass
│   ├── reconcile/
│   │   ├── base.py          ReconciliationProbe protocol
│   │   ├── git.py           trailer search
│   │   ├── filesystem.py    content hash compare
│   │   └── http.py          idempotency-key replay
│   └── hook.py              RequestHook — LiteLLM CustomLogger subclass
│
├── control/                 ░ OUT-OF-BAND — may fail. Never imported by kernel.
│   ├── policy/
│   │   ├── models.py        Policy DSL (pydantic)
│   │   └── compiler.py      Policy → CompiledPolicy artifact
│   ├── matrix/
│   │   ├── models.py
│   │   └── data/
│   │       ├── models.yaml  per-model capabilities
│   │       └── tools.yaml   per-tool effect classes
│   ├── cost/
│   │   ├── ingest.py        read LiteLLM_SpendLogs
│   │   └── attribute.py     join spend → turn
│   ├── cache/affinity.py    prefix-keyed affinity map
│   └── broker/              Capability Broker (MCP) — Layer 2
│
├── adapters/                THE PORTING COST. One package per harness.
│   └── openhands/
│       ├── executor.py      GatedExecutor — Seam C binding
│       ├── register.py      wrap + register_tool
│       └── events.py        Seam B subscription
│
├── replay/
│   ├── cassette.py          record/replay provider traffic
│   ├── inject.py            crash & failure injection
│   └── bench.py             policy comparison over traces
│
├── config.py                one settings object, env + file
└── cli.py                   agentctl <verb>
```

**One enforced rule, checked in CI:**

```python
# tests/test_boundaries.py
def test_kernel_never_imports_control():
    """R2: the kernel must run when the control plane is dead."""
    for mod in walk("agentctl/kernel"):
        assert "agentctl.control" not in imports_of(mod)
```

That single test is what keeps the architecture from rotting.

---

## 2. Data model

### 2.1 Ledger schema

```sql
-- agentctl/kernel/ledger/schema.sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous  = FULL;   -- durability over speed; this is the whole point

CREATE TABLE IF NOT EXISTS effect_record (
    tool_call_id     TEXT    PRIMARY KEY,
    conversation_id  TEXT    NOT NULL,
    turn_id          TEXT    NOT NULL,
    action_event_id  TEXT,
    tool_name        TEXT    NOT NULL,
    intent_hash      TEXT    NOT NULL,
    effect_class     TEXT    NOT NULL,
    state            TEXT    NOT NULL,
    fence_token      INTEGER NOT NULL,
    attempt          INTEGER NOT NULL DEFAULT 1,
    started_at       REAL    NOT NULL,
    committed_at     REAL,
    observation      BLOB,
    probe_verdict    TEXT,
    error            TEXT,
    CHECK (state IN ('INTENT','COMMITTED','OBSERVED','FAILED','BLOCKED')),
    CHECK (effect_class IN
        ('PURE_READ','IDEMPOTENT_WRITE','NON_IDEMPOTENT_WRITE','EXTERNAL','DESTRUCTIVE'))
);

CREATE INDEX IF NOT EXISTS ix_effect_conv  ON effect_record(conversation_id, turn_id);
CREATE INDEX IF NOT EXISTS ix_effect_state ON effect_record(state)
    WHERE state IN ('INTENT','BLOCKED');           -- the recovery scan

-- Fencing: one live writer per conversation.
CREATE TABLE IF NOT EXISTS lease (
    conversation_id TEXT PRIMARY KEY,
    holder          TEXT NOT NULL,
    fence_token     INTEGER NOT NULL,
    expires_at      REAL NOT NULL
);
```

`PRAGMA synchronous = FULL` is deliberate and non-negotiable. `NORMAL` can lose
the last commit on power failure — which is precisely the record whose absence
causes a double effect.

### 2.2 State machine

Legal transitions only. Anything else raises.

```
            ┌──────────┐
   (new) ──▶│  INTENT  │
            └────┬─────┘
      ┌──────────┼──────────┬─────────────┐
      ▼          ▼          ▼             ▼
 ┌─────────┐ ┌────────┐ ┌────────┐  ┌──────────┐
 │COMMITTED│ │ FAILED │ │BLOCKED │  │ (reconciled
 └────┬────┘ └────────┘ └───┬────┘   → COMMITTED)
      ▼                     ▼
 ┌──────────┐          human decision
 │ OBSERVED │
 └──────────┘
```

| From | To | Trigger |
|---|---|---|
| — | `INTENT` | gate admits, write-ahead |
| `INTENT` | `COMMITTED` | tool returned successfully |
| `INTENT` | `FAILED` | tool raised before any effect |
| `INTENT` | `COMMITTED` | probe found the effect on resume |
| `INTENT` | `FAILED` | probe proved the effect did not land |
| `INTENT` | `BLOCKED` | probe inconclusive → fail closed |
| `COMMITTED` | `OBSERVED` | observation returned to the harness |
| `BLOCKED` | any | human resolution only |

### 2.3 Core types

```python
# agentctl/kernel/ledger/models.py
from enum import Enum
from dataclasses import dataclass

class EffectClass(str, Enum):
    PURE_READ            = "PURE_READ"
    IDEMPOTENT_WRITE     = "IDEMPOTENT_WRITE"
    NON_IDEMPOTENT_WRITE = "NON_IDEMPOTENT_WRITE"
    EXTERNAL             = "EXTERNAL"
    DESTRUCTIVE          = "DESTRUCTIVE"

    @property
    def replay_safe(self) -> bool:
        return self in (EffectClass.PURE_READ, EffectClass.IDEMPOTENT_WRITE)

    @property
    def speculation_safe(self) -> bool:
        return self is EffectClass.PURE_READ      # strictly stricter — 0010 §6.4

class EffectState(str, Enum):
    INTENT = "INTENT"; COMMITTED = "COMMITTED"; OBSERVED = "OBSERVED"
    FAILED = "FAILED"; BLOCKED = "BLOCKED"

@dataclass(frozen=True)
class ToolCall:
    tool_call_id: str
    conversation_id: str
    turn_id: str
    tool_name: str
    args: dict

    def intent_hash(self) -> str:
        import hashlib, json
        canonical = json.dumps({"t": self.tool_name, "a": self.args},
                               sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

@dataclass(frozen=True)
class GateDecision:
    verdict: str                    # EXECUTE | SUBSTITUTE | BLOCK | ESCALATE
    observation: bytes | None = None
    reason: str | None = None
```

---

## 3. Kernel interfaces

### 3.1 LedgerStore

```python
# agentctl/kernel/ledger/store.py
class LedgerStore:
    """Single-writer, local, durable. No network. Never raises past `guard`."""

    def __init__(self, path: Path, holder: str): ...

    # --- lease / fencing -------------------------------------------------
    def acquire(self, conversation_id: str, ttl_s: float = 300) -> int:
        """Return a fence token. Raises LeaseHeld if another live holder exists."""

    # --- the write-ahead protocol ---------------------------------------
    def lookup(self, tool_call_id: str) -> EffectRecord | None: ...

    def write_intent(self, call: ToolCall, cls: EffectClass, fence: int) -> None:
        """INSERT + fsync. Must return only when durable."""

    def commit(self, tool_call_id: str, observation: bytes) -> None:
        """INTENT → COMMITTED + fsync."""

    def fail(self, tool_call_id: str, error: str) -> None: ...
    def block(self, tool_call_id: str, reason: str) -> None: ...
    def observed(self, tool_call_id: str) -> None: ...

    # --- recovery --------------------------------------------------------
    def pending(self, conversation_id: str) -> list[EffectRecord]:
        """Records in INTENT — the ambiguous set."""
```

### 3.2 EffectGate

The whole correctness core, and deliberately small.

```python
# agentctl/kernel/gate.py
class EffectGate:
    def __init__(self, store, classifier, probes, fence): ...

    def guard(self, call: ToolCall) -> GateDecision:
        cls = self.classifier.classify(call)
        rec = self.store.lookup(call.tool_call_id)

        if rec is None:
            self.store.write_intent(call, cls, self.fence)
            return GateDecision("EXECUTE")

        if rec.intent_hash != call.intent_hash():
            return GateDecision("BLOCK", reason="tool_call_id reused with different args")

        if rec.state in (EffectState.COMMITTED, EffectState.OBSERVED):
            return GateDecision("SUBSTITUTE", observation=rec.observation)

        if rec.state is EffectState.FAILED:
            self.store.write_intent(call, cls, self.fence)   # bumps attempt
            return GateDecision("EXECUTE")

        if rec.state is EffectState.BLOCKED:
            return GateDecision("BLOCK", reason=rec.error)

        # rec.state is INTENT — the ambiguous case (0008 §6.5)
        if cls.replay_safe:
            return GateDecision("EXECUTE")
        if cls is EffectClass.DESTRUCTIVE:
            return GateDecision("ESCALATE", reason="destructive effect, unknown outcome")

        verdict = self._probe(call, rec)
        if verdict == "LANDED":
            self.store.commit(call.tool_call_id, rec.observation or b"")
            return GateDecision("SUBSTITUTE", observation=rec.observation or b"")
        if verdict == "DID_NOT_LAND":
            return GateDecision("EXECUTE")

        self.store.block(call.tool_call_id, "probe inconclusive")
        return GateDecision("BLOCK", reason="cannot determine whether effect landed")
```

**`guard()` must never raise.** Any internal exception becomes
`BLOCK` — fail closed, per `0008` §6.5. A gate that crashes open is worse than
no gate, because it creates false confidence.

### 3.2.1 Verdict routing across seams

`0008` §3.5 splits enforcement by verdict. `guard()` is seam-agnostic and
returns a decision; **two different bindings act on it**:

| Verdict | Bound at | Mechanism |
|---|---|---|
| `EXECUTE` | either | do nothing |
| `BLOCK`, `ESCALATE` | **Seam B** | `ConversationState.block_action(action_id, reason)` |
| `SUBSTITUTE` | **Seam C** | return the stored observation from the executor wrap |

Keep `guard()` free of seam knowledge. The value: **Seam B alone gives correct
fail-closed behaviour**, so a harness with no executor wrap is still safe — it
just loses clean resume. Build Seam B first in M2; add Seam C for `SUBSTITUTE`.

`block_action` is read from source (`0015`), not executed. **M2's first test
confirms it empirically** before the design depends on it.

### 3.3 Reconciliation probes

```python
# agentctl/kernel/reconcile/base.py
class ReconciliationProbe(Protocol):
    def handles(self, call: ToolCall) -> bool: ...
    def probe(self, call: ToolCall, rec: EffectRecord) -> str:
        """LANDED | DID_NOT_LAND | INCONCLUSIVE"""
```

The git probe is the highest-value one and works by writing the intent hash into
the commit as a trailer, making the effect self-identifying:

```python
# agentctl/kernel/reconcile/git.py
TRAILER = "X-Agentctl-Intent"

class GitCommitProbe:
    def handles(self, call): return call.tool_name in {"git_commit", "execute_bash"} \
                                    and "git commit" in str(call.args)

    def probe(self, call, rec):
        out = run(["git", "log", "--all", f"--grep={TRAILER}: {rec.intent_hash}",
                   "--format=%H"], cwd=self.repo)
        if out.returncode != 0:      return "INCONCLUSIVE"
        return "LANDED" if out.stdout.strip() else "DID_NOT_LAND"
```

> **Design note.** The probe only works if the *write path* cooperates — the
> gate must inject the trailer when it admits the call. Reconciliation is not
> something bolted on afterwards; it is a contract between write and recovery.
> Every probe needs this pairing designed together.

### 3.4 RequestHook — Seam A

```python
# agentctl/kernel/hook.py
from litellm.integrations.custom_logger import CustomLogger

class RequestHook(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type, **kw):
        meta = data.setdefault("metadata", {})
        conv, turn = meta.get("conversation_id"), meta.get("turn_id")

        # 1. turn-atomic routing (0010 §7.3) — never switch mid-turn
        if _ends_with_unresolved_tool_calls(data.get("messages", [])):
            pin = self.affinity.pinned_deployment(conv, turn)
            if pin: data["model"] = pin

        # 2. cache affinity on the cache_control prefix, not the whole list
        elif (dep := self.affinity.lookup(_prefix_hash(data))):
            data["model"] = dep

        # 3. compiled policy — local file, no network
        if (deny := self.policy.check(data, user_api_key_dict)):
            raise HTTPException(status_code=403, detail=deny)

        # 4. attribution
        meta["trace_id"] = f"{conv}:{turn}"
        return data

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self.telemetry.record(kwargs, response_obj, start_time, end_time)
```

**Live-fire acceptance test required** (see §0): assert the hook actually fires
on your configured endpoint before trusting any of it. Done in `docs/0021`.

**Where the metadata actually is.** Anything the pre-call hook writes into
`data["metadata"]` arrives on the logging callback under
`litellm_params.metadata`, *not* `kwargs["metadata"]`, which is empty. Reading
only the obvious place yields `trace_id=None` and silently breaks the cost
attribution in `0008` §8 (`docs/0021` §4).

---

## 4. Adapter — the Seam C binding

The only harness-specific code. Keep it under ~150 lines (`0008` §12).

```python
# agentctl/adapters/openhands/executor.py
from openhands.sdk.tool import ToolExecutor

class GatedExecutor(ToolExecutor):
    """Wraps a real executor with the effect gate. Composition, not a fork."""

    def __init__(self, inner: ToolExecutor, gate: EffectGate, ctx):
        self._inner, self._gate, self._ctx = inner, gate, ctx

    def __call__(self, action, conversation=None):        # note: 2 args
        call = self._ctx.to_tool_call(action)
        d = self._gate.guard(call)

        if d.verdict == "SUBSTITUTE":
            return self._ctx.deserialize(d.observation)
        if d.verdict in ("BLOCK", "ESCALATE"):
            return self._ctx.blocked_observation(d.reason)

        try:
            obs = self._inner(action, conversation)
        except Exception as e:
            self._gate.store.fail(call.tool_call_id, repr(e))
            raise
        self._gate.store.commit(call.tool_call_id, self._ctx.serialize(obs))
        return obs
```

```python
# agentctl/adapters/openhands/register.py
def gate_tools(tools, gate, ctx):
    """Bind Seam C by replacing the executor FIELD on each resolved tool.

    Corrected per 0014 C1 — no subclassing, no re-registration.
    """
    return [t.model_copy(update={"executor": GatedExecutor(t.executor, gate, ctx)})
            for t in tools]


def install_seam_b(conversation, gate, ctx):
    """Bind BLOCK/ESCALATE via the event callback (0008 §3.5)."""
    def on_event(event):
        if type(event).__name__ == "ActionEvent" and event.action is not None:
            d = gate.guard(ctx.to_tool_call(event))
            if d.verdict in ("BLOCK", "ESCALATE"):
                conversation.state.block_action(event.id, d.reason or "blocked")
    return on_event
```

**Everything harness-specific lives in `ctx`** — how to read a tool call id off
an action, how to serialise an observation, how to build a blocked observation.
Porting to another harness means writing a new `ctx` and nothing else.

---

## 5. File formats

### 5.1 Capability matrix — `control/matrix/data/tools.yaml`

```yaml
version: 1
defaults:
  unknown_tool: EXTERNAL          # safe direction — 0008 §6.3

tools:
  read_file:      { class: PURE_READ }
  grep:           { class: PURE_READ }
  glob:           { class: PURE_READ }
  write_file:     { class: IDEMPOTENT_WRITE }
  str_replace:    { class: NON_IDEMPOTENT_WRITE, probe: filesystem }

  execute_bash:                   # classify by argument, not by name
    class: EXTERNAL
    rules:
      - match: "^(ls|cat|grep|rg|find|git (log|status|diff|show))\\b"
        class: PURE_READ
      - match: "^git commit\\b"
        class: NON_IDEMPOTENT_WRITE
        probe: git
      - match: "\\b(rm -rf|git push --force|DROP )"
        class: DESTRUCTIVE

mcp:
  default: EXTERNAL               # 0010 §8.2 — remote and opaque
  servers:
    filesystem:
      tools: { read_file: PURE_READ, list_directory: PURE_READ }
```

`execute_bash` is the hard case and the reason classification is
argument-aware rather than name-based. Get this table wrong and the whole
system is wrong — so it is data, reviewable and testable, not code.

### 5.2 Policy — `policy.yaml`

```yaml
version: 1

pools:
  free_tier:                       # the real daily driver — 0013
    - openrouter/free
    - google-ai-studio/flash
    - cerebras/llama
    - mistral/free
  paid:
    - anthropic/sonnet

routing:
  default_pool: free_tier
  escalate_to:
    pool: paid
    when: { requires_capability: [long_context], or_after_failures: 3 }
    require_confirmation: true     # 0002 §5 — never silently spend

budget:
  daily_usd: 2.00
  per_task_usd: 0.50
  on_exceeded: block

tiering:
  planning:  { min_tier: strong }
  edit:      { min_tier: mid }
  read:      { min_tier: cheap }

effects:
  destructive: require_human_approval
  external:    reconcile_or_block
```

Compiles to a flat lookup artifact the kernel reads from disk — no evaluation
logic in-band.

---

## 6. Test strategy

Three layers, and one of them is unusual.

| Layer | What runs | Speed | Covers |
|---|---|---|---|
| **Unit** | Ledger + gate against a temp SQLite | ms | State machine, every transition |
| **Cassette** | Recorded provider traffic replayed | seconds | Hook, routing, cost attribution |
| **Chaos** | Real subprocess, killed at chosen points | seconds | **The actual guarantee** |

### The chaos harness is the product's real test suite

```python
# replay/inject.py
CRASH_POINTS = [
    "before_action_event", "after_action_event", "before_intent",
    "after_intent", "mid_tool", "after_tool", "before_commit",
    "after_commit", "before_observation",
]

@pytest.mark.parametrize("point", CRASH_POINTS)
def test_no_duplicate_effect(point, tmp_repo):
    """0011 §10 — every crash point, exactly one effect."""
    run_agent_until(point, task="commit a file", repo=tmp_repo)
    kill_hard()
    resume_agent(repo=tmp_repo)
    assert count_commits(tmp_repo, marker=INTENT_HASH) == 1
```

That parametrised test *is* the specification. If it passes at all nine points,
the guarantee in `0008` §10 holds. If you write nothing else, write this.

### The harness must distinguish "did not happen" from "could not observe"

M0 shipped a bug worth generalising (`0014` §5). The SDK's visualizer filled an
undrained subprocess pipe and blocked the child mid-run. The parent was polling
for a marker at that moment, timed out, and reported **"the tool never ran"** —
when the tool had run perfectly.

That failure pointed in the direction of the hypothesis, which is the dangerous
direction. Rules for the chaos suite:

- **Never pipe child output to memory without a reader.** Redirect to files.
- **Every negative result must be distinguishable from a broken observation.**
  A timeout is `INCONCLUSIVE`, never `CONFIRMED` or `FALSIFIED`.
- **Assert the harness worked before interpreting what it measured** — did the
  child reach the tool at all? Did the mock receive a request?

A test harness that fails silently toward your hypothesis is worse than no
harness.

### The nine-point suite drives the kernel, not the SDK

`docs/0019`. The guarantee is a property of the *protocol*, so testing it at the
kernel makes the crash point chosen rather than raced for, and ~40s instead of
~4 minutes — the difference between running on every commit and not.
Experiments `0001`-`0003` cover the SDK integration separately.

### Force UTF-8 on every redirected subprocess

Four encoding failures so far: M0's probes, M0's subprocess pipes, M4's CRLF
appends, and the LiteLLM proxy refusing to start because its banner is
non-ASCII (`docs/0021` §6). On Windows, set `PYTHONIOENCODING=utf-8` and
`PYTHONUTF8=1` in any child environment whose output is redirected. Assume it;
do not wait to be surprised.

### Assert the ROUTE when the error path and the success path share an outcome

Fail-closed makes failures look like decisions. A crashing gate returns BLOCK,
and so does a gate that correctly decided to block — so a test asserting only
the verdict cannot tell them apart, and one did not for an entire milestone
(`docs/0024`). Assert which record moved, which reason was given, and whether
an exception was swallowed.

**Fail-safe designs are harder to test than fail-fast ones.** That is a cost of
`0008` §6.5, and it should be paid deliberately.

### Mutation-check any change to the gate, ledger or a probe

A suite that passes first time invites the suspicion that it cannot fail.
Break the thing deliberately and confirm the suite notices. `docs/0019` §4 does
this for the gate: neutering the ambiguous branch produces 7 failures, exactly
where the effect had landed. **Treat this as a rule, not an anecdote.**

---

## 7. Milestones

Each milestone is small enough to finish in a sitting or two, ends in something
demonstrable, and teaches one thing.

| M | Deliverable | Acceptance test | What it teaches |
|---|---|---|---|
| ~~M0~~ | ~~Falsification spike~~ | ✅ **DONE** — all four hypotheses confirmed (`0014`) | — |
| **M1** | LiteLLM wiring + live hook proof | `async_pre_call_hook` provably fires; two accounts fail over. **Trace-id forwarding is already free** (`0015` §5) — only add the turn component | Proxy architecture, the endpoint trap |
| **M2** | Ledger + gate. **Seam B first**, then Seam C | (a) `block_action` empirically confirmed; (b) chaos suite green at all 9 points for `PURE_READ`/`IDEMPOTENT_WRITE` | Write-ahead logging, durability, SQLite |
| ~~M3~~ | ~~Classifier + capability matrix~~ | ✅ **DONE** — 75-command corpus green; building it found 21 under-classifications (`0026`) | Why data beats code for policy |
| **M4** | Git + filesystem probes | Chaos green for `NON_IDEMPOTENT_WRITE` | Reconciliation, idempotency |
| **M5** | Cost ledger + attribution | `agentctl cost --today` shows spend per task | Telemetry joins, observability |
| ~~M6~~ | ~~Record/replay evaluator~~ | DONE - a real session replays with no key, no network, 0 misses (`0029`) | Deterministic testing of nondeterministic systems |
| **M7** | Policy compiler | Budget cap actually blocks; escalation asks first | Control/data plane separation, DSL design |

**M2 is now the whole thesis** — M0 is done and confirmed it. Everything after
is leverage.

M2 splits in two, per `0008` §3.5. **M2a** binds `BLOCK`/`ESCALATE` at Seam B
via `block_action` — no executor wrapping, and it already delivers correct
fail-closed behaviour. **M2b** adds Seam C for `SUBSTITUTE` and clean resume.
Ship M2a and use it before starting M2b.

Nothing here requires more than a laptop, a free-tier key or two, and a scratch
git repo.

---

## 8. Operating principles for a long-lived solo project

Written down because these are what usually kill personal infrastructure.

1. **Pin everything.** One `constraints.txt` with exact SDK and LiteLLM
   versions. Upgrade deliberately, never incidentally (`0009` R1).
2. **Re-verify before building on a source claim.** Every milestone starts by
   re-running the relevant assertion against the pinned version.
3. **The chaos suite runs on every commit.** It is the only thing standing
   between you and a silent regression of the core guarantee.
4. **The boundary test runs on every commit.** Kernel must never import control.
5. **Never let the kernel grow.** If `gate.py` exceeds ~200 lines, something
   belongs in the control plane.
6. **Ship a usable slice at every milestone.** M2 alone is already worth
   running daily — it makes your agent crash-safe. Do not wait for M7.

---

## 9. Open items

| # | Question | Now |
|---|---|---|
| Q2 | `tool_call_id` stable across resume? | ✅ **RESOLVED** — byte-identical (`0014`) |
| Q3 | Executor wrappable without forking? | ✅ **RESOLVED** — via the `executor` field (`0014`) |
| Q13 | Which endpoint does the SDK drive? | ✅ **RESOLVED** — `/v1/chat/completions` (`0014`) |
| Q5 | Trace-id forwarded? | ✅ **RESOLVED** — `x-litellm-session-id` (`0015`) |
| Q14 | Can the gate inject a git trailer into an agent-authored commit? | ⏳ **OPEN** — §3.3 reconciliation depends on it. M4. |
| Q16 | Does `block_action` behave as documented? | ⏳ **OPEN** — read from source, not executed. **M2a's first test.** |
| Q18 | Does litellm price every free-tier endpoint? | ⏳ **OPEN** — an unpriced endpoint is invisible to `max_budget_per_run`. M1. |

Budget note: `max_budget_per_run` covers `per_task_usd` by configuration
(`0015` §4), so the policy compiler in M7 only needs to build the per-day cap —
subject to Q18.
