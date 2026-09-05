# My OpenHands AI Agent Control Plane — Working Memory

> **Purpose:** This document captures the architecture, decisions, mental model, goals, and next steps discussed so far so the project can be continued in another session without losing context.

---

## 1. Core Idea

I am architecting an **AI Agent Control Plane** around **OpenHands**.

OpenHands is the agent/harness that actually performs the work. I do **not** want OpenHands to be tightly coupled to one API provider, one API key, or one account.

The control plane I am designing should sit between OpenHands and the model/API layer and give me ownership over:

- Multiple LLM APIs
- Multiple accounts per provider
- API keys/endpoints
- Rate limits and quotas
- Model selection
- API switching/failover
- Persistent session context
- Agent state/checkpoints
- Usage, cost, latency, and health
- Eventually tools/MCPs and multi-agent orchestration

The fundamental UX goal is:

> **The underlying API can change without interrupting the agent's work.**

The important distinction is that **the session belongs to me/the control plane, not to a particular model endpoint.**

---

## 2. The Current Stack I Have in Mind

The basic architecture is:

```text
                    USER
                      |
                      v
              +---------------+
              |   OpenHands   |
              | Agent/Harness |
              +-------+-------+
                      |
                      v
              +---------------+
              |    LiteLLM    |
              | Proxy / Layer  |
              +-------+-------+
                      |
                      v
          +-------------------------+
          |   MY CONTROL PLANE      |
          |                         |
          |  API Dashboard          |
          |  Session Manager        |
          |  Routing / Policies     |
          |  Usage & Health         |
          |  Checkpoints            |
          +-----------+-------------+
                      |
       +--------------+--------------+
       |              |              |
       v              v              v
   Provider A     Provider B     Provider C
   / Accounts     / Accounts     / Accounts
       |              |              |
       v              v              v
     APIs           APIs           APIs
```

### Important role separation

**OpenHands**
- Agent execution/harness
- Plans and performs work
- Uses tools
- Operates on the project/workspace

**LiteLLM**
- Proxy/translation/standardization layer
- Provides a common interface to different LLM APIs
- Can be useful as a proxy between OpenHands and many providers
- Should not become the owner of my persistent session state

**My Control Plane**
- Owns API/account configuration
- Owns routing policies
- Owns session identity
- Owns persistent context/project state
- Tracks quota/rate limits/usage
- Decides when and where to switch APIs
- Provides visibility and control

---

## 3. The Main Problem I Am Solving

Suppose I am using OpenHands with a particular model through API A.

Example:

```text
OpenHands
    |
    v
LiteLLM
    |
    v
Claude Opus
via API Account #1
```

I use it continuously and eventually API Account #1 reaches a rate limit/quota/credit limit.

Instead of the task stopping, I want:

```text
API Account #1
       |
       | quota exhausted / rate limit
       v
Control Plane detects problem
       |
       v
Select API Account #2
       |
       v
Same session
       |
       v
Same project context
       |
       v
OpenHands continues working
```

The user experience should be:

> **The API changed, but the work did not stop.**

---

## 4. Multiple Providers and Accounts

I may have many APIs, potentially around 10–20 or more, from different providers/accounts.

Examples discussed include:

- OpenRouter
- Cerebras
- OmniRoute
- Google AI Studio
- Mistral
- Anthropic organization API
- Personal API accounts
- Organization/cloud accounts with API credits
- Other compatible providers

The important requirement is **not just multiple providers**.

I also want:

> **Multiple accounts within the same provider.**

For example:

```text
OpenRouter
  ├── Account 1
  ├── Account 2
  ├── Account 3
  └── Account 4
```

or:

```text
Anthropic
  ├── Account / Key 1
  ├── Account / Key 2
  └── Organization API
```

---

## 5. User-Controlled Provider Switching

A key design decision is that I do **not** necessarily want fully autonomous provider switching.

I want explicit control over routing.

For example:

```text
Policy:

Use OpenRouter only
    |
    +-- Account 1
    +-- Account 2
    +-- Account 3

Do NOT switch to Anthropic
unless I explicitly allow it.
```

So the system can automatically rotate/fail over **within an allowed pool**, while respecting my boundaries.

Example:

```text
Allowed Provider Pool:
OpenRouter

OpenRouter Account 1
       |
       | quota exhausted
       v
OpenRouter Account 2
       |
       | quota exhausted
       v
OpenRouter Account 3

STOP before moving to Anthropic
unless policy permits it.
```

