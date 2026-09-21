r"""Preflight: what is ready, what is missing, what will stop you.

Built because a run burned fifteen tool calls and produced nothing, and the
only signal was a `RateLimitError` traceback thirty lines deep ending in
*"please file a bug report at github.com/OpenHands"* — which is not where the
problem was.

Everything here is free and offline except the provider probe, which reads your
own account status and costs no model request.

## What this check fetches, and what it doesn't

This module's own OpenRouter check calls `/api/v1/auth/key`, which reports
dollar usage and free-tier status but not the remaining daily count. That was
recorded here as unknowable by any free endpoint -- checked again on
2026-09-21 and found false. The sibling endpoint `/api/v1/key` exposes it
directly, at the same cost (zero) and with the same auth
(`probe.py::openrouter_quota`, `free_model_daily_requests:
{used, limit, remaining}`, confirmed live across six accounts). This check
still does not call it -- that number belongs in `agentctl dash`, not in a
preflight -- but it no longer claims the number cannot be known.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Derived, never duplicated. `doctor` and `proxy` each kept their own provider
# list until one registry replaced both -- two lists drift, and drift here
# means a key you added is checked by one command and ignored by another. The
# same defect as `docs/0029` §4.
def _provider_rows() -> list[tuple[str, str, str]]:
    from agentctl.control.providers import PROVIDERS as _P
    return [(p.key, p.name,
             "free tier available" if p.free_tier else "paid") for p in _P]


PROVIDERS = _provider_rows()

OK, WARN, BAD = "ok", "!!", "XX"


# ── Groq's turn-2 ceiling (`docs/0038` §4.1, `research/phase-10-2` V3-V5, I1) ──
# Three separately-dated facts. The conclusion below is COMPUTED from them,
# never written down as a bare number, so updating one fact updates the
# conclusion instead of leaving a stale headline behind.
#
# VERIFIED, in this repo, reproducible offline with no network and no key --
# `tests/test_doctor_groq_prefix.py` re-measures both live and fails if
# either has drifted from the constant pinned here:
_FIXED_PREFIX_TOKENS = 3_593         # 3,208 system prompt + 385 tool schemas
_PREFIX_MEASURED = "2026-09-20, openhands-sdk 1.45.0"
#
# _FIXED_PREFIX_TOKENS is environment-dependent by about two tokens: 3,593
# measured on Windows, 3,591 on Linux CI, same commit and same encoding. The
# cause is not identified -- neither the system prompt nor the tool schemas
# contain an OS string or a path. It does not move the conclusion (311 tokens
# of headroom versus 313, both far below one turn), and
# tests/test_doctor_groq_prefix.py asserts the conclusion rather than the
# constant for exactly that reason.
#
_RUNNER_MAX_OUTPUT_TOKENS = 4_096    # mirrors runtime/runner.py:221 -- not
                                      # importable, no constant exists there;
                                      # the same test pins this one too.
#
# INFERRED, external to this repo, and NOT re-checked by the test suite --
# dated so it is visibly different in kind from the two facts above. Source
# tier T3 (issue trackers + one article): Groq's own rate-limits page frames
# TPM as a budget but does not state the prompt+max_tokens mechanism in so
# many words. This can go stale or turn out wrong without this repo noticing.
_GROQ_TPM_CEILING = 8_000
_GROQ_TPM_SOURCE = "console.groq.com/docs/rate-limits, checked 2026-09-20"


def _groq_headroom(accts: list) -> tuple[str, str, str] | None:
    """How much of Groq's TPM ceiling is left for conversation, and whether
    Groq is all the user has.

    Returns None when no Groq account is configured — nothing to warn about.
    Status is WARN, never BAD: turn 1 does work, and the failure mode is
    INFERRED, not observed from this repo (`docs/0038` §4.1, confirmed by an
    independent re-check at §9.3, not yet confirmed by an actual `agentctl
    run` against Groq). BAD means "this will not work"; this means "it likely
    won't work past turn 1," a different claim.
    """
    groq = [a for a in accts if a.provider.name == "groq"]
    if not groq:
        return None

    n_groq = len(groq) * len(groq[0].provider.models)
    # Deployments in the POOL, not credentials held. Counting every
    # account folds in providers that cannot serve -- six Cerebras
    # keys that 402 on every completion, one paid Anthropic key that
    # is never called -- and hides them inside the reassuring
    # remainder ("the other N carry no such limit"). That is the
    # accounts-held-vs-deployments-served conflation `docs/0038` 9.4
    # was written to diagnose, reappearing one file over (`docs/0039`).
    n_total = sum(len(a.provider.models) for a in accts
                  if a.provider.free_tier)
    headroom = _GROQ_TPM_CEILING - _RUNNER_MAX_OUTPUT_TOKENS - _FIXED_PREFIX_TOKENS

    only = (" Groq is the only provider you have configured — there is no "
            "other deployment in your pool that carries a real conversation."
            if len(groq) == len(accts) else "")

    detail = (
        f"{n_groq} of {n_total} configured deployment(s) are Groq.{only} "
        f"Groq's published free-tier limit ({_GROQ_TPM_CEILING:,} tok/min, "
        f"metered on prompt+max_tokens — {_GROQ_TPM_SOURCE}, INFERRED "
        f"mechanism, not this repo's own test) leaves ~{headroom} tokens of "
        f"conversation after this repo's measured {_FIXED_PREFIX_TOKENS:,}-"
        f"tok system prompt + tool schemas ({_PREFIX_MEASURED}) and "
        f"runner.py's max_output_tokens={_RUNNER_MAX_OUTPUT_TOKENS} — turn 2 "
        f"of most real tasks will 413. The other {n_total - n_groq} "
        f"deployment(s) carry no documented version of this limit, which is "
        f"not the same as a clean bill of health — providers.py deliberately "
        f"records no rate limits for anyone. Unconfirmed by a live call from "
        f"this repo — falsify: agentctl run --model "
        f"groq/openai/gpt-oss-120b <a trivial task>, watch turn 2."
    )
    return (WARN, "groq headroom", detail)


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


def _keys_file() -> list[tuple[str, str, str]]:
    """Is the keys file exposed to git? The guard nobody thinks to run.

    `keys.py` documents this as one of three guards, and it was not actually
    wired anywhere until the docstring was checked against the code.
    """
    from agentctl.control.keys import check_not_tracked, resolve

    p = resolve()
    if p is None:
        return [(WARN, "keys file",
                 "none found — run: agentctl keys --init")]
    if (warn := check_not_tracked(p)):
        return [(BAD, "keys file", warn)]
    return [(OK, "keys file", f"{p} (not exposed to git)")]


def _providers(probe: bool) -> list[tuple[str, str, str]]:
    from agentctl.control.providers import all_accounts

    rows = _keys_file()
    accts = all_accounts()
    for a in accts:
        rows.append((OK, a.label,
                     f"{a.env} set "
                     f"({'free tier' if a.provider.free_tier else 'paid'})"))

    if not accts:
        rows.append((BAD, "providers", "no API key in the environment"))
        return rows

    providers = {a.provider.name for a in accts}
    if len(accts) == 1:
        # The project's own thesis: one account cannot fail over.
        rows.append((WARN, "failover",
                     f"only {accts[0].label} — a daily cap on it stops all "
                     f"work. A second key, even at the same provider, is a "
                     f"second quota."))
    elif len(providers) == 1:
        rows.append((WARN, "failover",
                     f"{len(accts)} accounts, all at "
                     f"{next(iter(providers))} — survives a cap, not the "
                     f"provider going down."))

    # Offline, no network — runs regardless of `probe`.
    if (row := _groq_headroom(accts)) is not None:
        rows.append(row)

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
                "`:free` model. This check reports free-tier status only; "
                "the live remaining count is exposed separately by "
                "`probe.py::openrouter_quota` (GET /api/v1/key) for callers "
                "that want it.")
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
