r"""Preflight: what is ready, what is missing, what will stop you.

Built because a run burned fifteen tool calls and produced nothing, and the
only signal was a `RateLimitError` traceback thirty lines deep ending in
*"please file a bug report at github.com/OpenHands"* — which is not where the
problem was.

Everything here is free and offline except the provider probe, which reads your
own account status and costs no model request.

## The one thing it cannot tell you

OpenRouter's free-model daily allowance is **not exposed by any free endpoint.**
`auth/key` reports dollar usage and free-tier status; the remaining-request
counter appears only in the `X-RateLimit-Remaining` header of a 429, which you
get by hitting the wall. Probed both `auth/key` and `credits`: no rate-limit
headers on either.

So this reports what is knowable and says plainly that the quota is not. A
check that guessed would be worse than one that admits the gap.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROVIDERS = [
    ("OPENROUTER_API_KEY", "openrouter", "many models, free tier available"),
    ("ANTHROPIC_API_KEY", "anthropic", "paid"),
    ("OPENAI_API_KEY", "openai", "paid"),
    ("GEMINI_API_KEY", "gemini", "free tier available"),
    ("MISTRAL_API_KEY", "mistral", "free tier available"),
    ("CEREBRAS_API_KEY", "cerebras", "free tier available"),
    ("GROQ_API_KEY", "groq", "free tier available"),
]

OK, WARN, BAD = "ok", "!!", "XX"


def check_all(workspace: str | Path | None = None,
              probe_network: bool = True) -> list[tuple[str, str, str]]:
    """[(status, subject, detail)] — never raises, always reports."""
    out: list[tuple[str, str, str]] = []
    out += _packages()
    out += _providers(probe_network)
    out += _tooling()
    out += _policy()
    if workspace:
        out += _workspace(Path(workspace))
    return out


# ── checks ─────────────────────────────────────────────────────────────
def _packages() -> list[tuple[str, str, str]]:
    from importlib.metadata import version

    rows = []
    for pkg, need in (("openhands-sdk", None), ("litellm", None),
                      ("mcp", 2), ("fastmcp", None), ("pyyaml", None)):
        try:
            v = version(pkg)
        except Exception:                               # noqa: BLE001
            rows.append((BAD, pkg, "not installed"))
            continue
        if need and int(v.split(".")[0]) < need:
            # docs/0021 §7: litellm[proxy] has downgraded this before, and
            # `pip check` reported nothing wrong.
            rows.append((BAD, pkg, f"{v} — needs >= {need}; the SDK will "
                                   f"fail to import"))
        else:
            rows.append((OK, pkg, v))

    try:
        from fastmcp import Client                      # noqa: F401
        rows.append((OK, "fastmcp client", "importable"))
    except Exception as e:                              # noqa: BLE001
        # `import fastmcp` alone succeeds even when this is broken (docs/0028).
        rows.append((BAD, "fastmcp client", f"{type(e).__name__}: {e}"))

    try:
        from openhands.sdk.event.base import Event      # noqa: F401
        rows.append((OK, "openhands sdk", "imports cleanly"))
    except Exception as e:                              # noqa: BLE001
        rows.append((BAD, "openhands sdk", f"{type(e).__name__}: {e}"))
    return rows


def _providers(probe: bool) -> list[tuple[str, str, str]]:
    rows = []
    present = [(env, name, note) for env, name, note in PROVIDERS
               if os.environ.get(env)]
    for env, name, note in PROVIDERS:
        if os.environ.get(env):
            rows.append((OK, name, f"{env} set ({note})"))

    if not present:
        rows.append((BAD, "providers", "no API key in the environment"))
        return rows

    if len(present) == 1:
        # This is the project's own thesis: one account cannot fail over.
        rows.append((WARN, "failover",
                     f"only {present[0][1]} is configured — a rate limit on it "
                     f"stops all work. A pool needs a second provider."))

    if probe and os.environ.get("OPENROUTER_API_KEY"):
        rows.append(_openrouter())
    return rows


def _openrouter() -> tuple[str, str, str]:
    """Read our own account. No model request, so it costs nothing."""
    import urllib.request

    key = os.environ["OPENROUTER_API_KEY"]
    try:
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=15) as fh:
            d = json.loads(fh.read())["data"]
    except Exception as e:                              # noqa: BLE001
        return (WARN, "openrouter", f"could not reach: {type(e).__name__}")

    if d.get("is_free_tier"):
        return (WARN, "openrouter quota",
                "FREE TIER: 50 model requests/day, account-wide across every "
                "`:free` model. The remaining count is not exposed by any "
                "endpoint — you find out at the 50th request.")
    return (OK, "openrouter quota",
            f"paid key, ${float(d.get('usage') or 0):.4f} used")


def _tooling() -> list[tuple[str, str, str]]:
    rows = []
    git = shutil.which("git")
    rows.append((OK, "git", git) if git else
                (BAD, "git", "not on PATH — the git probe and chaos suite need it"))
    rows.append((OK, "python", sys.version.split()[0]))
    if sys.version_info < (3, 12):
        rows[-1] = (BAD, "python", f"{sys.version.split()[0]} — needs >= 3.12")
    return rows


def _policy() -> list[tuple[str, str, str]]:
    from agentctl.kernel.policy import DEFAULT_POLICY, Policy

    if not DEFAULT_POLICY.exists():
        return [(WARN, "policy", "not compiled — run: agentctl policy "
                                 "agentctl/control/policy/data/policy.yaml")]
    try:
        p = Policy.load()
    except Exception as e:                              # noqa: BLE001
        return [(BAD, "policy", f"compiled artifact unreadable: {e}")]
    caps = ", ".join(f"{s} ${p.limit(s):.2f}" for s in ("per_task", "daily")
                     if p.limit(s) is not None)
    return [(OK, "policy", f"{caps or 'no caps'} | "
                           f"destructive: {p.effect_rule('DESTRUCTIVE') or '-'}")]


def _workspace(ws: Path) -> list[tuple[str, str, str]]:
    rows = []
    if not ws.exists():
        return [(WARN, "workspace", f"{ws} does not exist yet")]
    try:
        probe = ws / ".agentctl_write_probe"
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        rows.append((OK, "workspace", f"{ws} (writable)"))
    except Exception as e:                              # noqa: BLE001
        rows.append((BAD, "workspace", f"{ws} not writable: {e}"))

    if (ws / ".git").exists():
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=str(ws),
                               capture_output=True, text=True).stdout.strip()
        rows.append((WARN, "uncommitted", f"{len(dirty.splitlines())} changed "
                     f"file(s) — the agent edits real files; commit first")
                    if dirty else (OK, "git tree", "clean"))
    else:
        rows.append((WARN, "git", f"{ws} is not a git repo — no way to undo "
                                  f"what the agent writes"))

    led = ws / ".agentctl" / "ledger.db"
    if led.exists():
        rows.append((OK, "ledger", f"{led}  (agentctl --ledger <path> status)"))
    return rows


def report(rows: list[tuple[str, str, str]]) -> int:
    """Print, and return an exit code. Any BAD is a failure."""
    width = max((len(s) for _, s, _ in rows), default=10)
    for status, subject, detail in rows:
        print(f"  {status:<4} {subject:<{width}}  {detail}")
    bad = [r for r in rows if r[0] == BAD]
    warn = [r for r in rows if r[0] == WARN]
    print()
    if bad:
        print(f"  {len(bad)} blocking problem(s). Fix these before running.")
        return 1
    print(f"  ready{f' — {len(warn)} warning(s) worth reading' if warn else ''}")
    return 0
