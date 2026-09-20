r"""Preflight and provider-error translation. `docs/0031`.

Both exist because of one real failure: a run burned fifteen tool calls,
produced nothing, and surfaced as a `RateLimitError` traceback ending in
*"please file a bug report at github.com/OpenHands"*. The provider was out of
free quota. Nothing in that chain said so.

The tests that matter here are the ones about **not lying**: an unrecognised
error must pass through untranslated, and a check that cannot know something
must say it cannot.
"""
from __future__ import annotations

import pytest

from agentctl.runtime.doctor import BAD, OK, WARN, check_all, report
from agentctl.runtime.runner import _explain_provider_error as explain


# ── translating provider refusals ──────────────────────────────────────
RATE_LIMIT = (
    'litellm.RateLimitError: OpenrouterException - {"error":{"message":'
    '"Rate limit exceeded: free-models-per-day. Add 10 credits to unlock",'
    '"code":429,"metadata":{"headers":{"X-RateLimit-Limit":"50",'
    '"X-RateLimit-Remaining":"0","X-RateLimit-Reset":"1789344000000"}}}}')


def test_a_rate_limit_says_it_is_not_an_agent_error():
    """The SDK's own message points at the OpenHands bug tracker. It is not."""
    out = explain(Exception(RATE_LIMIT))
    assert out and "not an agent error" in out


def test_it_extracts_the_remaining_count_and_the_reset_time():
    out = explain(Exception(RATE_LIMIT))
    assert "remaining    0" in out
    assert "resets" in out and "2026-09-14" in out


def test_it_says_switching_model_will_not_help():
    """The free cap is account-wide. Trying another `:free` model wastes time."""
    out = explain(Exception(RATE_LIMIT))
    assert "account-wide" in out and "does not help" in out


def test_it_offers_the_offline_route():
    assert "--replay" in explain(Exception(RATE_LIMIT))


@pytest.mark.parametrize("text,expect", [
    ("Error: insufficient credits on this account", "out of credit"),
    ("401 No auth credentials found", "rejected the API key"),
    ("OpenrouterException - Upstream error from Nvidia: "
     "Service temporarily overloaded", "overloaded"),
])
def test_other_refusals_are_recognised(text, expect):
    out = explain(Exception(text))
    assert out and expect in out


def test_an_unrecognised_error_is_NOT_translated():
    """The important one.

    Guessing at an unfamiliar error hides it. An unhandled traceback is worse
    to read and better to have than a confident wrong explanation -- the same
    reason `docs/0024` insists a fail-closed path must be distinguishable from
    a decision.
    """
    assert explain(Exception("TypeError: unhashable type: 'dict'")) is None
    assert explain(ValueError("something nobody has seen before")) is None


def test_the_api_key_is_never_echoed_back():
    leaky = 'Invalid api key: sk-or-v1-ACTUALSECRETVALUE123'
    out = explain(Exception(leaky)) or ""
    assert "ACTUALSECRETVALUE" not in out


# ── preflight ──────────────────────────────────────────────────────────
def test_doctor_runs_offline_and_reports_something():
    rows = check_all(probe_network=False)
    assert rows and all(r[0] in (OK, WARN, BAD) for r in rows)


def test_doctor_checks_the_things_that_have_actually_broken():
    """Every subject here maps to a real failure recorded in docs/."""
    subjects = {s for _, s, _ in check_all(probe_network=False)}
    for needed in ("mcp", "fastmcp client", "openhands sdk", "git", "python"):
        assert needed in subjects, f"doctor stopped checking {needed}"


def test_a_single_provider_is_flagged_as_no_failover(monkeypatch):
    """The project's own thesis: one account cannot fail over."""
    for env, _, _ in __import__("agentctl.runtime.doctor", fromlist=["PROVIDERS"]).PROVIDERS:
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    rows = check_all(probe_network=False)
    assert any(s == "failover" and st == WARN for st, s, _ in rows)


