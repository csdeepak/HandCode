r"""One screen: providers, failover, effects, spend, policy.

    agentctl dash                              the terminal view
    agentctl dash --html out.html              a page you can open or hand to someone
    agentctl dash --refresh-quota              also spend one metadata call per
                                                OpenRouter account on its quota

Everything here is **derived**, never asserted. Each panel reads a real source
-- the environment, a running proxy, the effect ledger, the cost ledger, the
compiled policy -- and a panel with nothing behind it says so rather than
showing a confident zero. `docs/0021` §5 is the reason: a cost of `$0.00` that
actually means "no data" is worse than a blank, because it reads as good news.

## The pool panel and the capacity panel are different claims

Set `AGENTCTL_PROXY_URL` and the PROVIDERS panel reports what a running proxy
actually **loaded** (`GET /model/info`) instead of what the environment
implies -- a stale or hand-edited config becomes visible instead of silently
assumed correct (`docs/0038` §5.2). That is a fact about *configuration*.

**It is never read as a fact about capacity right now.** Whether the pool can
actually serve a request depends on router cooldown state, and that state has
no HTTP surface at all -- the one endpoint that would show it (`GET /health`)
answers by spending one real completion per deployment, i.e. it spends the
very quota it would be reporting on
(`research/phase-10-3-model-selection.md` §6.4). So "CAN I WORK RIGHT NOW?"
always answers **UNKNOWN**, with the reasons composed from whatever is
actually known. A green light built from anything short of that would be a
guess dressed as a fact -- do not build one.

Key values are never displayed. The provider panel shows `set`, never the key.
OpenRouter's quota is the one honest quota number this pool has
(`docs/0038` §5.3); it is fetched only on `--refresh-quota`, never polled.
"""
from __future__ import annotations

import html
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .providers import BY_NAME, PROVIDERS, missing

# `/health/liveliness` must answer before `/model/info` is worth asking for;
# it is cheap and instant when the proxy is actually up, so it stays short.
_PROXY_LIVENESS_TIMEOUT = 2
_PROXY_INFO_TIMEOUT = 5


def collect(ledger: str | Path | None = None,
            cost_ledger: str | Path | None = None,
            proxy_url: str | None = None,
            refresh_quota: bool = False) -> dict[str, Any]:
    """Everything the dashboard shows. Pure gathering, no formatting.

    `proxy_url` defaults to `AGENTCTL_PROXY_URL`. Unset, the pool panel is
    exactly what it always was: derived from the environment. `refresh_quota`
    must be passed explicitly -- nothing here polls OpenRouter on its own.
    """
    if proxy_url is None:
        proxy_url = os.environ.get("AGENTCTL_PROXY_URL") or None
    pool = _proxy_pool(proxy_url) if proxy_url else {"configured": False}
    return {
        "generated": time.time(),
        "proxy": pool,
        "providers": _providers(pool),
        "failover": _failover(),
        "capacity": _capacity(pool),
        "quota": _quota(refresh_quota),
        "effects": _effects(ledger),
        "cost": _cost(cost_ledger),
        "policy": _policy(),
    }


