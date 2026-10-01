"""Where `agentctl run` gets its defaults. `docs/0043` Phase 2.

Phase 0 (`docs/0044`) needed `--workspace`, `--model`, `--base-url` and
`--ledger` on almost every command, and the built-in model was one OpenRouter
id: a user holding only a Gemini or Anthropic key was handed a default that
could not work.

Precedence, highest first:

    a flag on the command line
    an environment variable     AGENTCTL_MODEL, AGENTCTL_BASE_URL
    ~/.agentctl/config.toml     written by `agentctl init`, editable
    derived                     the default model of the first provider you
                                hold a key for, free tiers first

`resolve()` reports which of these each value came from, because a default
nobody can trace is the confidently-wrong shape `docs/0039` is about.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

#: Keys this file owns. Anything else in config.toml is kept but not read.
KEYS = ("model", "base_url")
ENV = {"model": "AGENTCTL_MODEL", "base_url": "AGENTCTL_BASE_URL"}


def path() -> Path:
    """`~/.agentctl/config.toml`, or `AGENTCTL_CONFIG` when set."""
    if (p := os.environ.get("AGENTCTL_CONFIG")):
        return Path(p)
    return Path.home() / ".agentctl" / "config.toml"


def load(p: Path | None = None) -> dict:
    p = p or path()
    if not p.exists():
        return {}
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        # A broken config must not silently fall back to a different model.
        raise SystemExit(f"{p} is not valid TOML: {e}\n"
                         f"  fix it, or delete it and run `agentctl init`")


def write(values: dict, p: Path | None = None, note: str = "") -> Path:
    """Write the keys this module owns. Values are plain strings."""
    p = p or path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Written by `agentctl init`. Edit freely; a flag or an",
             "# AGENTCTL_* environment variable still wins over anything here."]
    if note:
        lines += [f"# {line}" for line in note.splitlines()]
    lines.append("")
    for k in KEYS:
        if values.get(k):
            v = str(values[k]).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{v}"')
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def derived_model() -> str | None:
    """The default model of the first provider holding a key, free first.

    The registry's first model per provider is the one `init` would try
    first. Without `init` it is unverified -- `resolve` says so.
    """
    from agentctl.control.providers import configured

    for p in configured():
        if p.default_model:
            return p.default_model
    return None


@dataclass(frozen=True)
class Setting:
    value: str | None
    source: str                 # "flag" | "env AGENTCTL_MODEL" | "config" | ...


def resolve(name: str, flag: str | None, cfg: dict | None = None) -> Setting:
    if flag:
        return Setting(flag, "flag")
    if (v := os.environ.get(ENV[name])):
        return Setting(v, f"env {ENV[name]}")
    cfg = load() if cfg is None else cfg
    if cfg.get(name):
        return Setting(str(cfg[name]), f"config {path()}")
    if name == "model" and (m := derived_model()):
        return Setting(m, "derived from your keys (unverified: `agentctl init` checks it)")
    return Setting(None, "unset")