def test_no_provider_at_all_is_blocking(monkeypatch):
    from agentctl.runtime.doctor import PROVIDERS
    for env, _, _ in PROVIDERS:
        monkeypatch.delenv(env, raising=False)
    rows = check_all(probe_network=False)
    assert any(st == BAD and s == "providers" for st, s, _ in rows)


def test_two_providers_are_not_flagged(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("MISTRAL_API_KEY", "y")
    rows = check_all(probe_network=False)
    assert not any(s == "failover" for _, s, _ in rows)


def test_an_uncommitted_workspace_is_warned_about(tmp_path):
    """The agent edits real files. Losing them is the user's problem to avoid."""
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    rows = check_all(workspace=tmp_path, probe_network=False)
    assert any("commit first" in d for _, _, d in rows)


def test_a_non_repo_workspace_is_warned_about(tmp_path):
    rows = check_all(workspace=tmp_path, probe_network=False)
    assert any("not a git repo" in d for _, _, d in rows)


def test_report_returns_nonzero_only_for_blocking_problems(capsys):
    assert report([(OK, "a", "fine"), (WARN, "b", "hmm")]) == 0
    assert report([(OK, "a", "fine"), (BAD, "b", "broken")]) == 1
    assert "blocking" in capsys.readouterr().out


def test_the_quota_check_reports_what_it_actually_fetches(monkeypatch):
    """This check calls `/api/v1/auth/key`, which reports free-tier status
    but not the remaining count. It must say that plainly -- and must not
    claim the number is unknowable, which was checked and found false
    (`probe.py::openrouter_quota` reads it from `/api/v1/key`, live, on
    2026-09-21).
    """
    import agentctl.runtime.doctor as d
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setattr(d, "_openrouter",
                        lambda: (WARN, "openrouter quota",
                                 "FREE TIER: 50 model requests/day, "
                                 "account-wide. This check reports free-tier "
                                 "status only; the live remaining count is "
                                 "exposed separately by "
                                 "probe.py::openrouter_quota."))
    rows = d.check_all(probe_network=True)
    quota = [r for r in rows if r[1] == "openrouter quota"]
    assert quota and "exposed separately" in quota[0][2]
    assert "not exposed by any endpoint" not in quota[0][2]


def test_the_false_unknowable_quota_claim_is_gone():
    """`doctor` used to assert OpenRouter's remaining count is 'not exposed
    by any endpoint.' That was checked again on 2026-09-21 and found false --
    `/api/v1/key` exposes it. Neither the module docstring nor the real
    `_openrouter` check's own source may repeat the claim.
    """
    import inspect

    import agentctl.runtime.doctor as d

    text = (d.__doc__ or "") + inspect.getsource(d._openrouter)
    assert "not exposed by any endpoint" not in text
    assert "not exposed by any free endpoint" not in text
    assert "you find out at the 50th request" not in text


# ── Groq's turn-2 ceiling (item 3, `docs/0038` §4.1) ────────────────────
def _clear_all_providers(monkeypatch):
    from agentctl.runtime.doctor import PROVIDERS
    for env, _, _ in PROVIDERS:
        monkeypatch.delenv(env, raising=False)


def test_groq_headroom_is_silent_without_a_groq_key(monkeypatch):
    """No noise for a user who has never touched Groq."""
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    rows = check_all(probe_network=False)
    assert not any(s == "groq headroom" for _, s, _ in rows)


def test_groq_headroom_warns_when_groq_is_configured(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("GROQ_API_KEY", "y")
    rows = check_all(probe_network=False)
    hits = [r for r in rows if r[1] == "groq headroom"]
    assert hits and hits[0][0] == WARN
    assert "413" in hits[0][2]


def test_groq_headroom_needs_no_network(monkeypatch):
    """The arithmetic is offline -- it must appear whether or not
    `probe_network` is set, unlike `openrouter quota`, which does need it.
    """
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "y")
    off = [r for r in check_all(probe_network=False) if r[1] == "groq headroom"]
    on = [r for r in check_all(probe_network=True) if r[1] == "groq headroom"]
    assert off and on


def test_groq_headroom_counts_scale_with_configured_accounts(monkeypatch):
    from agentctl.control.providers import BY_NAME

    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "a")
    monkeypatch.setenv("GROQ_API_KEY_2", "b")
    rows = check_all(probe_network=False)
    hits = [r for r in rows if r[1] == "groq headroom"]
    assert hits
    n = 2 * len(BY_NAME["groq"].models)
    assert f"{n} of {n} configured deployment(s) are Groq" in hits[0][2]