# ── panels ─────────────────────────────────────────────────────────────
def _proxy_pool(url: str) -> dict:
    """What a running proxy actually loaded. `docs/0038` §5.2;
    `research/phase-10-3-model-selection.md` §2.2 (VERIFIED V9-V18), §6.1.

    Two calls, in order -- the second is only worth making once the first
    says something is listening:

    * `GET /health/liveliness` -- the literal text `"I'm alive!"`, **not
      JSON** (measured, V12). A reachability check, nothing more; it is not
      parsed as JSON on purpose.
    * `GET /model/info` -- one row per DEPLOYMENT (not per model group --
      `/v1/models` collapses everything to `pool`/`paid` and is useless
      here, V9). Unauthenticated, because the config this project generates
      sets no `master_key` (V11); `api_key` is stripped server-side before
      it ever reaches here (V10).

    Deployment counts are never assumed. Whatever the proxy reports --
    3, 48, or 0 -- is what gets counted; nothing here hardcodes a pool size.
    """
    from .proxy import parse_deployment_id

    base = url.rstrip("/")
    now = time.time()
    try:
        req = urllib.request.Request(base + "/health/liveliness")
        with urllib.request.urlopen(req, timeout=_PROXY_LIVENESS_TIMEOUT) as fh:
            fh.read(200)
    except Exception as e:                                  # noqa: BLE001
        return {"configured": True, "reachable": False, "source": url,
                "observed_at": now,
                "why": f"proxy not reachable at {url}: {type(e).__name__}"}

    try:
        req = urllib.request.Request(base + "/model/info",
                                     headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_PROXY_INFO_TIMEOUT) as fh:
            info = json.loads(fh.read())
    except Exception as e:                                  # noqa: BLE001
        return {"configured": True, "reachable": True, "source": url,
                "observed_at": now,
                "why": f"proxy is up but /model/info failed: "
                       f"{type(e).__name__}: {e}"}

    rows = info.get("data") if isinstance(info, dict) else None
    if not isinstance(rows, list):
        return {"configured": True, "reachable": True, "source": url,
                "observed_at": now,
                "why": "/model/info answered but its shape was not the "
                       "one this proxy version was measured to return"}

    # Group deployments back into accounts. An id that does not match
    # `agentctl`'s own `provider-aN-mI` format is counted as unmatched,
    # never guessed at -- it may belong to a hand-edited or foreign config.
    by_acct: dict[str, dict] = {}
    unmatched = 0
    for row in rows:
        mi = (row.get("model_info") or {}) if isinstance(row, dict) else {}
        parsed = parse_deployment_id(mi.get("id") or "")
        if parsed is None:
            unmatched += 1
            continue
        provider, n, _model_idx = parsed
        label = f"{provider}-a{n}"
        acct = by_acct.setdefault(
            label, {"provider": provider, "label": label, "n": n,
                    "deployments": 0, "free": True})
        acct["deployments"] += 1
        acct["free"] = acct["free"] and bool(mi.get("free", True))

    return {"configured": True, "reachable": True, "source": url,
            "observed_at": now, "deployments": len(rows),
            "unmatched": unmatched,
            "accounts": sorted(by_acct.values(),
                               key=lambda a: (a["provider"], a["n"]))}


def _providers(pool: dict | None = None) -> list[dict]:
    """One row per ACCOUNT, not per provider.

    Two keys at one provider are two quotas, and collapsing them into a single
    row would hide the failover you actually bought (`docs/0033`).

    When a proxy is configured and its `/model/info` answered, rows come from
    what it actually loaded rather than from what the environment implies --
    that is the upgrade in `docs/0038` §5.2. Any other case (no proxy
    configured, unreachable, or an unreadable response -- see `pool["why"]`)
    falls back to the environment, exactly as before this existed.
    """
    if pool and pool.get("accounts"):
        when = time.strftime("%H:%M:%S", time.localtime(pool["observed_at"]))
        rows = []
        for acct in pool["accounts"]:
            p = BY_NAME.get(acct["provider"])
            rows.append({
                "name": acct["label"], "env": p.key if p else "?",
                "configured": True,
                "detail": f"{acct['deployments']} deployment(s) loaded by "
                          f"the proxy -- source: /model/info at {when}",
                "free": acct["free"],
                "model": p.default_model if p else "",
            })
        return rows
    return _providers_from_env()


def _providers_from_env() -> list[dict]:
    """The original panel: what the environment implies is configured."""
    from .providers import accounts_for

    rows = []
    for p in PROVIDERS:
        mine = accounts_for(p)
        if not mine:
            rows.append({"name": p.name, "env": p.key, "configured": False,
                         "detail": p.console, "free": p.free_tier,
                         "model": p.default_model})
            continue
        for a in mine:
            rows.append({
                "name": a.label, "env": a.env, "configured": True,
                # Length only. Never the value.
                "detail": f"set ({len(os.environ.get(a.env, ''))} chars)",
                "free": p.free_tier, "model": p.default_model,
            })
    return rows


