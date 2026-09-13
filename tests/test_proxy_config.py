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

from agentctl.control.proxy import accounts, available, build, write, _validate


ONE = {"OPENROUTER_API_KEY": "x"}
TWO = {"OPENROUTER_API_KEY": "x", "MISTRAL_API_KEY": "y"}


def test_the_output_is_valid_yaml():
    assert yaml.safe_load(build(ONE))


def test_every_deployment_shares_one_model_name():
    """That is what makes them a pool rather than separate models."""
    d = yaml.safe_load(build(TWO))
    assert len({m["model_name"] for m in d["model_list"]}) == 1


def test_fallbacks_parse_as_a_list_of_mappings():
    """The exact bug: a missing comma made this `["a" "b"]`."""
    d = yaml.safe_load(build(TWO))
    fb = d["router_settings"]["fallbacks"]
    assert isinstance(fb, list) and isinstance(fb[0], dict)
    assert all(isinstance(x, str) for x in list(fb[0].values())[0])


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
     "one model_name"),
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
