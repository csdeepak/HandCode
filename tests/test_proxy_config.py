r"""Generated proxy config. `docs/0031`.

The generator emitted `["a" "b"]` -- a missing comma -- and returned it
happily. The proxy would have failed to start with a YAML error pointing at a
file the user never wrote. So it now parses its own output, and these tests
check that it CAN fail: a generator whose validation cannot reject anything is
the shape of `docs/0028` §5.
"""
from __future__ import annotations

import pytest
import yaml

from agentctl.control.proxy import (accounts, available, build, write,
                                    parse_deployment_id, _validate)


ONE = {"OPENROUTER_API_KEY": "x"}
TWO = {"OPENROUTER_API_KEY": "x", "MISTRAL_API_KEY": "y"}


def test_the_output_is_valid_yaml():
    assert yaml.safe_load(build(ONE))


def test_every_free_deployment_is_in_the_pool():
    """That shared group is what makes them a pool rather than separate models.

    Source groups (`pool-gemini`) added a SECOND name for some of these, so
    the assertion is no longer "one group exists" but the property that
    always mattered: nothing free is missing from `pool` (`docs/0039`).
    """
    d = yaml.safe_load(build(TWO))
    free = {m["model_info"]["id"] for m in d["model_list"] if m["model_info"]["free"]}
    pooled = {m["model_info"]["id"] for m in d["model_list"]
              if m["model_name"] == "pool"}
    assert free and pooled
    assert {i.removesuffix("-only") for i in free} == pooled,         "a free deployment reachable only through a source group cannot fail over"


def test_there_is_no_automatic_fallback_to_paid():
    """This test used to require `fallbacks`, and requiring it was wrong twice.

    First, it pointed at `model_info.id` values; litellm maps model GROUPS, so
    those resolved to nothing. Second, the fix is not to correct the ids --
    `docs/0002` §5 says never silently spend, so `paid` is a group you ask for
    by name, not one you arrive at by failing.

    Failover comes from the shared `pool` model group instead: the router
    retries across its deployments and cools down whichever just failed.
    """
    env = {"OPENROUTER_API_KEY": "x", "ANTHROPIC_API_KEY": "y"}
    d = yaml.safe_load(build(env))
    assert not d["router_settings"].get("fallbacks")

    groups = {m["model_name"] for m in d["model_list"]}
    assert groups == {"pool", "paid"}
    paid = [m for m in d["model_list"] if m["model_name"] == "paid"]
    assert all("anthropic" in m["litellm_params"]["model"] for m in paid)


def test_a_fallback_naming_a_deployment_id_is_rejected():
    """The bug the generator shipped: ids where groups belong."""
    injected = '  fallbacks: [{"pool": ["openrouter-a1-m1"]}]\n  routing_strategy:'
    cfg = build(TWO).replace("  routing_strategy:", injected)
    with pytest.raises(AssertionError, match="not a model group"):
        _validate(cfg)


def test_free_deployments_all_share_one_group():
    """That shared group IS the failover mechanism."""
    d = yaml.safe_load(build(TWO))
    free = [m for m in d["model_list"] if m["model_name"] == "pool"]
    # TWO has no paid provider, so every row is free -- but some rows are now
    # source-group copies, which carry the same deployment under `-only`.
    rows = {m["model_info"]["id"].removesuffix("-only") for m in d["model_list"]}
    assert rows == {m["model_info"]["id"] for m in free}
    assert len({m["model_info"]["id"] for m in free}) == len(free)


def test_keys_are_referenced_never_inlined():
    """A generated config is a file people paste into repos."""
    text = build(ONE)
    assert "os.environ/OPENROUTER_API_KEY" in text
    assert "x" not in [m["litellm_params"]["api_key"]
                       for m in yaml.safe_load(text)["model_list"]]


def test_only_providers_with_a_key_are_included():
    """litellm resolves os.environ at load and refuses if it is missing."""
    d = yaml.safe_load(build(ONE))
    assert all("OPENROUTER" in m["litellm_params"]["api_key"]
               for m in d["model_list"])