def _capacity(pool: dict) -> dict:
    """Can I work right now? Always **UNKNOWN** -- see the module docstring.

    Not a placeholder waiting for a better source: research established there
    is no honest zero-cost source. Cooldown state lives in the router's
    in-process cache, reachable from no endpoint (V14); `healthy_only` fails
    open and measures background-health-check state, a different thing
    (V15); the Prometheus gauge was measured still reporting complete
    outage 15 seconds after a cooldown expired (V16); `GET /health` costs
    one real completion per deployment (V13). There is deliberately no code
    path in this function that returns anything but `UNKNOWN`.
    """
    if not pool or not pool.get("configured"):
        return {"verdict": "UNKNOWN",
                "detail": "no proxy is configured (set AGENTCTL_PROXY_URL) "
                          "-- and capacity would not be knowable even with "
                          "one: cooldown state has no HTTP surface."}
    if not pool.get("reachable"):
        return {"verdict": "UNKNOWN",
                "detail": pool.get("why", "the proxy is configured but "
                                          "not reachable right now.")}
    if "accounts" not in pool:
        return {"verdict": "UNKNOWN",
                "detail": pool.get("why", "the proxy answered, but its "
                                          "/model/info response could not "
                                          "be read.")}
    n_dep, n_acct = pool.get("deployments", 0), len(pool["accounts"])
    return {"verdict": "UNKNOWN",
            "detail": (f"the proxy is up and {n_dep} deployment(s) across "
                       f"{n_acct} account(s) are configured, but the "
                       f"router's cooldown state is not exposed on any "
                       f"endpoint, and a live probe (GET /health) would "
                       f"spend {n_dep} requests of the quota it reports on.")}


# Fixed reasons for the providers that expose no usable quota signal to an
# ordinary inference key (`docs/0038` §5.3, `research/phase-10-3-model-
# selection.md` §2.3). Structural, not a docstring promise: `_quota` below
# has no code path that turns one of these into a number.
_QUOTA_REASON = {
    "gemini": "Gemini publishes no quota endpoint or header; the only "
              "signal is the 429 when it arrives",
    "mistral": "the usage API needs an Admin key from the Backoffice, and "
               "reports consumed spend, not what remains",
    "cerebras": "no documented quota signal for an ordinary inference key",
    "groq": "no quota endpoint; remaining is reported only on a response "
            "header, and only once a request has actually been made",
    "anthropic": "the Rate Limits API needs an Admin key, documented as "
                 "unavailable for individual accounts",
    "openai": "no free tier here; not polled",
}


def _quota(refresh: bool) -> list[dict]:
    """Per-account quota. **OpenRouter is the only provider with an honest
    number here** (`docs/0038` §5.3) -- every other row says why it has none,
    never a `0`.

    Manual refresh only, enforced structurally: the network call happens if
    and only if `refresh` is `True`. Nothing in this function is ever polled.
    """
    from .providers import all_accounts

    rows = []
    for a in all_accounts():
        if a.provider.name != "openrouter":
            rows.append({"label": a.label, "value": None,
                         "reason": _QUOTA_REASON.get(
                             a.provider.name, "no documented quota signal")})
            continue
        if not refresh:
            rows.append({"label": a.label, "value": None,
                         "reason": "not checked this session "
                                   "(agentctl dash --refresh-quota)"})
            continue
        from .probe import openrouter_quota
        q = openrouter_quota(a)
        when = time.strftime("%H:%M:%S", time.localtime(q.checked_at))
        if q.ok:
            rows.append({
                "label": a.label,
                "value": f"{q.remaining} of {q.limit} free requests remaining",
                "reason": f"source: openrouter /api/v1/key at {when}"})
        else:
            rows.append({"label": a.label, "value": None,
                         "reason": f"could not check ({q.detail}) at {when}"})
    return rows


