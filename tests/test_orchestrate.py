r"""The split is the feature.

`docs/0040` §6.1 measured what an even split costs: a leg with one quota set
the pace for a leg with six, and the whole job ran at ×1.55 instead of ×4.33.
The fix is not more quota, it is allocation — so these tests are about the
shape of the plan, not about running anything.

They use explicit `ratio=` throughout rather than the live registry, because a
test that changes meaning when the owner adds a key is not testing the
allocator.
"""
import pytest

from agentctl.runtime.orchestrate import Leg, allocate, describe, fan_out, weights


def items(n: int) -> list[str]:
    return [f"f{i}.py" for i in range(n)]


def split(legs: list[Leg]) -> dict[str, int]:
    return {lg.source: len(lg.items) for lg in legs}


# ══ allocation ═══════════════════════════════════════════════════════
def test_the_scarce_source_carries_less():
    """One quota against six: the whole point."""
    legs = allocate(items(12), ["gemini", "mistral"],
                    ratio={"gemini": 1, "mistral": 6})
    assert split(legs) == {"gemini": 2, "mistral": 10}


def test_an_even_ratio_splits_evenly():
    """The allocator must not invent asymmetry that is not there."""
    legs = allocate(items(12), ["a", "b"], ratio={"a": 3, "b": 3})
    assert split(legs) == {"a": 6, "b": 6}


def test_every_item_is_allocated_exactly_once():
    """Largest-remainder, so nothing is dropped or double-counted."""
    for n in range(1, 40):
        legs = allocate(items(n), ["a", "b", "c"],
                        ratio={"a": 1, "b": 5, "c": 3})
        got = [i for lg in legs for i in lg.items]
        assert len(got) == n and len(set(got)) == n, f"{n} items mis-split"


def test_a_source_with_no_quota_gets_nothing():
    legs = allocate(items(10), ["live", "dead"],
                    ratio={"live": 4, "dead": 0})
    assert split(legs) == {"live": 10, "dead": 0}


def test_a_leg_that_would_carry_nothing_is_dropped_not_dispatched():
    """A zero-item leg still costs a report request and returns nothing.

    Paying one request to learn nothing is strictly worse than not
    dispatching, so the scarce leg is dropped rather than given an empty
    share.
    """
    legs = allocate(items(2), ["scarce", "rich", "richer"],
                    ratio={"scarce": 1, "rich": 6, "richer": 6})
    assert split(legs)["scarce"] == 0
    assert sum(len(lg.items) for lg in legs) == 2
    assert all(lg.requests == 0 for lg in legs if not lg.items)


def test_allocation_is_deterministic():
    """Two runs of the same job must be comparable."""
    a = split(allocate(items(17), ["x", "y", "z"],
                       ratio={"x": 1, "y": 2, "z": 4}))
    b = split(allocate(items(17), ["x", "y", "z"],
                       ratio={"x": 1, "y": 2, "z": 4}))
    assert a == b


def test_no_items_means_no_requests():
    legs = allocate([], ["a", "b"], ratio={"a": 1, "b": 1})
    assert sum(lg.requests for lg in legs) == 0


def test_weights_default_to_the_registry_quota_count():
    """Gemini's six keys are one quota (`docs/0039` §7)."""
    env = {f"GEMINI_API_KEY{s}": "k" for s in ("", "_2", "_3")}
    env.update({f"MISTRAL_API_KEY{s}": "k" for s in ("", "_2", "_3")})
    w = weights(["gemini", "mistral"], env=env)
    assert w == {"gemini": 1, "mistral": 3}


# ══ the plan a human reads ═══════════════════════════════════════════
def test_the_plan_explains_why_it_is_uneven():
    """An uneven split with no reason given reads like a bug."""
    out = describe(allocate(items(12), ["gemini", "mistral"],
                            ratio={"gemini": 1, "mistral": 6}))
    assert "gemini carries less" in out
    assert "1 quota(s) to mistral's 6" in out


def test_the_plan_is_ascii():
    """Non-ASCII in rendered output has broken this project five times."""
    out = describe(allocate(items(9), ["gemini", "mistral"],
                            ratio={"gemini": 1, "mistral": 6}))
    out.encode("cp437")


def test_an_even_plan_does_not_explain_an_asymmetry_it_does_not_have():
    out = describe(allocate(items(4), ["a", "b"], ratio={"a": 2, "b": 2}))
    assert "carries less" not in out


# ══ dispatch ═════════════════════════════════════════════════════════
def test_each_leg_is_told_only_its_own_items():
    seen = {}

    def fake(defn, task, **kw):
        seen[kw.get("model") or "direct"] = task
        return "ok"

    legs = allocate(items(6), ["gemini", "mistral"],
                    ratio={"gemini": 1, "mistral": 2})
    fan_out(object(), "where is X?", legs, base_url="http://p", runner=fake)

    # Derived from the plan, not assumed: a scout must be told its own items
    # and must not see another leg's, whatever the split turned out to be.
    for leg in legs:
        task = seen[f"openai/pool-{leg.source}"]
        mine = set(leg.items)
        theirs = {i for other in legs for i in other.items} - mine
        assert mine and all(i in task for i in mine)
        assert not any(i in task for i in theirs), \
            f"{leg.source} was shown another leg's items"
        assert "where is X?" in task


def test_one_leg_failing_does_not_lose_the_others():
    """A recon job short one scout returns what the rest found, visibly."""
    def flaky(defn, task, **kw):
        if "pool-gemini" in (kw.get("model") or ""):
            raise RuntimeError("429 daily cap")
        return "mistral found it"

    legs = allocate(items(6), ["gemini", "mistral"],
                    ratio={"gemini": 1, "mistral": 2})
    fan_out(object(), "q", legs, base_url="http://p", runner=flaky)

    by = {lg.source: lg for lg in legs}
    assert by["gemini"].report is None and "429" in by["gemini"].error
    assert by["mistral"].report == "mistral found it"
    assert by["mistral"].error is None


def test_an_empty_leg_is_never_dispatched():
    calls = []
    legs = allocate(items(2), ["scarce", "rich", "richer"],
                    ratio={"scarce": 1, "rich": 6, "richer": 6})
    fan_out(object(), "q", legs, base_url="http://p",
            runner=lambda d, t, **k: calls.append(k.get("model")) or "ok")
    assert "openai/pool-scarce" not in calls
