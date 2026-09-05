# AI Agent Control Plane

A control plane for long-running LLM agent loops: making agent work
**recoverable, measurable, and cost-efficient** across changes of provider,
account, and model.

> The model/provider endpoint can change; the logical agent work must remain
> recoverable, measurable, and cost-efficient.

**Status: design phase. No code yet, deliberately.**

---

## Start here

- **[INDEX.md](INDEX.md)** — every document, numbered. Highest number is newest.
- **[docs/0001](docs/0001-project-charter.md)** — what this is and is not.
- **[docs/0008](docs/0008-system-architecture-v1.md)** — the current architecture.
- **[docs/0009](docs/0009-open-questions-register.md)** — what is blocked and why.

---

## The one-paragraph version

Chat completions are stateless, so "session continuity" across an API switch is
nearly free and the data plane already handles it. What actually breaks in long
agent loops is narrower and harder: a tool commits a real side effect, the
process dies, and replay executes it again. Phase 0 research confirmed this is
a real property of OpenHands, not a hypothetical — actions are persisted before
execution and re-driven through the real executor on resume. This project
builds the missing layer: an **effect ledger** that records tool *commitment*,
plus cache-affinity and cost-attribution intelligence, delivered as plugins
into existing extension points rather than a fork of anything.

---

## Architecture in one diagram

```
AGENT HARNESS ──▶ [effect gate] ──▶ tool executor      ← the only place
      │                                                   R1 is enforceable
      ▼
ENFORCEMENT KERNEL  (in-band, must not fail)
      │  reads local effect ledger + compiled policy
      ▼
LLM DATA PLANE ──▶ providers
      │  telemetry
      ▼
CONTROL PLANE  (out-of-band, may fail)
   policy compiler · cost ledger · cache intelligence
   capability matrix · replay evaluator
```

Full reasoning, alternatives considered, and failure analysis: `docs/0008`.

---

## Method

**Research before building. Falsify before committing.**

Every component gets a BUILD / CONFIGURE / SKIP verdict backed by primary
sources before code is written. The default verdict is SKIP. Phase 0 deleted
two components and downgraded two more — that was the point of running it.

Research is conducted by a research agent using the prompt pack in `docs/0005`,
which enforces source tiering, date-stamping, and mandatory
VERIFIED / INFERRED / UNKNOWN confidence separation.

---

## Repository layout

```
INDEX.md          The register. Read this first.
CONVENTIONS.md    Numbering rules and document lifecycle.
docs/             The numbered document stream. The project's memory.
research/raw/     Unprocessed source material.
experiments/      Reproducible experiment scripts, configs, results.
issues/           Working notes on open problems.
```

Only `docs/` is numbered.

---

## Next action

Build step 0 — the falsification experiment in `docs/0008` §14. It resolves
questions Q1, Q2, and Q3 from `docs/0009` in a single sitting, and any one of
them resolving badly changes the architecture.

Do not write ledger code before it runs.

---

## A note on this repository's location

This repo is intentionally initialized as its own git repository. The parent
directory `C:\Users\csdee\` is itself a git repository with an unrelated remote
(`pestechnology/PESU_RR_CSE_C_P38_...`). Keeping this project as a separate
repo prevents its files from being swept into that one. Consider also adding
`openhands/` to the home directory's `.gitignore`.
