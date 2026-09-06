---
Number:        0011
Title:         Request Flow — End-to-End Architecture Diagrams
Type:          ARCHITECTURE
Status:        DRAFT
Created:       2026-09-05
Supersedes:    —
Superseded-by: —
Depends-on:    0008, 0010
---

# 0011 — Request Flow

One user request, traced through every concept in the architecture. Companion
to `0008` (which argues *why*) and `0010` (which adds latency, switching, and
MCP). This document shows *what actually happens*.

Diagrams are Mermaid so they render on GitHub and stay diffable.

**Legend used throughout**

| Marker | Meaning |
|---|---|
| **A** | Seam A — LiteLLM `CustomLogger` hook |
| **B** | Seam B — harness event callback (observe only) |
| **C** | Seam C — tool executor wrapper (the only enforcement point) |
| ▓ | In-band. Must not fail. |
| ░ | Out-of-band. May fail. |

---

## 1. The static picture — who owns what

```mermaid
flowchart TB
    U([USER<br/>add auth to the app])

    subgraph H["AGENT HARNESS — OpenHands SDK, unmodified"]
        direction TB
        CS[ConversationState<br/>append-only EventLog]
        CD[Condenser<br/>context construction]
        AG[Agent.step loop]
        TE[Tool Executor]
    end

    subgraph K["▓ ENFORCEMENT KERNEL — in-band, must not fail"]
        direction TB
        RH["Request Hook — Seam A<br/>policy · affinity · trace-id<br/>turn-atomic routing"]
        EG["Effect Gate — Seam C<br/>classify · lookup · WAL"]
        EL[(Effect Ledger<br/>SQLite · WAL · fsync)]
    end

    subgraph D["LLM DATA PLANE — LiteLLM"]
        direction TB
        RT[Router<br/>strategy · pre-call checks]
        CB2[Cooldown · Fallbacks<br/>Budgets]
    end

    subgraph P["PROVIDER POOLS"]
        direction LR
        P1[OpenRouter<br/>acct A]
        P2[OpenRouter<br/>acct B]
        P3[Anthropic<br/>org]
    end

    subgraph M["MCP FLEET"]
        M1[fs server<br/>stdio]
        M2[github server<br/>HTTP + OAuth]
    end

    subgraph CP["░ CONTROL PLANE — out-of-band, may fail"]
        direction TB
        PC[Policy Compiler]
        CL[Cost Ledger<br/>+ attribution]
        CI[Cache Intelligence]
        CM[Capability Matrix<br/>models · tools · effect classes]
        CBR[Capability Broker<br/>MCP registry · gating · creds]
        RE[Replay Evaluator]
    end

    U --> CS
    CS --> AG
    CD -.context.-> AG
    AG -->|LLM request| RH
    RH --> RT
    RT --> CB2
    CB2 --> P
    P -->|"assistant + tool_calls"| RH
    RH -->|response| AG
    AG -->|"ActionEvent persisted FIRST"| CS
    AG -->|tool call| EG
    EG <--> EL
    EG -->|approved| TE
    TE -->|MCP tools| CBR
    CBR --> M
    TE -->|ObservationEvent| CS

    CS -.->|"Seam B — observe"| CL
    RT -.telemetry.-> CL
    PC -.compiled policy.-> RH
    CI -.affinity hints.-> RH
    CM -.effect classes.-> EG
    CM -.-> PC
    CL -.-> RE

    classDef kernel fill:#fde8e8,stroke:#c0392b,stroke-width:2px
    classDef control fill:#e8f0fe,stroke:#3367d6,stroke-dasharray:5 3
    classDef harness fill:#e8f5e9,stroke:#2e7d32
    class K,RH,EG,EL kernel
    class CP,PC,CL,CI,CM,CBR,RE control
    class H,CS,CD,AG,TE harness
```

**The three things to read off this picture:**

1. The control plane touches nothing on the request path. It publishes
   artifacts (compiled policy, affinity hints, effect classes) and consumes
   telemetry. Cut every dashed line and work continues on the last artifacts.
2. The kernel is two small boxes plus a local database. Everything clever
   happens out-of-band.
3. Seam C sits between `Agent` and `Tool Executor` — the only point in the
   whole system where an effect can be stopped before it lands.

---