def _failover() -> dict:
    from .providers import all_accounts

    accts = all_accounts()
    n = len(accts)
    providers = {a.provider.name for a in accts}
    free = [a for a in accts if a.provider.free_tier]

    if n == 0:
        verdict, detail = "NONE", "no provider key is set; nothing can run"
    elif n == 1:
        verdict = "SINGLE ACCOUNT"
        detail = (f"only {accts[0].label}. A per-model limit or a transient "
                  f"outage is survivable; an account-wide daily cap is not -- "
                  f"there is nowhere to go. A second key, even at the same "
                  f"provider, is a second quota.")
    elif len(providers) == 1:
        # Better than one, and still one provider outage away from zero.
        verdict = "MULTI-ACCOUNT"
        detail = (f"{n} accounts, all at {next(iter(providers))} "
                  f"({', '.join(a.label for a in accts)}). A daily cap on one "
                  f"leaves {n - 1}; the provider going down takes all of them.")
    else:
        verdict = "READY"
        # Counts per provider, not 31 labels. A detail line nobody reads is
        # the same as no detail line.
        per: dict[str, int] = {}
        for a in accts:
            per[a.provider.name] = per.get(a.provider.name, 0) + 1
        shape = ", ".join(f"{name} x{k}" if k > 1 else name
                          for name, k in per.items())
        # "Accounts you HOLD", never "accounts that work". Six Cerebras keys
        # authenticate happily and every completion returns "Payment
        # required" (`docs/0034` §7), so a banner counting credentials as
        # capacity overstates the pool by however many of those you have --
        # and it sits directly above a capacity panel that scrupulously
        # answers UNKNOWN. One honest panel under one confident wrong one is
        # worse than neither (`docs/0039`).
        detail = (f"{n} accounts across {len(providers)} providers "
                  f"({shape}) are CONFIGURED -- that is a count of keys, not "
                  f"of what can serve. Enough shape to survive a cap and an "
                  f"outage; whether it does is what `agentctl keys --check` "
                  f"and `agentctl models --verify` answer.")
    return {"accounts": n, "free_accounts": len(free),
            "providers": len(providers),
            "verdict": verdict, "detail": detail,
            "missing": [{"name": p.name, "console": p.console, "free": p.free_tier}
                        for p in missing()]}


def _effects(path: str | Path | None) -> dict:
    p = Path(path) if path else Path("ledger.db")
    if not p.exists():
        return {"available": False, "why": f"no effect ledger at {p}"}
    try:
        from agentctl.kernel.ledger.store import LedgerStore
        with LedgerStore(p, holder="dash") as s:
            rows = s._db.execute(
                "SELECT state, effect_class, COUNT(*) n FROM effect_record "
                "GROUP BY state, effect_class").fetchall()
            convs = s._db.execute("SELECT COUNT(DISTINCT conversation_id) n "
                                  "FROM effect_record").fetchone()["n"]
    except Exception as e:                              # noqa: BLE001
        return {"available": False, "why": f"{type(e).__name__}: {e}"}

    by_state: dict[str, int] = {}
    by_class: dict[str, int] = {}
    for r in rows:
        by_state[r["state"]] = by_state.get(r["state"], 0) + r["n"]
        by_class[r["effect_class"]] = by_class.get(r["effect_class"], 0) + r["n"]
    return {"available": True, "path": str(p), "conversations": convs,
            "total": sum(by_state.values()),
            "by_state": by_state, "by_class": by_class,
            "blocked": by_state.get("BLOCKED", 0),
            "pending": by_state.get("INTENT", 0)}


def _cost(path: str | Path | None) -> dict:
    p = Path(path) if path else Path("cost.db")
    if not p.exists():
        return {"available": False,
                "why": f"no cost ledger at {p} -- run: agentctl ingest "
                       f"<hook_telemetry.json>"}
    try:
        from .cost import CostLedger
        with CostLedger(p) as c:
            all_time = c.totals()
            today = c.totals(since=time.time() - 86400)
    except Exception as e:                              # noqa: BLE001
        return {"available": False, "why": f"{type(e).__name__}: {e}"}

    def pack(t):
        return {"spend": t.describe_cost(), "calls": t.calls,
                "coverage": t.coverage, "trustworthy": t.trustworthy,
                "prompt_tokens": t.prompt_tokens,
                "cache_hit_ratio": t.cache_hit_ratio}
    return {"available": True, "path": str(p),
            "today": pack(today), "all_time": pack(all_time)}


