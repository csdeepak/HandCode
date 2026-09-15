r"""Key connectivity checks. `docs/0034`.

Three properties, each written because it was violated first:

* a **CDN** 403 must not be reported as a bad key
* a **paid** provider must not be called without being asked
* a key must never appear in output, including in an error path
"""
from __future__ import annotations

import urllib.error

import pytest

from agentctl.control import probe
from agentctl.control.providers import Account, BY_NAME

SECRET = "sk-or-v1-NEVERSHOWTHIS0000000000"


def _acct(name="groq"):
    p = BY_NAME[name]
    return Account(p, p.key, p.name)


class _HTTPError(urllib.error.HTTPError):
    def __init__(self, code, body):
        self._body = body.encode()
        super().__init__("http://x", code, "err", {}, None)

    def read(self, n=None):
        return self._body


# ── a CDN block is not a bad credential ────────────────────────────────
def test_cloudflare_403_is_not_reported_as_a_rejected_key(monkeypatch):
    """The real incident: twelve valid keys reported broken.

    Groq and Cerebras sit behind Cloudflare, which refuses Python's default
    User-Agent with `error code: 1010`. That is a 403 the API never saw.
    """
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    monkeypatch.setattr(probe.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(
                            _HTTPError(403, "error code: 1010")))
    r = probe.check(_acct())
    assert r.status == probe.UNREACHABLE
    assert "CDN" in r.detail and "never checked" in r.detail
    assert r.status != probe.BAD_KEY


def test_a_real_401_is_a_rejected_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    monkeypatch.setattr(probe.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(
                            _HTTPError(401, '{"error":"invalid api key"}')))
    assert probe.check(_acct()).status == probe.BAD_KEY


def test_a_429_means_the_key_works(monkeypatch):
    """Rate limited is a WORKING credential with no allowance left.
    Reporting it as broken sends someone to rotate a key that is fine."""
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    monkeypatch.setattr(probe.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(
                            _HTTPError(429, "slow down")))
    r = probe.check(_acct())
    assert r.status == probe.LIMITED and r.ok is True


# ── never echo the credential ──────────────────────────────────────────
def test_an_error_body_quoting_the_key_is_redacted(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    monkeypatch.setattr(probe.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(
                            _HTTPError(403, f"bad key {SECRET} rejected")))
    r = probe.check(_acct())
    assert SECRET not in r.detail and "<REDACTED>" in r.detail


def test_an_empty_key_is_not_a_network_call(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    def _explode(*a, **k):
        raise AssertionError("should not have made a request")
    monkeypatch.setattr(probe.urllib.request, "urlopen", _explode)
    assert probe.check(_acct()).status == probe.BAD_KEY


# ── the key goes in a header, never a URL ──────────────────────────────
def test_gemini_sends_the_key_as_a_header_not_a_query_string():
    """`?key=` puts a live credential into logs, history and error text."""
    url, headers = probe.ENDPOINTS["gemini"]
    assert "key=" not in url
    assert headers("K")["x-goog-api-key"] == "K"


def test_every_endpoint_is_https_and_metadata_only():
    for name, (url, _) in probe.ENDPOINTS.items():
        assert url.startswith("https://"), name
        assert "chat/completions" not in url, name     # must not bill anyone


# ── never silently spend ───────────────────────────────────────────────
def test_a_paid_provider_is_not_called_unless_asked(monkeypatch):
    """`docs/0002` §5. The first version of this billed Anthropic to answer a
    diagnostic question nobody had asked it."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    called = []
    monkeypatch.setattr(probe, "check_inference", probe.check_inference)
    import litellm
    monkeypatch.setattr(litellm, "completion",
                        lambda *a, **k: called.append(1))
    r = probe.check_inference("anthropic")
    assert r is not None and r.status == probe.SKIPPED_PAID
    assert not called, "a paid provider was called without --check-paid"


def test_a_free_provider_is_checked(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    import litellm

    class _R:
        choices = [type("c", (), {"message": type("m", (), {"content": "ok"})()})()]
    monkeypatch.setattr(litellm, "completion", lambda *a, **k: _R())
    r = probe.check_inference("groq")
    assert r is not None and r.status == probe.LIVE


def test_payment_required_is_its_own_verdict(monkeypatch):
    """Authenticating and being allowed to infer are different facts."""
    monkeypatch.setenv("CEREBRAS_API_KEY", SECRET)
    import litellm
    monkeypatch.setattr(litellm, "completion", lambda *a, **k: (_ for _ in ()).throw(
        Exception("CerebrasException - Payment required to access this resource")))
    r = probe.check_inference("cerebras")
    assert r is not None and r.status == probe.NO_CREDIT
    assert r.ok is False


def test_the_inference_check_never_echoes_the_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    import litellm
    monkeypatch.setattr(litellm, "completion", lambda *a, **k: (_ for _ in ()).throw(
        Exception(f"rejected key {SECRET}")))
    r = probe.check_inference("groq")
    assert r is not None and SECRET not in r.detail


def test_summarise_counts_usable_not_merely_present():
    a = _acct()
    rs = [probe.Result(a, probe.LIVE), probe.Result(a, probe.LIMITED),
          probe.Result(a, probe.BAD_KEY)]
    s = probe.summarise(rs)
    assert s["total"] == 3 and s["working"] == 2