This is an important part of the control plane.

---

## 6. API Dashboard

I want a dashboard where I can manage all my APIs/accounts.

Possible metadata:

```text
Provider
Account
API Key / Secret Reference
Model
Endpoint
RPM
TPM
Daily Limit
Monthly Limit
Remaining Quota
Cost
Latency
Health
Context Limit
Capabilities
Priority
Status
```

The dashboard should eventually allow:

- Add API
- Delete API
- Enable/disable API
- Edit API
- Add multiple accounts for the same provider
- Assign models
- Set priorities
- Create provider/account pools
- Define routing policies
- View usage
- View remaining quota
- View errors
- View latency
- View health
- View failovers

---

## 7. API Usage and Rate-Limit Management

The control plane should track the health and availability of each API.

For example:

```text
API #1
Model: Claude Opus
Provider: OpenRouter
Account: A1
Status: HEALTHY
Quota: 82%
Latency: 1.4s

API #2
Model: Claude Opus
Provider: OpenRouter
Account: A2
Status: HEALTHY
Quota: 51%
Latency: 1.7s

API #3
Model: Claude Opus
Provider: Anthropic
Account: Org
Status: DISABLED BY POLICY
```

When an API becomes unavailable:

```text
Request
   |
   v
API #1
   |
   +-- 429 / quota / timeout / outage
   |
   v
Control Plane
   |
   v
Check routing policy
   |
   v
Find compatible available endpoint
   |
   v
API #2
```

Important caveat:

Not every provider exposes perfectly predictable quota metadata. Therefore the system may need both:

1. **Predictive tracking** where provider information is available
2. **Reactive handling** based on actual errors/responses

---

## 8. Session Manager — The Most Important Component

The biggest architectural insight from the discussion is:

> **The session should be a first-class object.**

The API endpoint should NOT define the session.

Instead:

```text
                    SESSION ID
                        |
          +-------------+-------------+
          |             |             |
          v             v             v
      Context        Agent State    API Pointer
          |             |             |
          v             v             v
      Project        Checkpoint     Provider
      Memory                        /Account
```

The session remains stable even if the API changes.

Example:

```text
Session: PROJECT_AUTH_001

Current API:
OpenRouter / Account 1

      ↓

API exhausted

      ↓

Same Session: PROJECT_AUTH_001

New API:
OpenRouter / Account 2

      ↓

Continue
```

The session ID never changes.

---

## 9. Persistent Context

I want a context/project knowledge layer that I control locally or through infrastructure I own.

The important distinction is:

> **Do not think of it as one giant context window.**

Instead, maintain a persistent project-memory/context layer.

For example:

```text
              PERSISTENT PROJECT MEMORY
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
     Requirements     Decisions      Source Code
          |              |              |
          +--------------+--------------+
                         |
                         v
                    Retrieval
                         |
                         v
                  Context Builder
                         |
                         v
                  Active Request
                         |
                         v
                      Model
```

The persistent layer can contain:

- Project requirements
- Architecture
- Source-code knowledge
- Documentation
- Decisions
- Task history
- Previous agent outputs
- Important constraints
- Relevant user/project preferences
- Checkpoints
- Tool state
- Error history

I should be able to decide how long this project context is retained.

For an important project:

```text
Keep project context
       |
       v
Long-term persistence
```

For a temporary project:

```text
Delete session/project memory
       |
       v
Context removed
```

This gives me direct ownership of the project's persistent context.

---

## 10. Context Window vs Persistent Memory

This distinction is critical.

A model's **context window** is not the same thing as my persistent project memory.

The correct architecture is:

```text
Large Persistent Project Memory
            |
            v
       Retrieval
            |
            v
     Context Builder
            |
            v
Relevant Active Context
            |
            v
       Model Request
```

For example, I might have millions of tokens worth of project information stored persistently, but I should NOT send all of it on every request.

Instead:

```text
10M tokens stored
       |
       v
Retrieve relevant 20K / 50K / 100K tokens
       |
       v
Build model-specific context
       |
       v
Send request
```

This makes the architecture more scalable and model-independent.

---

## 11. Model Switching

If I am using the same model through different API accounts, the main goal is session continuity.

Example:

```text
Session
  |
  v
Claude model via API A
  |
  | quota exhausted
  v
Claude model via API B
  |
  v
Same session context
  |
  v
Continue task
```

The model weights themselves are not what preserve my conversation/session.

The harness/control plane must preserve the relevant state and context and construct the next request.

Therefore:

> **The model is replaceable; the session state is persistent.**

---

## 12. Switching Between Different Models

The architecture should also potentially allow:

```text
Claude
   ↓
GPT
   ↓
Gemini
```

But this is more complicated than switching accounts for the same model.

Different models can have differences in:

- Context limits
- Tool-calling formats
- Capabilities
- Reasoning behavior
- Input/output formats
- Vision support
- Tokenization
- System prompt expectations

Therefore the Context Builder should ideally construct a request appropriate for the target model.

Conceptually:

```text
Persistent Session State
        |
        v
Context Builder
        |
        +----> Claude-formatted request
        |
        +----> GPT-formatted request
        |
        +----> Gemini-formatted request
```

---

## 13. Checkpointing

The agent's work must be checkpointed so API switching does not lose progress.

Example:

```text
OpenHands
    |
    v
Working
    |
    v
Checkpoint
    |
    v
API quota exhausted
    |
    v
Switch API
    |
    v
Restore checkpoint
    |
    v
Continue
```

Checkpoint information could include:

```json
{
  "session_id": "...",
  "goal": "...",
  "plan": [],
  "completed_steps": [],
  "remaining_steps": [],
  "current_step": "...",
  "files_changed": [],
  "decisions": [],
  "errors": [],
  "tool_state": {},
  "git_state": {},
  "next_action": "..."
}
```

The checkpoint must survive:

- API switching
- Model switching
- Retries
- Agent restarts
- Temporary provider failures

---

## 14. Tool State Is Easy to Forget

A major point to keep in mind:

The context is not the only thing that matters.

An agent can have:

- Open files
- Repository state
- Terminal state
- Git state
- MCP connections
- Tool results
- Credentials/permissions
- Running tasks
- Build/test state

Therefore, seamless failover is not simply:

> "Save the chat history."

It is:

> **Preserve enough execution state that the agent can continue from the same logical point.**

---

## 15. Routing Engine

The router should eventually select an endpoint based on multiple factors.

Possible decision pipeline:

```text
Task
  |
  v
Required model
  |
  v
Required capabilities
  |
  v
Context requirements
  |
  v
Allowed provider/account pool
  |
  v
Availability
  |
  v
Quota
  |
  v
Rate limits
  |
  v
Cost
  |
  v
Latency
  |
  v
Priority
  |
  v
SELECT ENDPOINT
```

But the routing engine must respect user-defined policies first.

Example:

```text
USER POLICY
    |
    +-- Provider restriction
    +-- Model restriction
    +-- Account restriction
    +-- Cost limit
    +-- Capability requirement
    +-- Manual approval requirement
```

Then routing happens inside the permitted boundaries.

---

## 16. Failover Cases

### Rate limit

```text
429
 ↓
Retry/backoff
 ↓
Check allowed pool
 ↓
Select compatible API
```

### Quota exhaustion

```text
Remaining quota = 0
 ↓
Mark endpoint unavailable
 ↓
Select next permitted endpoint
```

### Provider outage

```text
Health check fails
 ↓
Remove endpoint from active pool
 ↓
Route elsewhere
```

### Timeout

```text
Timeout
 ↓
Retry
 ↓
Alternate compatible endpoint if required
```

### Capability mismatch

```text
Task requires vision/tool calling/etc.
 ↓
Find compatible endpoint
```

---

## 17. Dashboard View I Am Imagining

```text
+------------------------------------------------------+
|                 AI CONTROL PLANE                     |
+------------------------------------------------------+
|                                                      |
|  SESSIONS                                            |
|  ├── Project A — Running                             |
|  ├── Project B — Paused                              |
|  └── Project C — Completed                           |
|                                                      |
|  MODELS / APIS                                       |
|  ├── OpenRouter                                      |
|  │   ├── Account 1                                   |
|  │   ├── Account 2                                   |
|  │   └── Account 3                                   |
|  ├── Anthropic                                       |
|  ├── Google AI Studio                                |
|  ├── Cerebras                                        |
|  ├── Mistral                                         |
|  └── Other Providers                                  |
|                                                      |
|  CONTEXT / MEMORY                                    |
|  ├── Project Memory                                  |
|  ├── Documents                                       |
|  ├── Decisions                                       |
|  └── Checkpoints                                     |
|                                                      |
|  ROUTING                                             |
|  ├── Policies                                        |
|  ├── Provider Pools                                  |
|  ├── Model Selection                                 |
|  └── Failover Rules                                  |
|                                                      |
|  OBSERVABILITY                                       |
|  ├── Token Usage                                     |
|  ├── Cost                                            |
|  ├── Latency                                         |
|  ├── API Health                                      |
|  ├── Errors                                          |
|  └── Failovers                                       |
|                                                      |
+------------------------------------------------------+
```

