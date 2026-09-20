r"""The dashboard reads the live pool from a running proxy, and shows the one
honest quota number it has. `docs/0038` §5.2, §5.3; `research/phase-10-3-
model-selection.md` §6.

No live proxy, no live network: every HTTP call is monkeypatched onto
`urllib.request.urlopen`, mirroring `tests/test_probe.py`'s pattern. Fixture
payloads are shaped like the ones actually measured against a running proxy
(`research/phase-10-3-model-selection.md` §2.2 V10, V12) and confirmed again
live in this session (`docs/0038` §9.2) -- not invented shapes.

Two properties matter most here, because the standing rule (module docstring,
`docs/0021` §5) is easiest to violate by accident in exactly these ways:

* **No deployment count is ever hardcoded.** The pool changed from 42 to 48
  deployments mid-project without any code changing; a fixture or an
  assertion that bakes in a specific number would be the same mistake this
  project keeps finding elsewhere.
* **Capacity has exactly one verdict.** `_capacity()` must return `UNKNOWN`
  for every input it can be given -- there must be no path to a green light.
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from agentctl.control import dash, probe

SECRET = "sk-or-v1-NEVERSHOWTHISEITHER0000"


# ── fake transport, same shape as tests/test_probe.py ──────────────────
class _HTTPOK:
    def __init__(self, body: bytes):
        self._body = body

    def read(self, n=None):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _HTTPError(urllib.error.HTTPError):
    def __init__(self, code, body=""):
        self._body = body.encode()
        super().__init__("http://x", code, "err", {}, None)

    def read(self, n=None):
        return self._body


def _deployment(short_id: str, free: bool = True) -> dict:
    """One row shaped like the measured `/model/info` payload (V10),
    abridged to the fields this code actually reads."""
    return {"model_name": "pool",
            "litellm_params": {"model": "openai/fake"},
            "model_info": {"id": short_id, "free": free}}


def _router(*, liveliness_ok: bool = True, model_info=None,
            liveliness_raises: Exception | None = None,
            model_info_raises: Exception | None = None):
    """Route fake responses by URL, exactly like a real proxy would by path.

    Also records every request made, so a test can assert what was (and was
    not) sent -- in particular, that no Authorization header ever reaches
    the proxy calls (V11: the generated config sets no `master_key`).
    """
    calls: list = []

    def _urlopen(req, timeout=None):
        calls.append(req)
        url = req.full_url
        if "liveliness" in url:
            if liveliness_raises:
                raise liveliness_raises
            if not liveliness_ok:
                raise urllib.error.URLError("connection refused")
            return _HTTPOK(b"I'm alive!")           # measured V12: plain text
        if "model/info" in url:
            if model_info_raises:
                raise model_info_raises
            return _HTTPOK(json.dumps({"data": model_info or []}).encode())
        raise AssertionError(f"unexpected URL: {url}")

    return _urlopen, calls


# ── item 6: the pool comes from the proxy ───────────────────────────────
def test_no_proxy_configured_behaves_exactly_as_before(monkeypatch):
    monkeypatch.delenv("AGENTCTL_PROXY_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    d = dash.collect()
    assert d["proxy"] == {"configured": False}
    assert d["capacity"]["verdict"] == "UNKNOWN"
    assert all(p["name"] != "?" for p in d["providers"])   # env-derived rows


def test_liveliness_is_plain_text_not_json_and_that_is_handled(monkeypatch):
    """The endpoint returns the literal string `"I'm alive!"` (measured,
    V12) -- a naive `json.loads()` on it must not be mistaken for failure."""
    fake, calls = _router(liveliness_ok=True,
                          model_info=[_deployment("openrouter-a1-m0")])
    monkeypatch.setattr(dash.urllib.request, "urlopen", fake)
    pool = dash._proxy_pool("http://127.0.0.1:4000")
    assert pool["reachable"] is True
    assert pool["accounts"] == [{"provider": "openrouter", "label": "openrouter-a1",
                                 "n": 1, "deployments": 1, "free": True}]


def test_unreachable_proxy_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    fake, calls = _router(liveliness_ok=False)
    monkeypatch.setattr(dash.urllib.request, "urlopen", fake)
    d = dash.collect(proxy_url="http://127.0.0.1:4000")
    assert d["proxy"]["configured"] is True
    assert d["proxy"]["reachable"] is False
    assert "why" in d["proxy"]
    # Same rows as if no proxy were configured at all.
    assert any(p["name"] == "openrouter" and p["configured"] for p in d["providers"])


def test_the_deployment_count_is_never_hardcoded(monkeypatch):
    """The pool grew from 42 to 48 deployments mid-project with no code
    change. Prove the reader does not assume a size by using neither."""
    rows = ([_deployment(f"openrouter-a1-m{i}") for i in range(5)]
           + [_deployment(f"gemini-a{n}-m0") for n in range(1, 4)])
    fake, calls = _router(model_info=rows)
    monkeypatch.setattr(dash.urllib.request, "urlopen", fake)
    pool = dash._proxy_pool("http://x")
    assert pool["deployments"] == len(rows) == 8
    by_label = {a["label"]: a for a in pool["accounts"]}
    assert by_label["openrouter-a1"]["deployments"] == 5
    assert {"gemini-a1", "gemini-a2", "gemini-a3"} <= by_label.keys()


def test_an_id_in_a_foreign_format_is_counted_not_guessed(monkeypatch):
    rows = [_deployment("openrouter-a1-m0"), {"model_info": {"id": "some-other-config"}},
            {"model_info": {}}, {}]
    fake, calls = _router(model_info=rows)
    monkeypatch.setattr(dash.urllib.request, "urlopen", fake)
    pool = dash._proxy_pool("http://x")
    assert pool["deployments"] == 4
    assert pool["unmatched"] == 3
    assert len(pool["accounts"]) == 1


def test_model_info_failure_after_a_live_liveliness_is_reported_not_crashed(monkeypatch):
    fake, calls = _router(liveliness_ok=True,
                          model_info_raises=urllib.error.URLError("reset"))
    monkeypatch.setattr(dash.urllib.request, "urlopen", fake)
    pool = dash._proxy_pool("http://x")
    assert pool["reachable"] is True and "accounts" not in pool
    assert "model/info" in pool["why"]


def test_model_info_with_an_unexpected_shape_does_not_crash(monkeypatch):
    def _urlopen(req, timeout=None):
        if "liveliness" in req.full_url:
            return _HTTPOK(b"I'm alive!")
        return _HTTPOK(b'{"not_data": []}')          # no "data" key at all
    monkeypatch.setattr(dash.urllib.request, "urlopen", _urlopen)
    pool = dash._proxy_pool("http://x")
    assert pool["reachable"] is True and "accounts" not in pool


def test_no_credential_is_ever_sent_to_the_proxy(monkeypatch):
    """V11: the generated config sets no `master_key`, so neither proxy call
    needs or sends an Authorization header."""
    fake, calls = _router(model_info=[_deployment("openrouter-a1-m0")])
    monkeypatch.setattr(dash.urllib.request, "urlopen", fake)
    dash._proxy_pool("http://x")
    assert len(calls) == 2
    for req in calls:
        assert not any(k.lower() == "authorization" for k in req.headers)


def test_providers_panel_is_replaced_when_the_proxy_answers(monkeypatch):
    fake, calls = _router(model_info=[_deployment("openrouter-a1-m0"),
                                      _deployment("openrouter-a1-m1")])
    monkeypatch.setattr(dash.urllib.request, "urlopen", fake)
    d = dash.collect(proxy_url="http://x")
    names = {p["name"] for p in d["providers"]}
    assert names == {"openrouter-a1"}
    row = d["providers"][0]
    assert "loaded by the proxy" in row["detail"]
    assert "/model/info" in row["detail"]


# ── panel 1: capacity is always UNKNOWN ─────────────────────────────────
@pytest.mark.parametrize("pool", [
    {"configured": False},
    {"configured": True, "reachable": False, "why": "down"},
    {"configured": True, "reachable": True, "why": "bad shape"},
    {"configured": True, "reachable": True, "deployments": 48,
     "accounts": [{"provider": "openrouter", "label": "openrouter-a1", "n": 1,
                  "deployments": 3, "free": True}]},
    {"configured": True, "reachable": True, "deployments": 0, "accounts": []},
])
def test_capacity_is_always_unknown(pool):
    """There must be no input to `_capacity` that returns anything else --
    that is the acceptance test for 'do not build a green light.'"""
    cap = dash._capacity(pool)
    assert cap["verdict"] == "UNKNOWN"
    assert cap["detail"]


def test_capacity_never_reuses_the_failover_readiness_word_as_a_claim():
    """`_failover` legitimately says READY (configured shape). `_capacity`
    must never echo that word as its own verdict."""
    for pool in ({"configured": False},
                {"configured": True, "reachable": True, "deployments": 5,
                 "accounts": [{"provider": "openrouter", "label": "openrouter-a1",
                              "n": 1, "deployments": 5, "free": True}]}):
        assert dash._capacity(pool)["verdict"] != "READY"


def test_the_failover_banner_gets_a_clarifying_note_only_when_a_proxy_exists(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")            # -> FAILOVER: READY
    without = dash.render(dash.collect())
    assert "not live capacity" not in without

    fake, _ = _router(model_info=[_deployment("openrouter-a1-m0")])
    monkeypatch.setattr(dash.urllib.request, "urlopen", fake)
    withp = dash.render(dash.collect(proxy_url="http://x"))
    assert "not live capacity" in withp
    assert "CAN I WORK RIGHT NOW?   UNKNOWN" in withp


def test_html_capacity_banner_never_takes_the_green_failover_tone(monkeypatch):
    """The capacity tone is a fixed constant, never a dict keyed on verdict
    the way FAILOVER's is -- so there is no entry to someday add "READY" to."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    html_out = dash.to_html(dash.collect())               # FAILOVER: READY (green)
    assert "border-left:4px solid #1a7f37" in html_out    # the base .banner rule is green
    # The capacity banner overrides that with a fixed neutral colour of its
    # own -- never green, and never derived from FAILOVER's verdict.
    assert "banner.capacity {" in html_out
    assert "border-left-color:#57606a" in html_out
    assert "border-left-color:#1a7f37" not in html_out


