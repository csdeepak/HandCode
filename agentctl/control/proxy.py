r"""Generate a LiteLLM proxy config from the keys that actually exist.

The project's charter is surviving a rate limit without work stopping. That
requires somewhere to fail over TO, and a config listing providers you have no
key for does not start -- litellm resolves `os.environ/X` at load and refuses.
So the config is generated from the environment rather than hand-written, and
adding a provider means exporting a key, not editing YAML.

## What failover can and cannot do for you

Two different failures, and a pool only fixes one of them with one account:

| failure | one OpenRouter key | plus a second provider |
|---|---|---|
| transient overload (*"Upstream error from Nvidia"*) | **fixed** — another model, another upstream | fixed |
| per-model rate limit | **fixed** | fixed |
| free-models-per-**day** cap | **not fixed** — the cap is account-wide | fixed |

Saying a pool fixes the daily cap would be the comfortable answer and the
wrong one: OpenRouter counts free requests per account, not per model. The
`:free` models below buy resilience against the first two rows, which is what
actually interrupted a real run, and nothing against the third.

## Fallbacks are ordered, and the order is a cost decision

`fallbacks` sends the next attempt to the next entry. Free models come first
and paid providers last, so an outage degrades toward *slower*, never silently
toward *billed*. `docs/0002` §5: never silently spend.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

# (env var, litellm model, short name, is_free). Order is fallback order:
# free first, paid last, so degrading never silently costs money.
POOL = "pool"
# A separate model group, never an automatic fallback target (`docs/0002` §5).
PAID = "paid"
# `pool-openrouter`, `pool-gemini`, ... One source, deliberately narrower than
# `pool`. The prefix is what makes a source group recognisable as one rather
# than as some unrelated model group someone hand-added (`docs/0039`).
SOURCE_PREFIX = "pool-"


def available(env: dict | None = None) -> list[tuple[str, str, str, bool]]:
    """One deployment per ACCOUNT per model: (env, model, id, is_free).

    The cross product is the point. Two OpenRouter accounts times three models
    is six deployments, and when one account hits its daily cap the other three
    keep serving — which a single-account pool cannot do however many models it
    lists (`docs/0033`).

    Ordered free-first, paid-last, because that is also the fallback order: an
    outage degrades toward slower, never silently toward billed (`docs/0002`
    §5).
    """
    from .providers import all_accounts

    out = []
    seen: dict[str, int] = {}
    for acct in all_accounts(env):
        n = seen[acct.provider.name] = seen.get(acct.provider.name, 0) + 1
        for i, model in enumerate(acct.provider.models):
            # `provider-aN-mI`, both parts always present and labelled. The
            # obvious scheme -- label plus model index -- produced
            # `openrouter-2` (account 1, model 2) alongside `openrouter-2-0`
            # (account 2, model 0): unique, and unreadable in a fallback map
            # exactly when you are debugging one. Nothing is abbreviated
            # either, since `openrouter` and `openai` share a prefix.
            short = f"{acct.provider.name}-a{n}-m{i}"
            out.append((acct.env, f"{acct.provider.prefix}{model}", short,
                        acct.provider.free_tier))
    return out


# The optional `-only` suffix marks a source-group copy. It is the SAME
# deployment under a narrower name, so it parses to the same triple --
# a caller counting deployments must not count it twice (`docs/0039`).
_DEPLOYMENT_ID = re.compile(r"^([a-z][a-z0-9]*)-a(\d+)-m(\d+)(?:-only)?$")


def parse_deployment_id(short: str) -> tuple[str, int, int] | None:
    """The inverse of the `short` id `available()` builds above: one place
    defines the format, this parses it, and a round-trip test ties them
    together so they cannot drift apart silently.

    Returns `(provider_name, account_ordinal, model_index)`, 1-indexed for
    the account to match the id text itself (`a1` -> `1`). `None` for
    anything that does not match -- callers must not guess at a foreign or
    malformed id, only count it as unrecognised.
    """
    m = _DEPLOYMENT_ID.match(short)
    if not m:
        return None
    provider, n, i = m.groups()
    return provider, int(n), int(i)


# Kept for callers that want the catalogue rather than what is configured.
def _candidates() -> list[tuple[str, str, str, bool]]:
    from .providers import PROVIDERS as _P
    return [(p.key, f"{p.prefix}{m}", f"{p.name}-{i}", p.free_tier)
            for p in sorted(_P, key=lambda x: not x.free_tier)
            for i, m in enumerate(p.models)]


CANDIDATES: list[tuple[str, str, str, bool]] = _candidates()


def accounts(entries: list[tuple[str, str, str, bool]]) -> set[str]:
    """Distinct credentials behind the pool, by environment variable.

    Not providers: two keys at one provider are two accounts with two quotas,
    and counting them as one would under-report the failover you actually have.
    """
    return {c[0] for c in entries}


def _by_source(entries: list[tuple[str, str, str, bool]]) -> dict[str, list]:
    """Free deployments grouped by the provider serving them.

    Paid deployments are left out: `paid` is already a group you ask for by
    name, and a source group that silently included it would turn "route to
    one provider" into "spend money" (`docs/0002` §5).
    """
    out: dict[str, list] = {}
    for e in entries:
        if not e[3]:
            continue
        parsed = parse_deployment_id(e[2])
        if parsed is None:
            continue
        out.setdefault(parsed[0], []).append(e)
    return out


def sources(env: dict | None = None) -> list[dict]:
    """What a source picker needs, and the cost of each choice.

    The cost is not decoration. `pool` is 48 deployments across 24 accounts;
    asking for one source can leave you with six behind a single account-wide
    daily cap, which is precisely the failure the multi-account design exists
    to escape (`docs/0033`). A picker that shows only the names is offering a
    downgrade without saying so, so every row carries what it gives up
    (`research/phase-10-3-model-selection.md` §6.5).

    Ordered widest-first, so the safe choice reads first.
    """
    entries = available(env)
    total = len([e for e in entries if e[3]])
    rows = []
    for name, mine in _by_source(entries).items():
        from .providers import BY_NAME
        prov = BY_NAME.get(name)
        n_acct = len({e[0] for e in mine})
        # Keys are not allowances. Gemini bills per Google project, so six
        # keys there are one quota -- and a picker that offered "6 accounts"
        # would be selling failover this source does not have.
        n_quota = n_acct if (prov is None or prov.quota_per_key) else min(n_acct, 1)
        rows.append({
            "source": name,
            "group": f"{SOURCE_PREFIX}{name}",
            "deployments": len(mine),
            "accounts": n_acct,
            "quotas": n_quota,
            "models": sorted({e[1] for e in mine}),
            "gives_up": total - len(mine),
        })
    rows.sort(key=lambda r: (-r["deployments"], r["source"]))
    return rows


def verified_providers(allow_paid: bool = False) -> tuple[set[str], dict]:
    """Which providers can actually complete a request right now.

    Authenticating is not the same as being allowed to infer: six Cerebras
    keys list models happily and every completion returns "Payment required".
    Those deployments sit in the pool failing ~11% of requests with an HTTP 402
    that litellm does not treat as retryable, so a pool built from credentials
    is worse than one built from what works (`docs/0034` §7).
    """
    from .probe import LIMITED, LIVE, check_inference
    from .providers import PROVIDERS

    ok, report = set(), {}
    for p in PROVIDERS:
        r = check_inference(p.name, allow_paid=allow_paid)
        if r is None:
            continue
        report[p.name] = r
        if r.status in (LIVE, LIMITED):
            ok.add(p.name)
    return ok, report


def build(env: dict | None = None, telemetry: str | Path | None = None,
          only: set[str] | None = None) -> str:
    """The proxy config, as YAML text. `only` restricts it to named providers."""
    entries = available(env)
    if only is not None:
        from .providers import BY_KEY
        entries = [e for e in entries
                   if BY_KEY[e[0].split("_API_KEY")[0] + "_API_KEY"].name in only]
        if not entries:
            raise SystemExit("no provider passed verification -- nothing to route to")
    if not entries:
        raise SystemExit(
            "no provider keys in the environment — nothing to route to.\n"
            "  set at least one, e.g. OPENROUTER_API_KEY")

    lines = [
        "# GENERATED by `agentctl proxy` from the keys in your environment.",
        "# Re-run it after exporting a new provider key; do not hand-edit.",
        "#",
        f"# {len(entries)} deployment(s) across {len(accounts(entries))} "
        f"account(s).",
        "",
        "model_list:",
    ]
    for env_var, model, short, is_free in entries:
        lines += [
            f"  - model_name: {POOL if is_free else PAID}",
            "    litellm_params:",
            f"      model: {model}",
            f"      api_key: os.environ/{env_var}",
            "    model_info:",
            f"      id: {short}",
            f"      free: {str(is_free).lower()}",
        ]

    # ── the source groups ───────────────────────────────────────────────
    #
    # Everything above is one group, `pool`, and that is what makes failover
    # work. These add a second, narrower way to ask: `pool-openrouter` routes
    # only to OpenRouter.
    #
    # It is a duplicated entry, not a second deployment -- the same key, the
    # same model, reachable under two names. The id carries `-only` so it
    # stays unique, because a duplicate id would send a fallback to whichever
    # entry litellm resolved first (`docs/0032`).
    #
    # The cost is real and belongs next to the choice: asking for one source
    # narrows the pool to that source's share, and an account-wide daily cap
    # then has nothing to fail over to. `agentctl models` prints what each
    # choice leaves before you make it (`research/phase-10-3` §6.5).
    by_source = _by_source(entries)
    if len(by_source) > 1:
        lines += ["", "  # ── source groups: narrower on purpose ──"]
        for source in sorted(by_source):
            group = f"{SOURCE_PREFIX}{source}"
            mine = by_source[source]
            lines += [
                f"  # {group}: {len(mine)} deployment(s), "
                f"{len({e[0] for e in mine})} account(s). "
                f"Choosing it gives up the other "
                f"{len(entries) - len(mine)}.",
            ]
            for env_var, model, short, is_free in mine:
                lines += [
                    f"  - model_name: {group}",
                    "    litellm_params:",
                    f"      model: {model}",
                    f"      api_key: os.environ/{env_var}",
                    "    model_info:",
                    f"      id: {short}-only",
                    f"      free: {str(is_free).lower()}",
                ]

    n_free = sum(1 for c in entries if c[3])
    lines += [
        "",
        "litellm_settings:",
        "  # Seam A. Cost attribution and turn affinity; it cannot block a",
        "  # request (`docs/0021`).",
        "  callbacks: agentctl_hook.proxy_handler_instance",
        "  # A provider config's supported params differ (`tools`,",
        "  # `parallel_tool_calls`, ...) and the pool changes providers on every",
        "  # retry. Without this an unsupported param 400s the whole request",
        "  # instead of being silently omitted for that one deployment",
        "  # (`research/phase-10-3-model-selection.md` §2.1 V7).",
        "  drop_params: true",
        "  # Repairs cross-provider tool-call history when a turn hops",
        "  # providers: drops an orphaned tool result, dedups a duplicated",
        "  # one, and synthesises a placeholder result for an orphaned tool",
        "  # call -- gates `sanitize_messages_for_tool_calling` (litellm",
        "  # 1.100.0). Schema/role translation and thought-signature handling",
        "  # already run unconditionally either way; this only turns on those",
        "  # three repairs (`research/phase-10-3-model-selection.md` §2.1 V6,",
        "  # `docs/0038` §5.1). The synthesised placeholder is content the",
        "  # agent never produced -- Seam A already pins a turn to one",
        "  # deployment to keep this rare (`kernel/hook.py::TurnAffinity`),",
        "  # but does not eliminate it.",
        "  modify_params: true",
        "",
        "router_settings:",
        "  # Every free deployment shares the model_name `pool`, and THAT is",
        "  # what produces failover: the router retries across deployments in",
        "  # one model group, cooling down whichever just failed. A key that",
        "  # hits its daily cap is skipped for `cooldown_time` while the other",
        f"  # {max(n_free - 1, 0)} keep serving.",
        "  routing_strategy: simple-shuffle",
        # Enough retries to leave a capped account and land on another one.
        f"  num_retries: {min(max(n_free - 1, 2), 5)}",
        "  allowed_fails: 1",
        "  cooldown_time: 300",
        "",
        "  # NO automatic fallback to `paid`. `fallbacks` maps between model",
        "  # GROUPS, not deployment ids -- litellm's own example is",
        "  # [{\"azure-gpt-3.5-turbo\": \"openai-gpt-3.5-turbo\"}] -- and an",
        "  # earlier version of this file pointed it at model_info ids, which",
        "  # resolve to nothing. It is left out rather than corrected because",
        "  # `docs/0002` §5 says never silently spend: paid is a group you ask",
        "  # for by name, not one you arrive at by failing.",
    ]
    if any(not c[3] for c in entries):
        lines += [
            "  #   to use it deliberately:  --model openai/paid",
        ]
    lines.append("")
    text = "\n".join(l for l in lines if l is not None)

    # Parse our own output before handing it over. The first version of this
    # function emitted `["a" "b"]` -- a missing comma -- and returned it
    # happily; the proxy would have failed to start with a YAML error pointing
    # at a file the user never wrote. A generator that cannot detect its own
    # malformed output is the same shape as a guard that cannot fail
    # (`docs/0028` §5).
    _validate(text)
    return text


def _validate(text: str) -> None:
    import yaml

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise AssertionError(f"generated an invalid proxy config: {e}") from e

    assert isinstance(doc, dict), "config is not a mapping"
    models = doc.get("model_list") or []
    assert models, "config has no model_list"
    names = {m["model_name"] for m in models}
    # Free deployments must share ONE name. That shared model group is where
    # failover actually comes from: the router retries across the group and
    # cools down whichever deployment just failed.
    unexpected = {n for n in names
                  if n not in (POOL, PAID) and not n.startswith(SOURCE_PREFIX)}
    assert not unexpected, f"unexpected model groups: {unexpected}"
    assert POOL in names or names == {PAID}, "no free pool was built"
    for m in models:
        assert m["litellm_params"].get("api_key", "").startswith("os.environ/"), \
            "a key was inlined instead of referenced from the environment"

    # Deployment ids are what `fallbacks` points at. A duplicate would send a
    # failover to whichever entry litellm resolved first -- silently the wrong
    # provider. Two providers abbreviating to the same prefix caused exactly
    # this once (`docs/0032`).
    ids = [m["model_info"]["id"] for m in models]
    assert len(set(ids)) == len(ids), f"duplicate deployment ids: {ids}"
    # If fallbacks are ever reintroduced they must name model GROUPS. An
    # earlier version pointed them at `model_info.id` values, which resolve to
    # nothing -- litellm's own example maps one model_name to another.
    groups = {m["model_name"] for m in models}
    for entry in (doc.get("router_settings") or {}).get("fallbacks") or []:
        assert isinstance(entry, dict), f"fallbacks is malformed: {entry!r}"
        for source, targets in entry.items():
            assert source in groups, \
                f"fallback source {source!r} is not a model group"
            for t in ([targets] if isinstance(targets, str) else targets):
                assert t in groups, (
                    f"fallback target {t!r} is not a model group -- litellm "
                    f"maps groups, not deployment ids")


HOOK_MODULE = '''"""Seam A for the proxy. Loaded by `litellm_settings.callbacks`.

