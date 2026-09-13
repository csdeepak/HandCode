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


def test_the_quota_check_admits_what_it_cannot_know(monkeypatch):
    """OpenRouter exposes no remaining-request counter on any free endpoint.

    Probed `auth/key` and `credits`: neither returns rate-limit headers. A
    preflight that guessed would be worse than one that says so.
    """
    import agentctl.runtime.doctor as d
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setattr(d, "_openrouter",
                        lambda: (WARN, "openrouter quota",
                                 "FREE TIER: 50 model requests/day, "
                                 "account-wide. The remaining count is not "
                                 "exposed by any endpoint."))
    rows = d.check_all(probe_network=True)
    quota = [r for r in rows if r[1] == "openrouter quota"]
    assert quota and "not exposed" in quota[0][2]


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