def test_groq_headroom_says_so_when_groq_is_the_only_provider(monkeypatch):
    """The ruling: stay WARN, but the reader with ONLY Groq needs the
    sentence, not a different colour."""
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "y")
    rows = check_all(probe_network=False)
    hits = [r for r in rows if r[1] == "groq headroom"]
    assert hits and hits[0][0] == WARN
    assert "only provider you have configured" in hits[0][2]


def test_groq_headroom_does_not_clear_the_other_providers(monkeypatch):
    """A reader must not walk away thinking the rest of the pool is
    confirmed fine -- `providers.py` records no rate limits for anyone, so
    silence about Mistral/OpenRouter/Gemini is absence of evidence, not a
    clearance. Also must not read as 'the whole pool is broken.'
    """
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("MISTRAL_API_KEY", "y")
    monkeypatch.setenv("GROQ_API_KEY", "z")
    rows = check_all(probe_network=False)
    hits = [r for r in rows if r[1] == "groq headroom"]
    assert hits
    detail = hits[0][2]
    assert "not the same as a clean bill of health" in detail
    assert "only provider you have configured" not in detail


def test_groq_headroom_cites_its_sources_and_dates(monkeypatch):
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "y")
    rows = check_all(probe_network=False)
    detail = next(d for _, s, d in rows if s == "groq headroom")
    assert "console.groq.com" in detail and "2026-09-20" in detail
    assert "INFERRED" in detail
    assert "Unconfirmed by a live call" in detail


def test_groq_headroom_is_never_blocking(monkeypatch):
    """Turn 1 works; the failure is inferred, not observed from this repo.
    WARN, never BAD -- BAD means 'this will not work.'"""
    _clear_all_providers(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "y")
    rows = check_all(probe_network=False)
    assert not any(s == "groq headroom" and st == BAD for st, s, _ in rows)


# ── usability flaws found by actually using it (docs/0031 §9) ──────────
def test_the_key_error_names_the_right_variable():
    """Telling someone to set OPENROUTER_API_KEY for an anthropic/ model is
    advice that cannot work."""
    from agentctl.runtime.runner import _env_var_for

    assert _env_var_for("anthropic/claude-sonnet-5") == "ANTHROPIC_API_KEY"
    assert _env_var_for("gemini/gemini-2.5-flash") == "GEMINI_API_KEY"
    assert _env_var_for("openrouter/x/y:free") == "OPENROUTER_API_KEY"
    assert "provider" in _env_var_for("something/unknown")


def test_an_unknown_model_is_not_reported_as_an_agent_bug():
    """A 400 from the provider surfaced as an OpenHands traceback."""
    out = explain(Exception(
        "MaskedHTTPStatusError: Client error '400 Bad Request' for url "
        "'https://openrouter.ai/api/v1/chat/completions'"))
    assert out and "unknown or unavailable model id" in out


def test_ledger_can_be_given_after_the_subcommand(tmp_path):
    """`agentctl status --ledger X` used to be an unrecognised-argument error,
    which is exactly what people type."""
    from agentctl.cli import build_parser

    p = build_parser()
    after = p.parse_args(["status", "--ledger", str(tmp_path / "a.db")])
    before = p.parse_args(["--ledger", str(tmp_path / "a.db"), "status"])
    assert after.ledger == before.ledger


def test_the_global_default_is_not_clobbered_by_the_subparser():
    """SUPPRESS is what makes the duplicate option safe.

    Without it, the subparser's own default would overwrite a --ledger given
    before the subcommand -- silently, which is the worst kind.
    """
    from agentctl.cli import build_parser

    args = build_parser().parse_args(["--ledger", "chosen.db", "status"])
    assert str(args.ledger) == "chosen.db"