Generated by `agentctl proxy`. The hook records cost telemetry and stamps turn
affinity; it never blocks a request -- effects are gated at Seams B and C
inside the agent, not here (`docs/0008` §3).
"""
import os

from agentctl.adapters.litellm.hook import AgentctlHook

proxy_handler_instance = AgentctlHook(
    telemetry_path=os.environ.get("AGENTCTL_TELEMETRY", "hook_telemetry.json"))
'''


def write(out_dir: str | Path = ".", env: dict | None = None,
          only: set[str] | None = None) -> tuple[Path, Path]:
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    cfg = d / "proxy_config.yaml"
    hook = d / "agentctl_hook.py"
    cfg.write_text(build(env, only=only), encoding="utf-8")
    hook.write_text(HOOK_MODULE, encoding="utf-8")
    write_start_scripts(d, Path(__file__).resolve().parent.parent.parent)
    return cfg, hook


# The proxy prints a banner containing box-drawing characters. On Windows a
# redirected stdout defaults to cp1252, `click.echo` raises UnicodeEncodeError
# inside the startup event, and the server exits with "Application startup
# failed" -- which looks like a config error and is an encoding one. Fifth
# occurrence in this project; `docs/0012` §6 already required this and the
# generated output did not do it (`docs/0034` §8).
START_SH = """#!/usr/bin/env bash
# Generated by `agentctl proxy`. Start the pool.
set -euo pipefail
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export OPENHANDS_SUPPRESS_BANNER=1
export PYTHONPATH="{root}${{PYTHONPATH:+:$PYTHONPATH}}"
exec "{litellm}" --config "$(dirname "$0")/proxy_config.yaml" --port "${{1:-4000}}"
"""

START_PS1 = r"""# Generated by `agentctl proxy`. Start the pool.
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:OPENHANDS_SUPPRESS_BANNER = "1"
$env:PYTHONPATH = "{root};$env:PYTHONPATH"
& "{litellm}" --config "$PSScriptRoot\proxy_config.yaml" --port $(if ($args[0]) {{$args[0]}} else {{4000}})
"""


def _litellm_executable() -> str:
    """The litellm CLI belonging to THIS interpreter.

    A bare `litellm` only resolves when the virtualenv happens to be active,
    and a launcher that requires you to have activated something is a launcher
    that fails the first time you use it — which this one did.
    """
    import shutil
    import sys

    scripts = Path(sys.executable).parent
    for name in ("litellm.exe", "litellm"):
        if (candidate := scripts / name).exists():
            return str(candidate)
    return shutil.which("litellm") or "litellm"


def write_start_scripts(out_dir: str | Path, root: str | Path) -> list[Path]:
    """Runnable launchers, so the encoding trap cannot be stepped in."""
    d = Path(out_dir)
    exe = _litellm_executable().replace("\\", "/")
    made = []
    for name, body in (("start.sh", START_SH), ("start.ps1", START_PS1)):
        p = d / name
        p.write_text(body.format(root=str(root).replace("\\", "/"), litellm=exe),
                     encoding="utf-8", newline="\n")
        made.append(p)
    return made