def _policy() -> dict:
    try:
        from agentctl.kernel.policy import DEFAULT_POLICY, Policy
        if not DEFAULT_POLICY.exists():
            return {"available": False,
                    "why": "not compiled -- agentctl policy "
                           "agentctl/control/policy/data/policy.yaml"}
        pol = Policy.load()
    except Exception as e:                              # noqa: BLE001
        return {"available": False, "why": f"{type(e).__name__}: {e}"}
    return {"available": True,
            "per_task": pol.limit("per_task"), "daily": pol.limit("daily"),
            "on_exceeded": pol.on_exceeded, "on_unpriced": pol.on_unpriced,
            "default_pool": pol.default_pool,
            "effects": {c: pol.effect_rule(c) for c in
                        ("DESTRUCTIVE", "EXTERNAL", "NON_IDEMPOTENT_WRITE")
                        if pol.effect_rule(c)}}


# ── terminal ───────────────────────────────────────────────────────────
def render(d: dict) -> str:
    L: list[str] = []
    w = 74
    L.append("=" * w)
    L.append("  agentctl dashboard" + time.strftime(
        "%Y-%m-%d %H:%M", time.localtime(d["generated"])).rjust(w - 21))
    L.append("=" * w)

    f = d["failover"]
    proxy = d["proxy"]
    L.append("")
    L.append(f"  FAILOVER   {f['verdict']}")
    for line in _wrap(f["detail"], w - 14):
        L.append(f"             {line}")
    if proxy.get("configured"):
        # `docs/0038` §6.4's rule: this verdict describes configured shape,
        # not live capacity, and must not be re-read as the second thing.
        L.append("             (configured shape, not live capacity --")
        L.append("             see CAN I WORK RIGHT NOW below)")

    L.append("")
    L.append("  PROXY")
    if not proxy.get("configured"):
        L.append("    not configured   set AGENTCTL_PROXY_URL to read the "
                 "live pool instead of the environment")
    elif not proxy.get("reachable"):
        L.append(f"    NOT reachable   {proxy['source']}")
        for line in _wrap(proxy.get("why", ""), w - 8):
            L.append(f"    {line}")
    elif "accounts" not in proxy:
        L.append(f"    up, but unreadable   {proxy['source']}")
        for line in _wrap(proxy.get("why", ""), w - 8):
            L.append(f"    {line}")
    else:
        when = time.strftime("%H:%M:%S", time.localtime(proxy["observed_at"]))
        L.append(f"    up   {proxy['source']}   source: /health/liveliness "
                 f"at {when}")
        L.append(f"    {proxy['deployments']} deployment(s) across "
                 f"{len(proxy['accounts'])} account(s)   "
                 f"source: /model/info at {when}")
        if proxy.get("unmatched"):
            L.append(f"    {proxy['unmatched']} deployment(s) did not match "
                     f"agentctl's own id format -- not counted above")

    cap = d["capacity"]
    L.append("")
    L.append(f"  CAN I WORK RIGHT NOW?   {cap['verdict']}")
    for line in _wrap(cap["detail"], w - 4):
        L.append(f"    {line}")

    L.append("")
    L.append("  PROVIDERS")
    for p in d["providers"]:
        mark = "ok  " if p["configured"] else "--  "
        tag = "" if p["free"] else "  (paid)"
        L.append(f"    {mark} {p['name']:<12}{tag:<8} {p['detail']}")

    if f["missing"]:
        L.append("")
        L.append("  ADD AN ACCOUNT   (a second provider is what makes a cap survivable)")
        for m in f["missing"]:
            if m["free"]:
                L.append(f"    {m['name']:<12} {m['console']}")

    L.append("")
    L.append("  QUOTA")
    for q in d["quota"]:
        if q["value"]:
            L.append(f"    {q['label']:<16} {q['value']}")
            L.append(f"    {'':<16} {q['reason']}")
        else:
            L.append(f"    {q['label']:<16} --")
            for line in _wrap(q["reason"], w - 20):
                L.append(f"    {'':<16} {line}")

    e = d["effects"]
    L.append("")
    L.append("  EFFECTS")
    if not e["available"]:
        L.append(f"    (none)   {e['why']}")
    else:
        L.append(f"    {e['total']} effect(s) across {e['conversations']} "
                 f"conversation(s)")
        for cls, n in sorted(e["by_class"].items(), key=lambda kv: -kv[1]):
            L.append(f"      {cls:<24} {n}")
        if e["blocked"]:
            L.append(f"    !! {e['blocked']} BLOCKED -> agentctl blocked")
        if e["pending"]:
            L.append(f"    .. {e['pending']} still INTENT (a run may be live)")

    c = d["cost"]
    L.append("")
    L.append("  SPEND")
    if not c["available"]:
        L.append(f"    (none)   {c['why']}")
    else:
        for label in ("today", "all_time"):
            t = c[label]
            L.append(f"    {label:<10} {t['spend']}   {t['calls']} call(s)")
            if t["calls"] and not t["trustworthy"]:
                L.append(f"               ! only {t['coverage']:.0%} of calls "
                         f"could be priced; the real figure is HIGHER")

    p = d["policy"]
    L.append("")
    L.append("  POLICY")
    if not p["available"]:
        L.append(f"    (none)   {p['why']}")
    else:
        caps = "  ".join(f"{k} ${v:.2f}" for k, v in
                         (("per-task", p["per_task"]), ("daily", p["daily"]))
                         if v is not None)
        L.append(f"    caps       {caps or 'none'}   on-exceeded: {p['on_exceeded']}")
        for cls, rule in p["effects"].items():
            L.append(f"    {cls:<10} {rule}")
    L.append("")
    return "\n".join(L)


