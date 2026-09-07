# M0 — Falsification Spike

**Status:** not yet run
**Gates:** all build work in `docs/0012` §7
**Resolves:** `docs/0009` Q1, Q2, Q3, Q13 — and probes Q14

---

## Why this exists

`docs/0008` and `docs/0012` describe a system built on four assumptions that
have never been executed. Three of them are load-bearing: if any fails, the
architecture changes or dies.

This spike is **not a build**. Nothing here becomes production code. Its only
job is to convert four assumptions into four facts.

## Cost

Zero. Everything runs against a local mock provider that speaks the
OpenAI-compatible wire format and returns scripted tool calls. No API key, no
network, no tokens. This is deliberate — the spike must be cheap enough to
re-run on every SDK upgrade (`docs/0009` R1).

---

## Hypotheses

### H1 — Double execution is real (Q1)

> A side-effecting tool that runs, then loses its process before the
> `ObservationEvent` is written, will be **executed a second time** on resume.

- **Confirmed if:** the side-effect log contains 2 entries after resume.
- **Falsified if:** it contains 1. That means an executor-level dedup guard
  already exists, `docs/0007`'s core BUILD verdict collapses, and the Effect
  Ledger becomes an audit layer rather than the product.

### H2 — `tool_call_id` is stable across resume (Q2)

> The `tool_call_id` on the replayed action is byte-identical to the one
> persisted before the crash.

- **Confirmed if:** identical.
- **Falsified if:** it differs or is absent. The Effect Ledger's primary key
  (`docs/0012` §2.1) is then invalid and the data model must be redesigned
  around `action_event_id` or a content hash.

### H3 — An executor can be wrapped without forking (Q3)

> A `ToolExecutor` subclass holding another executor can be registered in place
> of the original via the public `register_tool` API, and calls route through
> the wrapper.

- **Confirmed if:** the wrapper's counter increments and the inner executor
  still produces its result.
- **Falsified if:** registration rejects it or calls bypass the wrapper. Seam C
  is then unavailable, R1 is unsatisfiable, and the project falls back to
  Option 1 (detect-and-alarm only) — a materially weaker product needing a new
  architecture document.

### H4 — OpenHands drives the OpenAI-format endpoint (Q13)

> The SDK calls `/v1/chat/completions`, not `/v1/messages`.

- **Confirmed if:** the mock records `/v1/chat/completions`.
- **Falsified if:** `/v1/messages`. LiteLLM issue #27518 means Seam A hooks are
  then **silently bypassed** — no policy, no affinity, no trace-id, and no
  error. M1 would need a different binding.

---

## Method

```
probe_00_api.py     Discover the real SDK surface. Run first.
probe_01_wrap.py    H3 — wrap and register an executor. No network.
probe_02_endpoint.py H4 — point the SDK at the mock, record the path called.
run_03_crash.py     H1, H2 — the crash/resume experiment.
run_all.py          Runs everything, writes results/report.md + results.json.
```

### The crash experiment

```
PARENT                              CHILD (subprocess)
  │                                   │
  │  spawn --child fresh              │
  ├──────────────────────────────────▶│  conversation.run()
  │                                   │  mock returns tool_call → tc_xxx
  │                                   │  ActionEvent persisted
  │                                   │  executor appends to side_effect.log
  │  poll for marker file             │  executor sleeps 5s  ◀── crash window
  │◀──────────────────────────────────┤
  │  proc.kill()   ── hard kill ──────▶ ✗
  │                                   
  │  inspect events/ → orphan? tool_call_id?
  │
  │  spawn --child resume             │
  ├──────────────────────────────────▶│  load persisted state
  │                                   │  get_unmatched_actions()
  │                                   │  ??? re-execute ???
  │◀──────────────────────────────────┤
  │
  │  count lines in side_effect.log
```

The executor writes its marker file **before** sleeping, so the parent kills
only after the side effect has genuinely landed. That is the exact ambiguous
state from `docs/0008` §6.5 — the effect happened, the record did not.

---

## Recording

`results/results.json` captures, per hypothesis: verdict, evidence, and the
exact installed versions of every relevant package. Per `docs/0009` R1, a
result without a version pin is not interpretable later.

---

## What is deliberately NOT tested

- Whether the Effect Ledger works — no ledger exists yet.
- Whether the gate blocks correctly — that is M2.
- Q14 (git trailer injection) is probed opportunistically but does not gate.

Resist the urge to start building inside this directory. When the spike
answers its four questions, record the answers in `docs/0009` and delete
nothing — but write M1 somewhere else.