## 2. The happy path — one full turn

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant AG as Agent.step
    participant CS as EventLog
    participant RH as ▓ Request Hook (A)
    participant RT as LiteLLM Router
    participant PR as Provider acct A
    participant EG as ▓ Effect Gate (C)
    participant EL as Effect Ledger
    participant TE as Tool Executor
    participant CL as ░ Cost Ledger

    U->>CS: MessageEvent "add auth"
    CS->>AG: step()
    AG->>AG: get_unmatched_actions() → none
    AG->>AG: Condenser builds view (harness-owned)

    Note over AG,RH: turn N begins
    AG->>RH: LLM request (messages + tools)
    RH->>RH: read compiled policy (local file)
    RH->>RH: turn-atomic check — unresolved tool_calls?
    RH->>RH: cache affinity: prefix_hash → deployment
    RH->>RH: model tier for task class
    RH->>RH: stamp trace_id = (conv_id, turn_id)
    RH->>RT: routed request + pinned deployment
    RT->>RT: pre-call checks · cooldown · budget
    RT->>PR: POST /messages
    PR-->>RT: assistant + tool_calls<br/>usage.cache_read_input_tokens
    RT-->>RH: response
    RH->>CL: telemetry (cost, tokens, cache, latency, deployment)
    RH-->>AG: response

    Note over AG,CS: 0006:V1 — intent persisted BEFORE execution
    AG->>CS: ActionEvent (tool_call_id, args)

    AG->>EG: execute(tool_call_id, name, args)
    EG->>EG: classify → effect_class
    EG->>EL: lookup(tool_call_id)
    EL-->>EG: absent
    EG->>EL: write INTENT, fsync
    EG->>TE: execute
    TE-->>EG: result
    EG->>EL: write COMMITTED + observation, fsync
    EG-->>AG: observation

    AG->>CS: ObservationEvent
    CS-->>CL: Seam B — attribute turn cost
    Note over AG: loop to step 2 until done
```

**Steps 14–15 are the whole project.** Everything before them is existing
software; everything after is bookkeeping. The gap between "intent persisted"
and "effect recorded" is where double execution lives.

---

## 3. The Effect Gate decision — the correctness core

```mermaid
flowchart TD
    S([Gate receives<br/>tool_call_id, name, args]) --> CLS[classify via<br/>Capability Matrix]
    CLS --> LK{ledger.lookup<br/>tool_call_id}

    LK -->|COMMITTED / OBSERVED| SUB[Return stored observation<br/>DO NOT EXECUTE]
    LK -->|FAILED| EXE
    LK -->|absent| WAL[write INTENT + fsync]
    LK -->|INTENT| AMB{{AMBIGUOUS<br/>did the effect land?}}

    AMB --> CK{effect_class}
    CK -->|PURE_READ| EXE
    CK -->|IDEMPOTENT_WRITE| EXE
    CK -->|NON_IDEMPOTENT| REC[reconciliation probe]
    CK -->|EXTERNAL| REC
    CK -->|DESTRUCTIVE| ESC[ESCALATE to human]

    REC --> RQ{probe conclusive?}
    RQ -->|"yes — it landed"| SUB2[synthesize observation<br/>DO NOT EXECUTE]
    RQ -->|"yes — it did not"| EXE
    RQ -->|no| BLK[FAIL CLOSED<br/>block conversation]

    WAL --> EXE[EXECUTE TOOL]
    EXE --> OK{success?}
    OK -->|yes| CMT[write COMMITTED<br/>+ observation, fsync]
    OK -->|no| FL[write FAILED]
    CMT --> R([return observation])
    SUB --> R
    SUB2 --> R
    FL --> R
    ESC --> HUM([human decision])
    BLK --> HUM

    classDef danger fill:#fde8e8,stroke:#c0392b,stroke-width:2px
    classDef safe fill:#e8f5e9,stroke:#2e7d32
    class AMB,BLK,ESC danger
    class SUB,SUB2,CMT safe
```

The `INTENT` branch is the irreducible ambiguity from `0008` §6.5. Note that
three of five classes escape it cheaply — which is why classification, not
cleverness, is what makes this tractable.

---

## 4. Crash and resume — where the ledger earns its existence

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent
    participant CS as EventLog
    participant EG as ▓ Effect Gate
    participant EL as Effect Ledger
    participant W as World (git repo)

    rect rgb(253, 232, 232)
    Note over AG,W: RUN 1 — crashes mid-tool
    AG->>CS: ActionEvent (id=tc_7, git commit)
    AG->>EG: execute(tc_7)
    EG->>EL: INTENT tc_7
    EG->>W: git commit
    W-->>EG: committed abc123
    Note over AG,W: 💥 kill -9 — before COMMITTED is written
    end

    rect rgb(232, 240, 254)
    Note over AG,W: RUN 2 — resume
    AG->>CS: load base_state + events
    AG->>AG: get_unmatched_actions() → [tc_7]
    Note over AG: 0006:V2 — harness would re-execute here
    AG->>EG: execute(tc_7)
    EG->>EL: lookup(tc_7)
    EL-->>EG: INTENT — ambiguous
    EG->>EG: class = NON_IDEMPOTENT_WRITE
    EG->>W: probe — git log for intent_hash trailer
    W-->>EG: found abc123
    EG->>EL: reconcile → COMMITTED
    EG-->>AG: synthesized observation
    Note over EG,W: ✅ no second commit
    end
```

