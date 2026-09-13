---
Number:        0030
Title:         M7 — A Policy That Fails Open Is Worse Than No Policy
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-13
Supersedes:    —
Superseded-by: —
Depends-on:    0008, 0012, 0021
---

# 0030 — M7: A Policy That Fails Open Is Worse Than No Policy

The last milestone. A budget cap that actually stops a run, an escalation that
asks before spending, and a compiler whose job is to make sure neither of those
can be silently wrong.

**362 tests passing** (was 332). Code: `control/policy/compile.py`,
`kernel/policy.py`. Experiment: `0009-m7-policy`. `verify.py` now has 10 checks.

---

## 1. The split, and why it is the whole design

`docs/0012` §5.2 is one sentence: *"compiles to a flat lookup artifact the
kernel reads from disk — no evaluation logic in-band."*

    control/policy/compile.py     validates, resolves, refuses      out of band
    kernel/policy.py              looks things up                   in band

This is the same trick as the capability matrix, and it exists for the reason
in `docs/0008` R2: the kernel must keep working when the control plane is dead.
A policy engine that parsed YAML in-band would make every run depend on the
policy being correct *at that moment*, and the only response available in-band
is to fail closed and stop the work.

So the kernel's policy module contains no YAML, no schema, no defaults
resolution, and no `if` on a pool name. The test that keeps it that way checks
the **import graph**, not the text — the kernel legitimately names a *path*
into `control/` to read the artifact. Reading a file the control plane wrote is
the design; importing the code that wrote it is the violation.

## 2. What a compiler is actually for

Not reformatting YAML. **Deciding where the errors happen.**

```
pool "paid" is not defined (routing.escalate_to.pool)
daily_usd 0.50 is below per_task_usd 2.00 -- the daily cap can never bind
routing.escalate_to.pool is the default pool, so escalation would change nothing
unknown effect class 'desctructive' -- did you mean DESTRUCTIVE?
unknown rule 'email_my_manager' for DESTRUCTIVE
```

The fourth is the one that justifies the milestone.

`desctructive` is not a syntax error. A lenient compiler accepts it and emits
an artifact in which `DESTRUCTIVE` **has no rule at all** — so the most
dangerous effect class silently stops requiring approval, and the policy file
still reads like protection. The failure is invisible, and it is in the
direction of less safety.

> **A policy that fails open on a typo is worse than no policy**, because it
> buys confidence it has not earned.

Unknown keys are therefore errors, never warnings, in every section. And every
problem is reported at once — fixing a policy one error per run is a bad
afternoon.

`require_confirmation` defaults to **true** for the same reason (`docs/0002`
§5): omitting a key must not authorise paid traffic.

## 3. A budget cap built on an untrustworthy number under-blocks

This is where M7 collides with M5, and the collision is the interesting part.

`docs/0021` §5 found litellm reports cost `0.0` for endpoints it cannot price —
indistinguishable from a call that was genuinely free. So measured spend is a
**lower bound**, and a cap compared against it under-blocks, always in the
direction of spending more than intended.

Hiding that would make the cap a decoration. Every verdict carries the coverage
it was computed from:

```
$0.1000 of $0.50 (per_task) — but only 33% of calls could be priced,
                              so the real spend is HIGHER
```

What to *do* about incomplete pricing is stated by the policy, not decided
quietly by the guard:

| `on_unpriced` | |
|---|---|
| `warn` (default) | keep working, say so — fail open, per `docs/0008` §6.5 where cost decisions fail open and only effect decisions fail closed |
| `block` | stop when measurement is incomplete — honest, and on a free-tier pool that is most of the time |

Neither is right in general. Making it a policy key is the point: the person
who set the cap is the person who should choose.

## 4. The spend is supplied, never fetched

`Policy.check_budget(spent_usd, scope, coverage)` takes the number. It does not
query the cost ledger, because it cannot — the ledger is control-plane and the
kernel may not import it.

That constraint produced the better design. A guard that queried a database
in-band would fail whenever the control plane was down, turning a **cost**
feature into an **availability** problem. The runtime reads the ledger and
hands over a float; the kernel compares two numbers.

## 5. Enforced before anything happens

A budget check that runs after the work is an audit, not a cap. So enforcement
happens before the effect ledger, before the agent, before a single token:

```
$ agentctl run "..." --policy policy.yaml
refusing to start: budget exceeded: $1.5000 of $1.00 (daily)
  raise budget.daily_usd, or wait for the window to roll.
```

and leaving the default pool asks first:

```
!! anthropic/sonnet is not in the default pool 'free_tier' (the 'paid' pool)
   spend on it? [y/N]
```

A policy naming `DESTRUCTIVE: require_human_approval` also turns the
confirmation on regardless of command-line flags. Policy tightens; it never
loosens.

Replay is exempt: it spends nothing, so a budget cannot bind and a stale cost
ledger must not stop an offline run.

## 6. What is declared but not enforced

Stated plainly, because a policy file that looks enforced and is not would be
the exact failure this document is about.

- **`pools` and `tiering` are declarations.** Routing across a pool is the
  LiteLLM proxy's job (`docs/0021`); `agentctl run` talks to one model. What is
  enforced at run level is the *boundary* — using something outside the default
  pool asks first. Which member of a pool gets picked is not decided here.
- **`or_after_failures` and `requires_capability` are recorded, not acted on.**
  They belong to the proxy's routing loop.
- **`daily_usd` is checked at the start of a run, not continuously.** A single
  long run can exceed it. Per-task is enforced mid-run through the SDK's own
  `max_budget_per_run` (`docs/0015` §4, Q17), which is why the policy targets
  that rather than reimplementing it.

## 7. Consequences

- `docs/0012` §7 → **M7 complete. Every milestone M0–M7 is now done.**
- `docs/0012` §6 → new rule: a config compiler must reject unknown keys, because
  the failure mode of accepting them is silent and unsafe.
- `docs/0021` §5 → its finding now has teeth: coverage is an input to a
  decision, not just a display column.
- `README` → `agentctl policy` compiles and shows; `--policy` enforces.
