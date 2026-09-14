r"""One screen: providers, failover, effects, spend, policy.

    agentctl dash                 the terminal view
    agentctl dash --html out.html a page you can open or hand to someone

Everything here is **derived**, never asserted. Each panel reads a real source
— the environment, the effect ledger, the cost ledger, the compiled policy —
and a panel with nothing behind it says so rather than showing a confident
zero. `docs/0021` §5 is the reason: a cost of `$0.00` that actually means "no
data" is worse than a blank, because it reads as good news.

Key values are never displayed. The provider panel shows `set`, never the key.
"""
from __future__ import annotations

import html
import os
import time
from pathlib import Path
from typing import Any

from .providers import PROVIDERS, configured, missing


def collect(ledger: str | Path | None = None,
            cost_ledger: str | Path | None = None) -> dict[str, Any]:
    """Everything the dashboard shows. Pure gathering, no formatting."""
    return {
        "generated": time.time(),
        "providers": _providers(),
        "failover": _failover(),
        "effects": _effects(ledger),
        "cost": _cost(cost_ledger),
        "policy": _policy(),
    }


# ── panels ─────────────────────────────────────────────────────────────
def _providers() -> list[dict]:
    """One row per ACCOUNT, not per provider.

    Two keys at one provider are two quotas, and collapsing them into a single
    row would hide the failover you actually bought (`docs/0033`).
    """
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
                  f"outage is survivable; an account-wide daily cap is not — "
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
        detail = (f"{n} accounts across {len(providers)} providers "
                  f"({', '.join(a.label for a in accts)}). Survives a cap and "
                  f"an outage.")
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
                "why": f"no cost ledger at {p} — run: agentctl ingest "
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
                    "why": "not compiled — agentctl policy "
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
    L.append("")
    L.append(f"  FAILOVER   {f['verdict']}")
    for line in _wrap(f["detail"], w - 14):
        L.append(f"             {line}")

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

    f = d["failover"]
    tone = {"READY": "#1a7f37", "MULTI-ACCOUNT": "#7a6a00",
            "SINGLE ACCOUNT": "#9a6700",
            "NONE": "#b3261e"}.get(f["verdict"], "#57606a")

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
                   f"— the real figure is higher</span>")
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
 .banner {{ border-left:4px solid {tone}; padding:10px 14px; margin:0 0 20px;
            background:#fff; border-radius:0 8px 8px 0; }}
 .banner b {{ color:{tone}; }}
</style>
<div class="wrap">
  <h1>agentctl</h1>
  <p class="muted">generated {when} &middot; values are never shown, only whether a key is set</p>
  <div class="banner"><b>FAILOVER: {esc(f['verdict'])}</b><br>{esc(f['detail'])}</div>
  <div class="grid">
    <div class="card"><h2>Providers</h2><table>{rows}</table></div>
    <div class="card"><h2>Effects</h2>{eff}</div>
    <div class="card"><h2>Spend</h2>{cost}</div>
    <div class="card"><h2>Policy</h2>{poli}</div>
  </div>
</div>
"""
