r"""One capped key must not speak for five working ones.

`agentctl proxy --verify` builds the pool from providers that can actually
serve. It asked one account per provider, on the stated reasoning that *"the
tier is an account-level property"* — which is the argument against doing that.
A daily cap is account-level too, so on 2026-09-21 a single capped OpenRouter
key removed all eighteen of that provider's deployments from a 48-deployment
pool, leaving 30. The other five accounts were fine.

The second bug compounded it. OpenRouter's daily-cap error reads:

    Rate limit exceeded: free-models-per-day. Add 10 credits to unlock
    1000 free model requests per day

It contains the word `credits`, and the payment check ran before the rate-limit
check — so a cap that clears at midnight was classified as a billing failure,
which is the one verdict that drops a provider from the pool outright. A fifth
way a check can lie (`docs/0034`).
"""
import pytest

from agentctl.control import probe
from agentctl.control.probe import LIMITED, LIVE, NO_CREDIT, UNREACHABLE

pytest.importorskip("litellm")

ENV = {"OPENROUTER_API_KEY": "k1", "OPENROUTER_API_KEY_2": "k2",
       "OPENROUTER_API_KEY_3": "k3"}


@pytest.fixture
def three_accounts(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    yield


def fake_completion(calls, outcomes):
    """Raise or return per call, recording the key used each time."""
    def _c(*_a, **kw):
        key = kw.get("api_key")
        calls.append(key)
        result = outcomes.get(key, "ok")
        if isinstance(result, Exception):
            raise result
        return {"ok": True}
    return _c


# ══ one account must not condemn a provider ══════════════════════════
def test_a_capped_first_account_does_not_drop_the_provider(three_accounts,
                                                           monkeypatch):
    import litellm
    calls: list[str] = []
    capped = Exception("Rate limit exceeded: free-models-per-day. Add 10 "
                       "credits to unlock 1000 free model requests per day")
    monkeypatch.setattr(litellm, "completion",
                        fake_completion(calls, {"k1": capped}))

    r = probe.check_inference("openrouter")
    assert r.status == LIVE, f"a working account #2 was ignored: {r.detail}"
    assert calls == ["k1", "k2"], "should stop at the first success"


def test_a_healthy_provider_still_costs_exactly_one_call(three_accounts,
                                                         monkeypatch):
    """The cost concern behind the original single-call design is preserved."""
    import litellm
    calls: list[str] = []
    monkeypatch.setattr(litellm, "completion", fake_completion(calls, {}))

    assert probe.check_inference("openrouter").status == LIVE
    assert calls == ["k1"]


def test_every_account_failing_reports_a_failure(three_accounts, monkeypatch):
    import litellm
    calls: list[str] = []
    broke = Exception("Payment required to access this resource")
    monkeypatch.setattr(litellm, "completion", fake_completion(
        calls, {k: broke for k in ("k1", "k2", "k3")}))

    r = probe.check_inference("openrouter")
    assert r.status == NO_CREDIT
    assert len(calls) == 3, "must try them all before condemning the provider"


# ══ the wording trap ═════════════════════════════════════════════════
def test_a_daily_cap_is_rate_limited_not_unpaid(three_accounts, monkeypatch):
    """The exact string OpenRouter returns, which mentions credits."""
    import litellm
    capped = Exception("Rate limit exceeded: free-models-per-day. Add 10 "
                       "credits to unlock 1000 free model requests per day")
    monkeypatch.setattr(litellm, "completion", fake_completion(
        [], {k: capped for k in ("k1", "k2", "k3")}))

    r = probe.check_inference("openrouter")
    assert r.status == LIMITED, (
        "a cap that clears at midnight was read as a billing failure, which "
        "is the one verdict that removes a provider from the pool")


def test_a_real_payment_failure_is_still_no_credit(three_accounts, monkeypatch):
    """The fix must not turn every failure into `rate limited`."""
    import litellm
    monkeypatch.setattr(litellm, "completion", fake_completion(
        [], {k: Exception("Payment required to access this resource")
             for k in ("k1", "k2", "k3")}))
    assert probe.check_inference("openrouter").status == NO_CREDIT


# ══ a model leaving the catalogue is not a dead key (docs/0044 N6) ═══
GONE = Exception("litellm.NotFoundError: 404 No endpoints found for this model")


def fake_by_model(calls, dead_models=(), capped_keys=()):
    def _c(*_a, **kw):
        calls.append((kw.get("api_key"), kw.get("model")))
        if kw.get("api_key") in capped_keys:
            raise Exception("Rate limit exceeded: free-models-per-day")
        if any(kw.get("model", "").endswith(m) for m in dead_models):
            raise GONE
        return {"ok": True}
    return _c


def test_a_gone_first_model_falls_through_to_the_next(three_accounts,
                                                      monkeypatch):
    """Phase 0: the first registry model was gone and a working key read
    "0 provider(s) can serve a request right now"."""
    import litellm

    from agentctl.control.providers import BY_NAME
    first, second = BY_NAME["openrouter"].models[:2]
    calls: list = []
    monkeypatch.setattr(litellm, "completion",
                        fake_by_model(calls, dead_models=(first,)))

    r = probe.check_inference("openrouter")
    assert r.status == LIVE, r.detail
    assert r.gone == (first,)
    assert first in r.detail and second in r.detail
    assert calls == [("k1", f"openrouter/{first}"),
                     ("k1", f"openrouter/{second}")]


def test_every_model_gone_says_the_key_may_be_fine(three_accounts, monkeypatch):
    import litellm

    from agentctl.control.providers import BY_NAME
    models = BY_NAME["openrouter"].models
    calls: list = []
    monkeypatch.setattr(litellm, "completion",
                        fake_by_model(calls, dead_models=models))

    r = probe.check_inference("openrouter")
    assert r.status == UNREACHABLE
    assert "key may be fine" in r.detail and set(r.gone) == set(models)
    assert len(calls) == len(models), "a gone model is gone for every account"


def test_a_cap_does_not_spend_a_request_per_model(three_accounts, monkeypatch):
    """A daily cap is account-wide across every `:free` model, so trying the
    next model on a capped key would only spend a request to learn nothing."""
    import litellm
    calls: list = []
    monkeypatch.setattr(litellm, "completion",
                        fake_by_model(calls, capped_keys=("k1",)))

    assert probe.check_inference("openrouter").status == LIVE
    assert [k for k, _ in calls] == ["k1", "k2"]


def test_pool_verification_finds_a_dead_model_after_a_live_one(three_accounts,
                                                              monkeypatch):
    """`docs/0047`: the dead id was LAST, verification stopped at the first
    model that answered, and its 404 ended a live pooled run."""
    import litellm

    from agentctl.control.providers import BY_NAME
    models = BY_NAME["openrouter"].models
    calls: list = []
    monkeypatch.setattr(litellm, "completion",
                        fake_by_model(calls, dead_models=(models[-1],)))

    r = probe.check_inference("openrouter", all_models=True)
    assert r.status == LIVE and r.gone == (models[-1],)
    assert len(calls) == len(models), "one completion per model id, no more"

    calls.clear()
    assert probe.check_inference("openrouter").gone == ()
    assert len(calls) == 1, "keys --check still stops at the first success"


def test_a_busy_model_is_not_a_dead_one(three_accounts, monkeypatch):
    import litellm

    from agentctl.control.providers import BY_NAME
    second = BY_NAME["openrouter"].models[1]

    def c(*_a, **kw):
        if kw["model"].endswith(second):
            raise Exception("Rate limit exceeded: try again in 20s")
        return {"ok": True}

    monkeypatch.setattr(litellm, "completion", c)
    assert probe.check_inference("openrouter", all_models=True).gone == ()


def test_groq_deployments_drop_the_param_groq_rejects():
    """`docs/0047`: Groq 400'd on `prompt_cache_key`, which litellm forwards
    because its Groq config inherits OpenAI's parameter list, and the 400
    ended a pooled run. Only Groq's deployments drop it; the YAML must parse."""
    import yaml

    from agentctl.control.proxy import build

    cfg = yaml.safe_load(build({"GROQ_API_KEY": "g", "OPENROUTER_API_KEY": "o"}))
    for d in cfg["model_list"]:
        dropped = d["litellm_params"].get("additional_drop_params")
        if d["litellm_params"]["model"].startswith("groq/"):
            assert dropped == ["prompt_cache_key"], d
        else:
            assert dropped is None, d


def test_proxy_leaves_out_a_model_verification_found_gone():
    from agentctl.control.proxy import build
    from agentctl.control.providers import BY_NAME

    p = BY_NAME["openrouter"]
    dead = f"{p.prefix}{p.models[0]}"
    env = {"OPENROUTER_API_KEY": "k1"}
    assert dead in build(env)
    assert dead not in build(env, drop_models={dead})


# ══ which verdict survives ═══════════════════════════════════════════
def test_limited_beats_no_credit_across_accounts(three_accounts, monkeypatch):
    """One capped key and one unpaid key means the provider works tomorrow."""
    import litellm
    monkeypatch.setattr(litellm, "completion", fake_completion([], {
        "k1": Exception("Payment required"),
        "k2": Exception("rate limit exceeded"),
        "k3": Exception("Payment required"),
    }))
    r = probe.check_inference("openrouter")
    assert r.status == LIMITED, \
        "reporting the bleaker verdict drops a provider that returns tomorrow"


def test_a_provider_stays_in_the_pool_when_rate_limited():
    """LIMITED is admitted; NO_CREDIT is not. That is why the order matters."""
    from agentctl.control.proxy import verified_providers  # noqa: F401
    assert LIMITED != NO_CREDIT
    assert UNREACHABLE not in (LIMITED, NO_CREDIT)
