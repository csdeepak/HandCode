r"""Choosing one source, and being told what it costs.

The owner asked for a models section where you pick a source and can switch to
another API of the same source. `research/phase-10-3-model-selection.md` §6.5
specified it and said the thing that makes it honest:

    selecting a source narrows the failover pool from 42 deployments to that
    source's share ... The picker should therefore show, at the moment of
    selection, how many deployments and how many accounts the choice leaves --
    and default to `pool`.

So these tests are as much about the warning as the feature. A picker that
lists names without the cost is offering a downgrade without saying so, and
the downgrade is exactly the failure `docs/0033` and the multi-account design
exist to escape: one source can mean one account-wide daily cap with nothing
behind it.
"""
import yaml

from agentctl.control.proxy import (
    PAID, POOL, SOURCE_PREFIX, _validate, build, parse_deployment_id, sources,
)

# Two providers, two accounts each. Small enough to assert exact numbers.
ENV = {
    "OPENROUTER_API_KEY": "k1", "OPENROUTER_API_KEY_2": "k2",
    "GEMINI_API_KEY": "k3", "GEMINI_API_KEY_2": "k4",
}
ONE = {"OPENROUTER_API_KEY": "k1"}


def groups(cfg: str) -> dict[str, int]:
    doc = yaml.safe_load(cfg)
    out: dict[str, int] = {}
    for m in doc["model_list"]:
        out[m["model_name"]] = out.get(m["model_name"], 0) + 1
    return out


# ══ the config ═══════════════════════════════════════════════════════
def test_every_source_gets_its_own_group_beside_the_pool():
    g = groups(build(ENV))
    assert g[POOL] > 0, "the wide default must survive"
    assert g[f"{SOURCE_PREFIX}openrouter"] > 0
    assert g[f"{SOURCE_PREFIX}gemini"] > 0
    # A source group is a second NAME for the same deployments, so each
    # source's count must match its share of the pool, not add to it.
    assert g[f"{SOURCE_PREFIX}openrouter"] + g[f"{SOURCE_PREFIX}gemini"] == g[POOL]


def test_a_single_source_gets_no_group_because_there_is_no_choice():
    """One provider means `pool` and `pool-x` would be the same set."""
    g = groups(build(ONE))
    assert g == {POOL: g[POOL]}, f"nothing to choose between: {g}"


def test_source_group_ids_stay_unique():
    """A duplicate id sends a fallback to whichever litellm resolved first."""
    ids = [m["model_info"]["id"] for m in yaml.safe_load(build(ENV))["model_list"]]
    assert len(set(ids)) == len(ids), f"duplicate deployment ids: {ids}"


def test_the_generated_config_still_validates():
    """The validator used to forbid any group but pool/paid."""
    _validate(build(ENV))


def test_a_source_copy_parses_as_the_same_deployment():
    """`-only` is a narrower NAME, not another deployment.

    A caller counting deployments must not count it twice, so both ids must
    resolve to the same triple.
    """
    assert parse_deployment_id("gemini-a2-m0-only") == ("gemini", 2, 0)
    assert parse_deployment_id("gemini-a2-m0-only") == parse_deployment_id(
        "gemini-a2-m0")


def test_paid_never_appears_in_a_source_group():
    """Asking to route to one provider must not become asking to spend."""
    env = dict(ENV, ANTHROPIC_API_KEY="paid")
    doc = yaml.safe_load(build(env))
    paid_models = {m["litellm_params"]["model"] for m in doc["model_list"]
                   if m["model_name"] == PAID}
    assert paid_models, "fixture is wrong: no paid deployment to test with"
    for m in doc["model_list"]:
        if m["model_name"].startswith(SOURCE_PREFIX):
            assert m["litellm_params"]["model"] not in paid_models, \
                f"{m['model_name']} would silently spend money"


# ══ the cost, which is the point ══════════════════════════════════════
def test_every_source_says_what_choosing_it_gives_up():
    rows = sources(ENV)
    assert rows, "no sources built from a two-provider environment"
    total = sum(r["deployments"] for r in rows)
    for r in rows:
        assert r["gives_up"] == total - r["deployments"], \
            f"{r['source']} misreports its cost"
        assert r["accounts"] >= 1


def test_the_widest_source_is_listed_first():
    """The safe choice reads first; a narrower one is a deliberate step down."""
    rows = sources(ENV)
    assert rows == sorted(rows, key=lambda r: (-r["deployments"], r["source"]))


def test_a_source_carries_its_real_account_count():
    """Two accounts at one provider are two quotas (`docs/0033`)."""
    row = next(r for r in sources(ENV) if r["source"] == "openrouter")
    assert row["accounts"] == 2


def test_sources_are_empty_without_keys():
    assert sources({}) == []
