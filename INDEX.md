# Document Index

**The highest number is the newest document.** Current head: **0010**.

Conventions for adding to this stream: [CONVENTIONS.md](CONVENTIONS.md).

| # | Title | Type | Status | Created | Summary |
|---|---|---|---|---|---|
| [0001](docs/0001-project-charter.md) | Project Charter | ARCHITECTURE | LIVING | 2026-09-05 | What the project is, what it is not, success criteria |
| [0002](docs/0002-original-architecture.md) | Original Architecture (working memory) | ARCHITECTURE | SUPERSEDED | 2026-09-05 | The first design. Superseded by 0008 §2. Kept as the record of where thinking started |
| [0003](docs/0003-architecture-critique.md) | Critique of the Original Architecture | DECISION | ACCEPTED | 2026-09-05 | Five findings that reframed the project from failover to cost/continuity |
| [0004](docs/0004-research-roadmap.md) | Research & Build Roadmap | GUIDELINE | LIVING | 2026-09-05 | Ten research phases, five hard problems, phase status table |
| [0005](docs/0005-research-prompt-pack.md) | Research Agent Prompt Pack | GUIDELINE | LIVING | 2026-09-05 | Master brief + 10 phase prompts + standing follow-ups |
| [0006](docs/0006-research-phase-0-recon.md) | Phase 0 — Existing-system Reconnaissance | RESEARCH | ACCEPTED (frozen) | 2026-09-05 | 13 verified claims, 4 inferences, 5 unknowns. Confirms double-execution |
| [0007](docs/0007-phase-0-decision-record.md) | Phase 0 Decision Record | DECISION | ACCEPTED | 2026-09-05 | Component verdict table. Two components deleted, two downgraded |
| [0008](docs/0008-system-architecture-v1.md) | System Architecture v1 | ARCHITECTURE | **DRAFT** | 2026-09-05 | Seam analysis, three candidate architectures, Effect Ledger design |
| [0009](docs/0009-open-questions-register.md) | Open Questions & Risk Register | REGISTER | LIVING | 2026-09-05 | 7 open questions, 5 risks. Q1–Q5 block 0008 |
| [0010](docs/0010-latency-switching-mcp-integration.md) | Latency, Model Switching, and MCP/Plugin Integration | RESEARCH | ACCEPTED (frozen) | 2026-09-05 | Feature research. Cache latency claim corrected; MCP now stateless; Capability Broker proposed |

---

## Reading order

**New to the project?** `0001` → `0007` → `0008`. That is the charter, the
current verdicts, and the current design. About 30 minutes.

**Want the full history?** `0002` → `0003` → `0004` → `0006` → `0007` → `0008`.

**Picking up work?** `0009` first. It says what is blocked and why.

---

## Current state

| | |
|---|---|
| **Phase** | Phase 0 complete. Phase 1 not started. |
| **Architecture** | `0008` in DRAFT. Blocked on Q1–Q5 in `0009`. Revisions pending from `0010` §11. |
| **Next action** | Build step 0 — the falsification experiment (`0008` §14). Resolves Q1, Q2, Q3 in one sitting. |
| **Code written** | None, deliberately. |

---

## Research phase status

| Phase | Topic | Status | Doc |
|---|---|---|---|
| 0 | Existing-system reconnaissance | **COMPLETE** | `0006` |
| 1 | LLM request lifecycle | Not started | — |
| 2 | Context engineering | Not started | — |
| 3 | Agent execution state | Not started | — |
| 4 | Distributed systems foundations | Not started | — |
| 5 | Durable execution & orchestration | Not started | — |
| 6 | Routing intelligence & cache economics | Not started | — |
| 7 | Correctness boundary | Not started | — |
| 8 | Evaluation without burning tokens | Not started | — |
| 9 | Production architecture | Not started | — |

Prompts: `0005`. Each completed phase gets the next free number as a frozen
RESEARCH document, followed by a DECISION document recording what it changed.
