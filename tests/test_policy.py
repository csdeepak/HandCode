r"""Policy: compiled out of band, looked up in band. M7, `docs/0030`.

Two halves, tested separately because they fail differently:

* the **compiler** must refuse a policy that is wrong, listing every problem
* the **kernel** must only look things up, and must never need the compiler

The compiler tests are mostly about what it *rejects*. A policy DSL that
accepts everything has moved the errors from compile time to run time, which
is the one thing `docs/0012` §5.2 forbids -- in-band, the only available
response is to fail closed and stop the work.
"""
from __future__ import annotations

import json

import pytest

from agentctl.control.policy import PolicyError, compile_policy, compile_to
from agentctl.kernel.policy import Policy

MINIMAL = {"pools": {"free": ["a/b"]}, "routing": {"default_pool": "free"}}


# ── what the compiler refuses ──────────────────────────────────────────
def _problems(doc: dict) -> list[str]:
    with pytest.raises(PolicyError) as e:
        compile_policy(doc)
    return e.value.problems


def test_a_typo_in_an_effect_class_is_an_error_not_a_warning():
    """This is the one that matters most.

    `desctructive` is not a syntax error. Accepted, it would compile into an
    artifact where DESTRUCTIVE has no rule at all -- so the most dangerous
    class silently stops requiring approval. Policy that fails OPEN on a typo
    is worse than no policy, because it reads like protection.
    """
    p = _problems({"effects": {"desctructive": "require_human_approval"}})
    assert any("unknown effect class" in x for x in p)
    assert any("did you mean DESTRUCTIVE" in x for x in p)


def test_an_undefined_pool_is_caught_at_compile_time():
    assert any("'paid' is not defined" in x
               for x in _problems({"pools": {"free": ["a"]},
                                   "routing": {"default_pool": "paid"}}))


def test_escalating_to_an_undefined_pool_is_caught():
    assert any("escalate_to.pool" in x for x in _problems(
        {"pools": {"free": ["a"]},
         "routing": {"default_pool": "free", "escalate_to": {"pool": "gold"}}}))


def test_escalating_to_the_same_pool_is_caught():
    """Compiles fine and means nothing, which is worse than an error."""
    assert any("would change nothing" in x for x in _problems(
        {"pools": {"free": ["a"]},
         "routing": {"default_pool": "free", "escalate_to": {"pool": "free"}}}))


def test_a_daily_cap_below_the_per_task_cap_is_incoherent():
    assert any("can never bind" in x for x in _problems(
        {"budget": {"daily_usd": 0.5, "per_task_usd": 2.0}}))


def test_a_rule_no_one_implements_is_refused():
    """A verb nothing enforces would compile and then quietly do nothing."""
    assert any("unknown rule" in x for x in _problems(
        {"effects": {"destructive": "email_my_manager"}}))


@pytest.mark.parametrize("doc,expect", [
    ({"budget": {"per_task_usd": -1}}, "must be positive"),
    ({"budget": {"per_task_usd": 1, "on_exceeded": "shrug"}}, "on_exceeded"),
    ({"budget": {"per_task_usd": 1, "dailyusd": 2}}, "unknown budget key"),
    ({"budget": {"on_exceeded": "block"}}, "sets no cap"),
    ({"pools": {"free": ["a", "a"]}}, "same deployment twice"),
])
def test_more_refusals(doc, expect):
    assert any(expect in x for x in _problems(doc))


def test_every_problem_is_reported_not_just_the_first():
    """Fixing a policy one error per run is a bad afternoon."""
    p = _problems({"pools": {"free": ["a", "a"]},
                   "budget": {"daily_usd": 0.1, "per_task_usd": 9.0},
                   "effects": {"destructive": "nonsense"}})
    assert len(p) >= 3


def test_a_policy_with_no_budget_is_valid():
    """Not configuring a cap is a choice, not a mistake."""
    assert compile_policy(MINIMAL)["budget"] == {}


def test_escalation_requires_confirmation_by_default():
    """`docs/0002` §5: never silently spend.

    Omitting the key must not authorise paid traffic.
    """
    c = compile_policy({"pools": {"free": ["a"], "paid": ["b"]},
                        "routing": {"default_pool": "free",
                                    "escalate_to": {"pool": "paid"}}})
    assert c["routing"]["escalation"]["require_confirmation"] is True


# ── what the kernel does with it ───────────────────────────────────────
def test_the_kernel_only_reads(tmp_path):
    path = compile_to_tmp(tmp_path)
    pol = Policy.load(path)
    assert pol.default_pool == "free"
    assert pol.pool("paid") == ["b/c"]
    assert pol.requires_approval("DESTRUCTIVE") is True
    assert pol.limit("per_task") == 0.5


def compile_to_tmp(tmp_path):
    src = tmp_path / "policy.yaml"
    src.write_text(
        "version: 1\n"
        "pools:\n  free: [a/b]\n  paid: [b/c]\n"
        "routing:\n  default_pool: free\n"
        "  escalate_to: {pool: paid}\n"
        "budget:\n  per_task_usd: 0.50\n  daily_usd: 2.00\n"
        "effects:\n  destructive: require_human_approval\n", encoding="utf-8")
    return compile_to(src, tmp_path / "policy.compiled.json")