def test_free_models_come_before_paid_ones():
    """`docs/0002` §5: degrade toward slower, never silently toward billed."""
    env = {"OPENROUTER_API_KEY": "x", "ANTHROPIC_API_KEY": "y"}
    entries = available(env)
    frees = [i for i, c in enumerate(entries) if c[3]]
    paid = [i for i, c in enumerate(entries) if not c[3]]
    assert not paid or max(frees) < min(paid)


def test_accounts_counts_credentials_not_deployments():
    """Three models on one key is ONE account, and one daily cap."""
    assert len(available(ONE)) > 1
    assert accounts(available(ONE)) == {"OPENROUTER_API_KEY"}
    assert len(accounts(available(TWO))) == 2


def test_no_keys_at_all_refuses_clearly():
    with pytest.raises(SystemExit, match="no provider keys"):
        build({})


# ── the validator must be able to fail ─────────────────────────────────
@pytest.mark.parametrize("text,expect", [
    ("model_list: [{model_name: a, litellm_params: {api_key: 'os.environ/K'}},"
     " {model_name: b, litellm_params: {api_key: 'os.environ/K'}}]",
     "unexpected model groups"),
    ("litellm_settings: {}", "no model_list"),
    ("model_list: [{model_name: pool, litellm_params: {api_key: sk-real}}]",
     "inlined"),
])
def test_the_validator_rejects_bad_configs(text, expect):
    with pytest.raises(AssertionError, match=expect):
        _validate(text)


def test_a_good_config_passes_the_validator():
    _validate(build(TWO))          # must not raise


def test_write_puts_both_files_down(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    cfg, hook = write(tmp_path)
    assert cfg.exists() and hook.exists()
    assert "proxy_handler_instance" in hook.read_text(encoding="utf-8")


# ── modify_params: true (`docs/0038` §5.1, item 5) ─────────────────────
def test_modify_params_is_enabled():
    """Without it, a stale/orphaned tool_call_id 400s on a cross-provider hop

    instead of being repaired: `sanitize_messages_for_tool_calling` returns
    the message list untouched unless this is set
    (`research/phase-10-3-model-selection.md` §2.1 V6).
    """
    d = yaml.safe_load(build(ONE))
    assert d["litellm_settings"]["modify_params"] is True


def test_drop_params_and_modify_params_coexist():
    """Two independent settings; one must not crowd the other out of a future

    edit to this block.
    """
    d = yaml.safe_load(build(ONE))
    assert d["litellm_settings"]["drop_params"] is True
    assert d["litellm_settings"]["modify_params"] is True


# ── the id format and its parser are one contract ──────────────────────
def test_every_generated_id_parses_back_to_its_triple():
    """`dash` reads `/model/info` and must recover (provider, account, model)
    from `model_info.id` alone (`research/phase-10-3` §6.1). One test ties
    the generator and the parser together so they cannot drift apart."""
    env = {"OPENROUTER_API_KEY": "x", "OPENROUTER_API_KEY_2": "y",
           "MISTRAL_API_KEY": "z"}
    for env_var, _model, short, _free in available(env):
        parsed = parse_deployment_id(short)
        assert parsed is not None, short
        provider, n, i = parsed
        assert short == f"{provider}-a{n}-m{i}"


def test_parse_deployment_id_rejects_what_it_does_not_recognise():
    """A foreign or malformed id must come back `None`, never a guess."""
    for bad in ("", "openrouter", "openrouter-a1", "openrouter-a1-mX",
                "openrouter_a1_m0", "OPENROUTER-a1-m0", "pool", "paid"):
        assert parse_deployment_id(bad) is None, bad


def test_modify_params_carries_a_rationale_comment():
    """`docs/0038`: 'a setting with no rationale is a setting nobody can

    review later.' Comments do not survive `yaml.safe_load`, so this checks
    the raw text rather than the parsed document.
    """
    text = build(ONE)
    assert "sanitize_messages_for_tool_calling" in text
    assert "synthesises a placeholder result" in text
