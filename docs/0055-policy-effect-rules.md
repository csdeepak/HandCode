---
Number:        0055
Title:         A Policy's Effect Rules Hold for Every Class
Type:          DECISION
Status:        ACCEPTED
Created:       2026-10-04
Supersedes:    —
Superseded-by: —
Depends-on:    0025, 0030, 0049, 0052
---

# 0055 — A Policy's Effect Rules Hold for Every Class

## 1. The defect

A policy's `effects:` maps an effect class to a rule. The compiler
(`control/policy/compile.py`) accepts four rules for any of the five classes.
Its own comment says why the list is short: a rule nothing implements
*"would compile and then do nothing, which is the failure mode this file
exists to prevent."*

The runner read one rule for one class:

| Rule | Compiled for | Enforced before this fix |
|---|---|---|
| `require_human_approval` | any class | `DESTRUCTIVE` only |
| `block` | any class | **nowhere** |
| `allow` | any class | nowhere |
| `reconcile_or_block` | any class | always, by the gate itself, so correct as written |

The worst row is `block`. A policy saying `external: block` compiled,
`agentctl policy` printed `EXTERNAL block`, and every external effect then
ran. It was fail-open, silently, in the one layer that promises to fail
closed.

It was found while reading the runner for an experiment on external effects.
That experiment was not carried out, so nothing about prompt injection is
claimed here. Issue-triggered runs of the GitHub Action stay off (`0053`).

## 2. The decision

`runner._effect_rules(policy)` gives every class's rule, and
`_install_confirmation` acts on all of them:

| Rule | Now |
|---|---|
| `block` | refused. Recorded FAILED ("blocked by your policy"), never BLOCKED, so it is not listed as waiting for approval. The agent is told not to reach the same effect another way |
| `require_human_approval` | asked at a terminal, queued without one (`0049`), for any class |
| `allow` on `DESTRUCTIVE` | not asked, as with `--allow-destructive` |
| `reconcile_or_block` | nothing beyond the gate |

**`--allow-destructive` turns off the built-in questions:**
- destructive actions;
- writes outside the workspace;
- installs.

**It does not turn off a policy's `block` or `require_human_approval`.** A
command-line flag must not quietly loosen a rule the operator wrote down. The
flag's help now says so.

A run without `--policy` behaves exactly as before. Every existing caller of
`_install_confirmation` uses the defaults (no rules, the questions on), and
the suite's existing tests of it pass unchanged.

## 3. Evidence

**`tests/test_policy_rules.py`, 10 tests:**
- `require_human_approval` on EXTERNAL queues the action (BLOCKED, awaiting
  approval);
- `block` refuses it, and its record is not BLOCKED;
- neither is loosened by `confirm=False` (`--allow-destructive`);
- `allow` on DESTRUCTIVE stops the question for `rm -rf build`;
- a rule on one class leaves reads alone;
- a policy file yields every rule;
- **two end-to-end runs** of `agentctl run --policy`, with the scripted model
  (`tests/scripted_model.py`) writing `hello.txt`:
  - under `idempotent_write: block`, nothing is written and nothing waits;
  - under `idempotent_write: require_human_approval`, nothing is written,
    one action waits, and the exit code is 1.

**The end-to-end tests fail on the old runner.** With `runner.py` from `HEAD`
put back, both fail on `assert not wrote`: the scripted agent wrote the file
under a policy forbidding it. With the fix, both pass.

The full suite: 894 passed, 3 skipped.