---

## 18. End-to-End Example

Suppose I tell OpenHands:

> Build an authentication system.

Flow:

```text
USER
 |
 v
OPENHANDS
 |
 v
CONTROL PLANE
 |
 +--> SESSION MANAGER
 |       |
 |       +--> Session ID
 |       +--> Agent State
 |       +--> Checkpoint
 |       +--> Project Context
 |
 +--> ROUTER
 |       |
 |       +--> Policy
 |       +--> Model
 |       +--> Provider
 |       +--> Account
 |       +--> Quota
 |
 +--> LITELLM
 |
 v
MODEL API
 |
 v
AGENT WORK
 |
 +--> Read project
 +--> Plan
 +--> Modify code
 +--> Run tests
 +--> Review
 |
 v
CHECKPOINT
 |
 v
API #1 EXHAUSTED
 |
 v
CONTROL PLANE
 |
 v
API #2 SELECTED
 |
 v
RESTORE SESSION STATE
 |
 v
BUILD RELEVANT CONTEXT
 |
 v
LITELLM
 |
 v
MODEL API #2
 |
 v
CONTINUE WORK
 |
 v
TEST
 |
 v
REVIEW
 |
 v
FINAL RESULT
```

The key point is that **the API changed, not the task.**

---

## 19. What I Think the Product Actually Is

I should NOT describe this merely as:

> "An OpenHands API dashboard."

A better description is:

> **An AI Agent Control Plane / AI Session OS**

OpenHands is the execution engine.

LiteLLM is a proxy/compatibility layer.

My control plane is the persistent layer that manages:

**Sessions + Models + Accounts + Quotas + Context + Memory + Routing + Failover + Checkpoints + Tools + Security + Observability**

The core abstraction is:

> **A persistent agent session that is independent of the underlying API endpoint.**

---

## 20. What I Would Build First

If I were implementing this, I would deliberately start small.

### Phase 1 — Prove session continuity

Build only:

```text
OpenHands
   |
LiteLLM
   |
My Control Plane
   |
2 APIs / 2 accounts
```

Goal:

```text
API 1
 ↓
Agent works
 ↓
API 1 gets 429/quota exhausted
 ↓
API 2
 ↓
Same session
 ↓
Same context
 ↓
Agent continues
```

This is the first major proof-of-concept.

### Phase 2 — API Dashboard

Add:

- Provider management
- Account management
- API keys/secrets
- Model mapping
- Health
- Usage
- Quota
- Rate-limit tracking

### Phase 3 — Routing Policies

Add:

- Provider pools
- Account pools
- Model restrictions
- Priority
- Cost limits
- User-controlled failover

### Phase 4 — Persistent Project Memory

Add:

- Session storage
- Project memory
- Retrieval
- Summarization
- Context construction
- Long-term project persistence

### Phase 5 — Checkpointing

Make agent state recoverable across:

- API failures
- Restarts
- Model switches
- Session pauses/resumes

### Phase 6 — Observability

Track:

- Requests
- Tokens
- Cost
- Latency
- Provider
- Account
- Model
- Errors
- Retries
- Failovers

### Phase 7 — Tools/MCP

Add a tool manager that keeps tools independent from the model.

### Phase 8 — Multi-Agent

Only after the core session/control-plane system works:

```text
Supervisor
   |
   +-- Research Agent
   +-- Coding Agent
   +-- Testing Agent
   +-- Review Agent
```

---

## 21. What I Must Learn

Learning order:

