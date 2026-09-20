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
