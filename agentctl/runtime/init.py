"""`agentctl init`: from one key to a working default, in one command.

`docs/0043` Phase 2. Phase 0 (`docs/0044`) took a new user nine commands and
two false "it will not work" verdicts to reach a first task. This is the
middle of the three commands the plan promises:

    pip install ...            (once)
    agentctl init              this
    agentctl run "<task>"      in any git repository

What it does, in order, and nothing else:

1. **Find a key.** One already in the environment or a keys file is used. With
   none, it asks which provider and reads the key without echoing it, into
   `~/.agentctl/keys.env` -- outside every repository, ignored first.
2. **Prove it.** One completion, through the same check as `keys --check`,
   which tries each registry model past a dead one (`docs/0044` N6). The
   model that ANSWERED is the one recorded: a default chosen by a completion,
   not by a list.
3. **Record it** in `~/.agentctl/config.toml`, which `run` reads.

A paid provider is not called unless asked (`docs/0002` §5: never silently
spend), and then it costs one four-token completion.
"""
from __future__ import annotations

import getpass
import os
import sys

from agentctl.runtime import config


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _choose(interactive: bool):
    """A provider the user picks, free tiers first. None if they do not."""
    from agentctl.control.providers import PROVIDERS

    order = sorted(PROVIDERS, key=lambda p: (not p.free_tier, PROVIDERS.index(p)))
    print("  No provider key found. Pick one to start with -- one is enough:\n")
    for i, p in enumerate(order, 1):
        print(f"    {i}. {p.name:<11} {'free tier' if p.free_tier else 'PAID'}"
              f"   {p.console}")
    print()
    if not interactive:
        return None
    answer = _ask(f"  provider [1-{len(order)}, default 1]: ") or "1"
    try:
        return order[int(answer) - 1]
    except (ValueError, IndexError):
        from agentctl.control.providers import BY_NAME
        return BY_NAME.get(answer.lower())


def _store_key(p, value: str) -> None:
    from agentctl.control.keys import HOME_PATH, set_value

    path = set_value(HOME_PATH, p.key, value)
    os.environ[p.key] = value
    print(f"  saved         {p.key} -> {path}  (never printed, outside any repo)")


def run_init(provider: str | None = None, model: str | None = None,
             verify: bool = True, key_stdin: bool = False,
             check_paid: bool = False, interactive: bool | None = None) -> int:
    from agentctl.control.providers import BY_NAME, configured

    if interactive is None:
        interactive = sys.stdin.isatty()
    print("agentctl init\n")

    # ── 1. a key ────────────────────────────────────────────────────────
    if provider:
        p = BY_NAME.get(provider.lower())
        if p is None:
            print(f"  no provider called {provider!r}. Known: "
                  f"{', '.join(BY_NAME)}")
            return 2
    else:
        have = configured()
        p = have[0] if have else _choose(interactive and not key_stdin)

    if p is None:
        print("  Non-interactive, and no key in the environment. Either:")
        print("    export OPENROUTER_API_KEY=...        then  agentctl init")
        print("    agentctl init --provider openrouter --key-stdin < keyfile")
        return 2

    if not p.configured:
        print(f"  {p.name}: create a key at {p.console}")
        for step in p.steps:
            print(f"    - {step}")
        if key_stdin:
            value = sys.stdin.readline().strip()
        elif interactive:
            value = getpass.getpass(f"  paste your {p.key} (not shown): ").strip()
        else:
            value = ""
        if not value:
            print(f"\n  no key given. Set {p.key} and run `agentctl init` again.")
            return 2
        _store_key(p, value)
    else:
        print(f"  key           {p.key} (already set)")

    # ── 2. prove it ────────────────────────────────────────────────────
    chosen, how = model or p.default_model, "registry default, not checked"
    if model:
        how = "given with --model"
    elif not verify:
        how = "registry default; --no-verify, so not checked"
    elif not p.free_tier and not check_paid:
        how = ("registry default; not checked -- a paid provider is called "
               "only with --check-paid (one 4-token completion)")
    else:
        from agentctl.control.probe import LIMITED, LIVE, check_inference

        print(f"  checking      one completion against {p.name} ...")
        r = check_inference(p.name, allow_paid=check_paid)
        if r is not None and r.status == LIVE and r.model:
            chosen, how = f"{p.prefix}{r.model}", "answered a completion just now"
        elif r is not None and r.status == LIMITED:
            how = ("the key works but is rate limited right now; registry "
                   "default recorded, unchecked")
        else:
            print(f"  !! {p.name} cannot serve a request: "
                  f"{r.detail if r else 'no model to check'}")
            print(f"     the key is saved; nothing else was changed. Check it at "
                  f"{p.console}, then run `agentctl init` again.")
            return 1

    # ── 3. record it ───────────────────────────────────────────────────
    cfg = config.load()
    cfg["model"] = chosen
    path = config.write(cfg, note=f"model: {how}")
    print(f"  model         {chosen}")
    print(f"                ({how})")
    print(f"  config        {path}")
    print()
    print("  Ready. In any git repository:")
    print('    agentctl run "describe what this repository does"')
    return 0