```text
1. System Architecture
        ↓
2. API Gateway / Proxy Architecture
        ↓
3. LLM APIs
        ↓
4. LiteLLM
        ↓
5. Rate Limits / Quotas
        ↓
6. Model Routing
        ↓
7. Context Engineering
        ↓
8. Memory / Retrieval
        ↓
9. Agent State
        ↓
10. Checkpointing
        ↓
11. MCP / Tools
        ↓
12. Multi-Agent Orchestration
        ↓
13. Sandboxing
        ↓
14. Observability
        ↓
15. Security
        ↓
16. Distributed Systems
        ↓
17. Implementation
```

I do not need to master every distributed-systems concept before starting.

Learn queues, workers, caches, databases, event buses, retries, idempotency, locks, and health checks as they become relevant.

---

## 22. First System-Design Exercise

Before building the whole platform, solve this:

> **An OpenHands agent sends an LLM request. The API returns 429. The system chooses another permitted API for the same model, preserves the agent/session state, retries the request, and continues the task.**

Then scale:

```text
1 API
 ↓
2 APIs
 ↓
10 APIs
 ↓
Multiple accounts
 ↓
Quota tracking
 ↓
Routing policies
 ↓
Persistent session context
 ↓
Project memory
 ↓
Checkpointing
 ↓
MCP/tool manager
 ↓
Multiple agents
 ↓
Sandbox
 ↓
Deployment
 ↓
Observability
```

---

## 23. Important Technical Mental Model

Do not think:

```text
Model = Session
```

Think:

```text
Session
   |
   +-- Agent State
   +-- Project Context
   +-- Memory
   +-- Checkpoints
   +-- Workspace State
   +-- Tool State
   +-- Routing Policy
   |
   +-- Current Model/API
```

The **current model/API is only one attribute of the session**.

Therefore:

```text
SESSION_001
     |
     +--> API A
     |
     |  switch
     v
     +--> API B
     |
     |  switch
     v
     +--> API C
```

The session remains `SESSION_001`.

---

## 24. Important Risks / Things to Validate

These are areas I should investigate rather than assume:

1. Exactly how OpenHands exposes/configures LiteLLM.
2. How OpenHands stores agent/session state.
3. What state can safely be reconstructed after an API failure.
4. Which provider quota/rate-limit signals are available programmatically.
5. Whether switching accounts violates any provider's terms or account policies.
6. How model-specific context limits should be handled.
7. How tool calls behave if a request fails halfway through.
8. How to make retries idempotent.
9. How to securely store API credentials.
10. How to prevent one failed provider from corrupting the agent's logical state.
11. How to distinguish a failed request from a successfully executed tool call whose response was lost.
12. How to preserve Git/workspace consistency.
13. How to handle switching between genuinely different models.
14. How to keep the control plane from becoming a single point of failure.

These should be treated as engineering/research questions, not already-solved assumptions.

---

## 25. The Most Important Architectural Insight

The most important idea to preserve when continuing this project is:

> **I am not primarily building an API key manager. I am building a persistent AI agent session/control layer.**

The API can change.

The provider can change.

The account can change.

The model can potentially change.

But:

**the agent's logical work should continue.**

That is the central product idea.

---

## 26. Current Working Definition

### Project

**AI Agent Control Plane for OpenHands**

### Core stack

```text
OpenHands
    +
LiteLLM
    +
My Control Plane
    +
Persistent Session / Context Layer
    +
API / Account Dashboard
```

### Core promise

> **Use many APIs and accounts without losing the agent session or project context.**

### Core differentiator

> **API continuity is not required for task continuity.**

### Long-term vision

```text
                 AI AGENT CONTROL PLANE
                         |
       +-----------------+-----------------+
       |                 |                 |
       v                 v                 v
    SESSIONS          ROUTING           MEMORY
       |                 |                 |
       v                 v                 v
    CHECKPOINTS       APIs/Accounts    CONTEXT
       |                 |                 |
       +-----------------+-----------------+
                         |
                         v
                      OPENHANDS
                         |
                         v
                   AGENT EXECUTION
```

---

## 27. How to Continue This Project in a New Chat

Start the next session with this file and tell the assistant:

> "This is my current architecture for an OpenHands AI Agent Control Plane. Read it first. Continue from the existing design instead of restarting the discussion. Help me turn the architecture into an implementable system design, beginning with the smallest proof-of-concept: OpenHands + LiteLLM + two API accounts + persistent session state + seamless same-model failover."

Then focus on implementation questions one at a time.

**Do not jump directly into building the entire platform. Prove session continuity first.**
