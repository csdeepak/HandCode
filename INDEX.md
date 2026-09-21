# Document Index

**The highest number is the newest document.** Current head: **0038**.

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
| [0011](docs/0011-request-flow-architecture.md) | Request Flow — End-to-End Diagrams | ARCHITECTURE | DRAFT | 2026-09-05 | Five Mermaid diagrams tracing one user request through every concept; concept coverage map |
| [0012](docs/0012-low-level-design-and-build-plan.md) | Low-Level Design &amp; Build Plan | ARCHITECTURE | DRAFT | 2026-09-05 | Package layout, ledger schema, gate/hook/adapter interfaces, chaos test suite, milestones M0–M7 |
| [0013](docs/0013-personal-use-and-future-scope.md) | Personal Use &amp; Future Scope | GUIDELINE | LIVING | 2026-09-05 | Free-tier orchestrator, dashboard restored (M8), daily-driver CLI, integration surfaces, learning ladder |
| [0014](docs/0014-m0-results-decision-record.md) | M0 Results — Decision Record | DECISION | ACCEPTED | 2026-09-08 | All four hypotheses CONFIRMED. Double execution reproduced. Three corrections to 0012 |
| [0015](docs/0015-sdk-capability-findings.md) | SDK Capability Findings | DECISION | ACCEPTED | 2026-09-08 | Q5/Q15/Q16/Q17 resolved. Seam B can block — corrects 0008 §3. Revised seam table |
| [0016](docs/0016-m2a-results.md) | M2a Results — The Gate Works | DECISION | ACCEPTED | 2026-09-08 | Duplicate eliminated. Two design flaws found by tests: most-dangerous-match, and fence enforcement |
| [0017](docs/0017-m4-results.md) | M4 Results — Reconciliation Probes | DECISION | ACCEPTED | 2026-09-08 | Git and filesystem probes. Ambiguity resolves with no human. Fingerprinting replaces trailer injection |
| [0018](docs/0018-m2b-results.md) | M2b Results — Substitution | DECISION | ACCEPTED | 2026-09-08 | Agent resumes with a result, not a rejection. Correctness story closed for local effects |
| [0019](docs/0019-nine-point-chaos-suite.md) | The Nine-Point Chaos Suite | DECISION | ACCEPTED | 2026-09-08 | 38 tests, real process death. Mutation-verified to have teeth |
| [0020](docs/0020-external-idempotency-probe.md) | The EXTERNAL Idempotency-Key Probe | DECISION | ACCEPTED | 2026-09-08 | Fourth verdict SAFE_TO_RETRY. Every effect class now has a recovery path |
| [0021](docs/0021-m1-results.md) | M1 Results — Seam A Fires | DECISION | ACCEPTED | 2026-09-08 | Hook proven live in a real proxy; failover works; Q18 confirmed as a hazard |
| [0022](docs/0022-integration-complete.md) | Integration Complete | DECISION | ACCEPTED | 2026-09-08 | Full stack runs together; cost ledger with pricing coverage as a first-class signal |
| [0023](docs/0023-real-provider-run.md) | The Real Provider Run | DECISION | ACCEPTED | 2026-09-08 | Found a real duplicate; corrected Q2. `tool_call_id` is model-minted and unstable across a pool |
| [0024](docs/0024-right-outcome-wrong-route.md) | The Right Outcome by the Wrong Route | DECISION | ACCEPTED | 2026-09-11 | A demo passed while the gate was crashing. Assert the route, not just the result |
| [0025](docs/0025-making-it-usable.md) | Making It Usable | DECISION | ACCEPTED | 2026-09-11 | Real tools + `agentctl run`. The model saw empty observations because `content` is reserved |
| [0026](docs/0026-classifier-first-word.md) | M3 — The Classifier Only Ever Saw the First Word | DECISION | ACCEPTED | 2026-09-13 | 21 under-classifications in 55 commands. Anchored rules never saw past the first word |
| [0027](docs/0027-where-a-write-lands.md) | Where a Write Lands Is Not What Kind of Write It Is | DECISION | ACCEPTED | 2026-09-13 | `echo x > ~/.bashrc` was classified correctly and still went unasked |
| [0028](docs/0028-ci-found-a-real-bug.md) | CI Found a Bug That Only Existed on Someone Else's Machine | DECISION | ACCEPTED | 2026-09-13 | `id()` is unique only among live objects; the proxy extra was never installable |
| [0029](docs/0029-m6-replay.md) | M6 - Replaying a Session Means Replaying the World Too | DECISION | ACCEPTED | 2026-09-13 | Record/replay at zero cost; a deny-list cannot match two representations |
| [0030](docs/0030-m7-policy.md) | M7 - A Policy That Fails Open Is Worse Than No Policy | DECISION | ACCEPTED | 2026-09-13 | Compile out of band, look up in band. A typo must not disarm DESTRUCTIVE |
| [0031](docs/0031-handover.md) | Handover - The Flaws a Real User Found in an Hour | DECISION | ACCEPTED | 2026-09-13 | doctor, provider-error translation, proxy pools. A generator that emitted invalid YAML |
| [0032](docs/0032-keys-and-dashboard.md) | One Registry, One Keys File, One Screen | DECISION | ACCEPTED | 2026-09-14 | Where to get every key, one file to hold them, and a screen saying if failover is real |
| [0033](docs/0033-multi-account.md) | Many Keys, Many Accounts | DECISION | ACCEPTED | 2026-09-14 | The account is the unit, not the provider. And 'outside any repo' was false here |
| [0034](docs/0034-connectivity.md) | 31 Keys, and Four Ways a Check Can Lie | DECISION | ACCEPTED | 2026-09-15 | A CDN 403 is not a rejected key; a catalogue is not what you can call |
| [0035](docs/0035-dogfood.md) | The Agent Fixed Its Own Repository | DECISION | ACCEPTED | 2026-09-15 | PASS on a real gap, and an 8-line change arrived as a 149-line diff |
| [0036](docs/0036-live-demo.md) | A Timeout That Did Not Time Out | DECISION | ACCEPTED | 2026-09-15 | A live demo fixed a real bug and found three defects in the tool running it |
| [0037](docs/0037-harness-pivot-research-brief.md) | Harness Pivot — Research Brief | GUIDELINE | LIVING | 2026-09-20 | Phase 10 prompts: which harness, whether multi-agent is affordable, model selection, what to delete |
| [0038](docs/0038-harness-pivot-decision.md) | The Pivot That Was Already Built | DECISION | **DRAFT** | 2026-09-20 | No pivot. The SDK already ships the features; multi-agent does not fit the budget; a live single-agent bug found |

---

## Reading order

**New to the project?** `0001` → `0007` → `0008` → `0011`. Charter, current
verdicts, current design, then the diagrams. About 40 minutes.

**Ready to build?** `0012` (how) then `0013` (what for). Start at M0.

**Want the full history?** `0002` → `0003` → `0004` → `0006` → `0007` → `0008`.

**Picking up work?** `0009` first. It says what is blocked and why.

---

## Current state

| | |
|---|---|
| **Phase** | **Integration complete** (`0022`). Full stack verified end to end; spend is attributable. |
| **Architecture** | `0008` DRAFT — Q1/Q2/Q3/Q5/Q13/Q15/Q16/Q17 resolved. **Q4 is the last blocker.** §3 needs the `0015` correction. |
| **Verify** | `python verify.py` — 8 checks, ~4 min, zero cost |
| **Next action** | **M0-M7 are all complete.** Next: a run against a second provider family to test the `/v1/messages` path, and Q9 -- the read/write ratio by effect class, which decides whether speculative execution is worth building. |
| **Code written** | `agentctl/` — ledger, classifier, gate, Seams B and C, probes, CLI. **605 tests green.** |

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