def _wrap(text: str, width: int) -> list[str]:
    import textwrap
    return textwrap.wrap(text, width) or [""]


# ── html ───────────────────────────────────────────────────────────────
def to_html(d: dict) -> str:
    """A single self-contained page. No CDN, no fonts, no network."""
    def esc(x):
        return html.escape(str(x))

    f, proxy, cap = d["failover"], d["proxy"], d["capacity"]
    tone = {"READY": "#1a7f37", "MULTI-ACCOUNT": "#7a6a00",
            "SINGLE ACCOUNT": "#9a6700",
            "NONE": "#b3261e"}.get(f["verdict"], "#57606a")
    # Capacity has exactly one verdict, UNKNOWN, and it must never borrow the
    # green FAILOVER tone -- a fixed neutral colour, not a lookup, so there is
    # no dict entry to someday add "READY" to by accident.
    CAPACITY_TONE = "#57606a"

    def provider_row(p: dict) -> str:
        dot = "&#9679;" if p["configured"] else "&#9675;"
        paid = "" if p["free"] else " <i>paid</i>"
        # `detail` is "set (N chars)" when configured and the console URL when
        # not. Only the second is ever rendered as a link, and the first never
        # contains the key itself.
        if p["configured"]:
            action = "set"
        else:
            action = f'<a href="{esc(p["detail"])}">get a key</a>'
        return (f'<tr class="{"on" if p["configured"] else "off"}">'
                f"<td>{dot}</td>"
                f"<td><b>{esc(p['name'])}</b>{paid}</td>"
                f"<td><code>{esc(p['env'])}</code></td>"
                f"<td>{action}</td></tr>")

    rows = "".join(provider_row(p) for p in d["providers"])

    if not proxy.get("configured"):
        proxy_line = "<span class='muted'>not configured -- set AGENTCTL_PROXY_URL</span>"
    elif not proxy.get("reachable") or "accounts" not in proxy:
        proxy_line = f"<span class='warn'>{esc(proxy.get('why', 'unreachable'))}</span>"
    else:
        proxy_line = (f"up -- {proxy['deployments']} deployment(s) across "
                      f"{len(proxy['accounts'])} account(s) "
                      f"<span class='muted'>(source: /model/info)</span>")

    def quota_row(q: dict) -> str:
        if q["value"]:
            return (f"<tr><td><b>{esc(q['label'])}</b></td>"
                    f"<td>{esc(q['value'])}<br>"
                    f"<span class='muted'>{esc(q['reason'])}</span></td></tr>")
        return (f"<tr class='off'><td><b>{esc(q['label'])}</b></td>"
                f"<td class='muted'>-- {esc(q['reason'])}</td></tr>")

    quota = "<table>" + "".join(quota_row(q) for q in d["quota"]) + "</table>"

    e, c, pol = d["effects"], d["cost"], d["policy"]
    eff = ("<p class='muted'>" + esc(e["why"]) + "</p>" if not e["available"]
           else "<table>" + "".join(
               f"<tr><td>{esc(k)}</td><td class='n'>{v}</td></tr>"
               for k, v in sorted(e["by_class"].items(), key=lambda kv: -kv[1]))
           + "</table>")
    cost = ("<p class='muted'>" + esc(c["why"]) + "</p>" if not c["available"]
            else "".join(
                f"<p><b>{k.replace('_',' ')}</b> {esc(c[k]['spend'])} "
                f"<span class='muted'>{c[k]['calls']} calls</span>"
                + ("" if c[k]["trustworthy"] or not c[k]["calls"] else
                   f"<br><span class='warn'>only {c[k]['coverage']:.0%} priced "
                   f"-- the real figure is higher</span>")
                + "</p>" for k in ("today", "all_time")))
    poli = ("<p class='muted'>" + esc(pol["why"]) + "</p>" if not pol["available"]
            else "".join(
                f"<p><b>{esc(k)}</b> {esc(v)}</p>" for k, v in
                [("per-task cap", f"${pol['per_task']:.2f}" if pol["per_task"] else "none"),
                 ("daily cap", f"${pol['daily']:.2f}" if pol["daily"] else "none"),
                 ("on exceeded", pol["on_exceeded"]),
                 *pol["effects"].items()]))

    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["generated"]))
    return f"""<!doctype html><meta charset="utf-8">
<title>agentctl dashboard</title>
<style>
 :root {{ color-scheme: light dark; }}
 body {{ font: 15px/1.5 ui-sans-serif, system-ui, sans-serif; margin: 0;
        background: #f6f8fa; color: #1f2328; }}
 @media (prefers-color-scheme: dark) {{
   body {{ background:#0d1117; color:#e6edf3; }}
   .card {{ background:#161b22 !important; border-color:#30363d !important; }}
   code {{ background:#21262d !important; }} }}
 .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px 20px 60px; }}
 h1 {{ font-size: 20px; margin: 0 0 4px; }}
 .muted {{ color: #57606a; }} .warn {{ color:#9a6700; }}
 .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); }}
 .card {{ background:#fff; border:1px solid #d0d7de; border-radius:10px; padding:16px; }}
 .card h2 {{ font-size:12px; letter-spacing:.08em; text-transform:uppercase;
            color:#57606a; margin:0 0 10px; }}
 table {{ width:100%; border-collapse:collapse; }}
 td {{ padding:4px 6px; border-bottom:1px solid rgba(128,128,128,.18); }}
 td.n {{ text-align:right; font-variant-numeric:tabular-nums; }}
 tr.off {{ opacity:.55; }}
 code {{ background:#eef1f4; padding:1px 5px; border-radius:4px; font-size:13px; }}
 .banner {{ border-left:4px solid {tone}; padding:10px 14px; margin:0 0 12px;
            background:#fff; border-radius:0 8px 8px 0; }}
 .banner b {{ color:{tone}; }}
 .banner.capacity {{ border-left-color:{CAPACITY_TONE}; margin:0 0 20px; }}
 .banner.capacity b {{ color:{CAPACITY_TONE}; }}
</style>
<div class="wrap">
  <h1>agentctl</h1>
  <p class="muted">generated {when} &middot; values are never shown, only whether a key is set</p>
  <div class="banner"><b>FAILOVER: {esc(f['verdict'])}</b><br>{esc(f['detail'])}
    {"<br><span class='muted'>configured shape, not live capacity -- see below</span>" if proxy.get("configured") else ""}</div>
  <p class="muted">proxy: {proxy_line}</p>
  <div class="banner capacity"><b>CAN I WORK RIGHT NOW? {esc(cap['verdict'])}</b><br>{esc(cap['detail'])}</div>
  <div class="grid">
    <div class="card"><h2>Providers</h2><table>{rows}</table></div>
    <div class="card"><h2>Quota</h2>{quota}</div>
    <div class="card"><h2>Effects</h2>{eff}</div>
    <div class="card"><h2>Spend</h2>{cost}</div>
    <div class="card"><h2>Policy</h2>{poli}</div>
  </div>
</div>
"""