Without the ledger, run 2 produces a duplicate commit. That is the confirmed
behavior in `0006:V1`/`V2`, not a hypothetical.

---

## 5. Provider failover — and the rule that protects it

```mermaid
sequenceDiagram
    autonumber
    participant AG as Agent
    participant RH as ▓ Request Hook
    participant RT as LiteLLM Router
    participant A as acct A (warm cache)
    participant B as acct B (cold)
    participant CL as ░ Cost Ledger

    AG->>RH: turn N request
    RH->>RT: affinity → pin acct A
    RT->>A: request
    A-->>RT: 429 rate limited
    RT->>RT: cooldown acct A · fallback
    RT->>B: same request, acct B
    B-->>RT: 200 — cache MISS, full prefill
    RT-->>RH: response
    RH->>CL: cache_creation not read · latency ↑ · switch cost recorded

    Note over RH,B: affinity now repoints to acct B for the warm prefix

    rect rgb(253, 232, 232)
    Note over AG,B: THE HAZARD — 0010 §7.3
    AG->>RH: turn N+1 — message list ends in unresolved tool_calls
    RH->>RH: turn-atomic check → BLOCKED
    Note over RH: an endpoint change mid-turn can invalidate<br/>tool_call_id semantics, and the ledger is keyed on it
    RH->>RT: pinned to the endpoint that opened the turn
    end
```

Failover between turns is cheap and already handled by the data plane. Failover
*within* a turn can defeat the effect ledger's primary key — hence the rule:
**the turn is the atomic unit of routing.**

---

## 6. Where each concept appears

| Concept | Diagram | Step / node |
|---|---|---|
| Session identity | §1 | `ConversationState` — harness-owned (`0007`) |
| Turn | §2 | steps 6–24, one `Agent.step` iteration |
| Journal | §1, §2 | `EventLog`, append-only (`0006:V3`) |
| Context vs memory | §1 | Condenser — SKIP verdict, harness-owned |
| Control / data plane split | §1 | dashed lines only, no hot-path edge |
| Seam A — Request Hook | §2 | steps 7–13 |
| Seam B — observe | §1, §2 | `EventLog` → Cost Ledger |
| Seam C — Effect Gate | §2, §3 | steps 15–21 |
| Write-ahead intent | §2, §3 | `write INTENT, fsync` |
| Effect classification | §3 | `classify` → 5 classes |
| Ambiguous state | §3, §4 | the `INTENT` branch |
| Reconciliation probe | §3, §4 | git log for intent hash |
| Fail closed | §3 | `BLOCK conversation` |
| Fail open | §1 | cut any dashed line — work continues |
| Cache affinity | §2, §5 | `prefix_hash → deployment` |
| Model tiering | §2 | `model tier for task class` |
| Cost attribution | §2 | `trace_id = (conv_id, turn_id)` |
| Policy compiler | §1 | compiled policy → Request Hook |
| Capability matrix | §1, §3 | feeds classifier and compiler |
| Provider pools / accounts | §1, §5 | acct A / acct B / org |
| Failover · cooldown | §5 | 429 → cooldown → acct B |
| Turn-atomic routing | §5 | the red block |
| MCP + Capability Broker | §1 | `Tool Executor` → Broker → MCP fleet |
| Replay evaluator | §1 | consumes Cost Ledger, off-path |
| Speculation (Layer 2) | §7 | below |

---

## 7. Layer 2 — speculative execution (not yet built)

The latency path from `0010` §6.4, shown for completeness. Gated on Q9.

```mermaid
flowchart LR
    GEN[LLM still generating<br/>~96% of turn latency] --> PRED[predict likely<br/>next tool call]
    PRED --> CLS{effect_class}
    CLS -->|PURE_READ| SPEC[speculatively execute<br/>cache result]
    CLS -->|anything else| WAIT[wait for generation]
    SPEC --> MATCH{prediction correct?}
    MATCH -->|yes| HIT[serve cached result<br/>tool latency hidden]
    MATCH -->|no| DISC[discard — no harm,<br/>it was a pure read]
    WAIT --> NORM[normal gate path §3]

    classDef win fill:#e8f5e9,stroke:#2e7d32
    class HIT,SPEC win
```

Speculation is *strictly stricter* than replay safety: `IDEMPOTENT_WRITE` is
safe to repeat but not safe to speculate, because a discarded speculative write
has still mutated the world. Same classifier, higher threshold.

---

## 8. Status

DRAFT, inheriting every open question from `0009`. In particular:

- If **Q3** fails, Seam C does not exist and §2–§4 are unbuildable as drawn.
- If **Q2** fails, the ledger key in §3 is invalid.
- If **Q9** shows writes dominate, §7 is deleted.

These diagrams describe the intended design, not verified behavior.