def test_a_missing_policy_says_how_to_make_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="agentctl policy compile"):
        Policy.load(tmp_path / "nope.json")


def test_an_empty_policy_enforces_nothing():
    pol = Policy.empty()
    assert not pol
    assert pol.requires_approval("DESTRUCTIVE") is False
    assert pol.check_budget(999.0).allowed is True


def test_the_artifact_records_which_source_it_came_from(tmp_path):
    path = compile_to_tmp(tmp_path)
    assert len(Policy.load(path).source_sha256) == 64


# ── the budget guard ───────────────────────────────────────────────────
BUDGET = Policy({"budget": {"per_task_usd": 0.50, "on_exceeded": "block",
                            "on_unpriced": "warn"}})


@pytest.mark.parametrize("spent,allowed", [
    (0.00, True), (0.49, True), (0.50, False), (0.75, False),
])
def test_the_cap_actually_binds(spent, allowed):
    assert BUDGET.check_budget(spent, "per_task").allowed is allowed


def test_warn_lets_the_work_continue_and_says_so():
    p = Policy({"budget": {"per_task_usd": 0.5, "on_exceeded": "warn"}})
    v = p.check_budget(9.0, "per_task")
    assert v.allowed is True and "over budget" in v.reason


def test_an_unpriced_call_makes_the_figure_a_lower_bound():
    """`docs/0021` §5: litellm reports 0.0 for endpoints it cannot price.

    A cap compared against measured spend under-blocks, always in the direction
    of spending more than intended. The verdict must not hide that.
    """
    v = BUDGET.check_budget(0.10, "per_task", coverage=0.33)
    assert v.allowed is True                    # on_unpriced: warn
    assert v.trustworthy is False
    assert "HIGHER" in v.describe() and "33%" in v.describe()


def test_blocking_on_incomplete_pricing_is_available():
    strict = Policy({"budget": {"per_task_usd": 0.5, "on_unpriced": "block"}})
    v = strict.check_budget(0.10, "per_task", coverage=0.33)
    assert v.allowed is False and "could be priced" in v.reason


def test_full_coverage_reports_a_plain_number():
    v = BUDGET.check_budget(0.10, "per_task", coverage=1.0)
    assert v.trustworthy and "HIGHER" not in v.describe()


def test_no_configured_limit_allows_anything():
    assert Policy({"budget": {}}).check_budget(10_000.0).allowed is True


# ── the boundary this whole design exists to keep ──────────────────────
def test_the_kernel_never_imports_the_compiler():
    """`docs/0008` R2 -- and the reason M7 is split in two at all.

    Checked on the import graph, not on the text: the kernel legitimately
    names a *path* into `control/` to read the compiled artifact, exactly as
    `classify.py` reads `tools.yaml`. Reading a file the control plane wrote
    is the design. Importing the code that wrote it is the violation.
    """
    import ast
    import pathlib

    import agentctl.kernel.policy as kp

    tree = ast.parse(pathlib.Path(kp.__file__).read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    offenders = [m for m in imported
                 if "control" in m or "litellm" in m or "openhands" in m]
    assert not offenders, f"kernel/policy.py imports {offenders}"


def test_the_kernel_reads_the_artifact_by_path():
    """The other half of the same rule: it must still FIND the compiled file."""
    from agentctl.kernel.policy import DEFAULT_POLICY

    assert DEFAULT_POLICY.name == "policy.compiled.json"
    assert "control" in DEFAULT_POLICY.parts


def test_the_budget_guard_is_given_the_spend_never_fetches_it():
    """A guard that queried a database in-band would fail when it was down."""
    import inspect
    sig = inspect.signature(Policy.check_budget)
    assert "spent_usd" in sig.parameters and "coverage" in sig.parameters


# ══ Phase 10.4: a declaration nothing enforces ═══════════════════════
def test_tiering_is_refused_rather_than_compiled_into_nothing():
    """It used to compile, validate, and be read by no one.

    `docs/0030` recorded that at the time, expecting `control/proxy.py` to
    grow a routing loop that consumed it. It never did. A block that compiles
    cleanly reads like protection, and M7's own title is that a policy
    failing open is worse than no policy — so the honest handling is to
    refuse it where the user is watching.
    """
    import pytest

    from agentctl.control.policy.compile import compile_policy

    with pytest.raises(Exception) as e:
        compile_policy({"tiering": {"planning": {"min_tier": "frontier"}}})
    assert "tiering" in str(e.value).lower()
    assert "not implemented" in str(e.value).lower()


def test_a_policy_without_tiering_still_compiles():
    """Refusing the dead key must not break every other policy."""
    from agentctl.control.policy.compile import compile_policy

    out = compile_policy({"budget": {"daily_usd": 1.0}})
    assert out["tiering"] == {}