# ── item 7: OpenRouter quota, manual refresh only ───────────────────────
def test_quota_makes_no_network_call_without_refresh(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    def _explode(*a, **k):
        raise AssertionError("quota must not be polled without --refresh-quota")
    monkeypatch.setattr(probe.urllib.request, "urlopen", _explode)
    rows = dash._quota(refresh=False)
    assert rows and rows[0]["value"] is None
    assert "not checked this session" in rows[0]["reason"]


def test_quota_refresh_reads_the_measured_shape(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    payload = json.dumps({"data": {"is_free_tier": True,
                          "free_model_daily_requests":
                              {"used": 0, "limit": 50, "remaining": 50}}}).encode()
    monkeypatch.setattr(probe.urllib.request, "urlopen",
                        lambda *a, **k: _HTTPOK(payload))
    rows = dash._quota(refresh=True)
    assert rows[0]["value"] == "50 of 50 free requests remaining"
    assert "api/v1/key" in rows[0]["reason"]


def test_only_openrouter_can_ever_show_a_number(monkeypatch):
    """Structural, not a docstring promise: no provider other than
    OpenRouter has a code path in `_quota` that produces a `value`."""
    for env in ("GEMINI_API_KEY", "MISTRAL_API_KEY", "CEREBRAS_API_KEY",
               "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.setenv(env, "x")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for refresh in (False, True):
        rows = dash._quota(refresh=refresh)
        assert rows and all(r["value"] is None for r in rows)
        assert all(r["reason"] for r in rows)              # never a bare blank


def test_quota_reason_is_specific_per_provider(monkeypatch):
    for env in ("GEMINI_API_KEY", "MISTRAL_API_KEY", "CEREBRAS_API_KEY",
               "GROQ_API_KEY"):
        monkeypatch.setenv(env, "x")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    rows = {r["label"]: r["reason"] for r in dash._quota(refresh=False)}
    assert "no quota endpoint" in rows["gemini"] or "publishes no quota" in rows["gemini"]
    assert "Admin key" in rows["mistral"]
    assert "no documented quota signal" in rows["cerebras"]
    assert "response header" in rows["groq"]


def test_quota_key_never_appears_anywhere_rendered(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    payload = json.dumps({"data": {"free_model_daily_requests":
                          {"used": 1, "limit": 50, "remaining": 49}}}).encode()
    monkeypatch.setattr(probe.urllib.request, "urlopen",
                        lambda *a, **k: _HTTPOK(payload))
    d = dash.collect(refresh_quota=True)
    assert SECRET not in dash.render(d)
    assert SECRET not in dash.to_html(d)
    assert SECRET not in str(d)


def test_a_failed_quota_check_does_not_echo_the_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    monkeypatch.setattr(probe.urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(
                            _HTTPError(403, f"bad key {SECRET}")))
    rows = dash._quota(refresh=True)
    assert SECRET not in rows[0]["reason"]


def test_all_generated_terminal_output_is_windows_console_safe(monkeypatch):
    """`docs/0034` §8: this exact project has hit a Windows console encoding
    crash five times already. The classic non-UTF8 console codepage (cp437)
    must be able to encode everything `render()` produces."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    fake, _ = _router(model_info=[_deployment("openrouter-a1-m0")])
    monkeypatch.setattr(dash.urllib.request, "urlopen", fake)
    text = dash.render(dash.collect(proxy_url="http://x", refresh_quota=False))
    text.encode("cp437")                                   # must not raise
