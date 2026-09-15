r"""One file holding every provider key, and the guards that keep it private.

    agentctl keys --init     write a template listing every provider
    agentctl keys            show which are set, and where to get the rest

## The file never reaches me, and never reaches git

Values are read from disk into the process environment and **never printed,
logged, echoed in an error, or shown by any command here** — `agentctl keys`
reports `set (73 chars)`, never the key. That is the same rule the runner
already follows for `OPENROUTER_API_KEY`.

The larger risk is not display, it is `git add -A`. A file of live API keys
committed to a public repository is the single worst outcome this project can
produce, so there are three independent guards:

1. `--init` writes `.gitignore` entries before it writes the file
2. `load()` refuses to proceed if the file is **tracked by git**, because at
   that point ignoring it does nothing
3. `check_not_tracked()` is called by `doctor`, so the warning appears even
   when nobody is thinking about keys

Guard 2 is the one that matters. A `.gitignore` entry added *after* a file is
already tracked has no effect at all, and that is exactly how keys get
published — the ignore rule is there, everybody assumes it works, and the file
was staged before it existed.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .providers import PROVIDERS

# Outside any repository, so no `git add -A` anywhere can reach it. This is
# the default for `--init` because a gitignore rule is a promise and a
# different directory is a fact.
HOME_PATH = Path.home() / ".agentctl" / "keys.env"
LOCAL_PATH = Path("keys.env")

# Anything matching these is a secret file we never want in a commit.
GITIGNORE_LINES = ("keys.env", ".env", "*.env", "!*.env.template")


def search_paths() -> list[Path]:
    """Where a keys file may live, nearest first.

    `AGENTCTL_KEYS` wins, then a project-local file, then the home file. A
    project-local one is supported because people expect it, and warned about
    because it sits inside a repository.
    """
    out = []
    if (explicit := os.environ.get("AGENTCTL_KEYS")):
        out.append(Path(explicit))
    out += [LOCAL_PATH, HOME_PATH]
    return out


def resolve() -> Path | None:
    """The keys file actually in use, or None."""
    for p in search_paths():
        if p.exists():
            return p
    return None


# Back-compat for callers that pass nothing.
DEFAULT_PATH = LOCAL_PATH

_LINE = re.compile(r"""^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$""")


class KeysAreTracked(RuntimeError):
    """The keys file is in git. Ignoring it now changes nothing."""


# ── reading ────────────────────────────────────────────────────────────
def parse(text: str) -> dict[str, str]:
    """A minimal .env parser. No dependency, no surprises.

    Handles `KEY=value`, `export KEY=value`, quotes, blank lines and `#`
    comments. Deliberately does not do variable interpolation: a key is a
    literal, and `$` inside one is a character, not a reference.
    """
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _LINE.match(line)
        if not m:
            continue
        name, value = m.group(1), m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #")[0].strip()
        if value:
            out[name] = value
    return out


def _git(path: Path, *args: str) -> subprocess.CompletedProcess | None:
    """Run git with the keys file's own directory as cwd.

    The directory matters. `~/.agentctl/keys.env` may sit inside a repository
    that has nothing to do with this project — on the machine this was written
    on, the home directory itself is a repo with an unrelated remote. Asking
    git from the wrong cwd answers about the wrong repository.
    """
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              cwd=str(path.parent if path.parent.exists() else "."))
    except Exception:                                   # noqa: BLE001
        return None                                     # no git: not our problem


def enclosing_repo(path: str | Path) -> Path | None:
    """The repository the keys file lives inside, if any."""
    p = Path(path)
    r = _git(p, "rev-parse", "--show-toplevel")
    if r is None or r.returncode != 0:
        return None
    return Path(r.stdout.strip()) if r.stdout.strip() else None


def check_not_tracked(path: str | Path = DEFAULT_PATH) -> str | None:
    """Is the keys file exposed to git? Returns a warning, or None.

    Two distinct states, and the second is the one worth catching, because it
    is the moment *before* the accident rather than after:

    * **tracked** — already committed. The keys must be assumed public.
    * **inside a repo and not ignored** — one `git add -A` away from that.
    """
    p = Path(path)
    if not p.exists():
        return None

    r = _git(p, "ls-files", "--error-unmatch", str(p))
    if r is None:
        return None
    if r.returncode == 0:
        return (f"{p} is TRACKED BY GIT. A .gitignore entry does nothing once a "
                f"file is tracked. Run:  git rm --cached {p}  and rotate every "
                f"key in it — assume they are public.")

    repo = enclosing_repo(p)
    if repo is None:
        return None                                     # not in a repo: safe
    ig = _git(p, "check-ignore", "-q", str(p))
    if ig is not None and ig.returncode != 0:
        return (f"{p} sits inside the git repository at {repo} and is NOT "
                f"ignored there. One `git add -A` would stage your keys. "
                f"Fix:  echo '{p.name}' >> {repo / '.gitignore'}")
    return None


def load(path: str | Path = DEFAULT_PATH, *, override: bool = False) -> list[str]:
    """Load keys into `os.environ`. Returns the NAMES set, never the values.

    An existing environment variable wins unless `override=True`: something
    already exported is a deliberate act, and a file should not silently
    replace it.
    """
    p = Path(path)
    if not p.exists():
        return []

    if (warning := check_not_tracked(p)):
        raise KeysAreTracked(warning)

    loaded = []
    for name, value in parse(p.read_text(encoding="utf-8")).items():
        if override or not os.environ.get(name):
            os.environ[name] = value
            loaded.append(name)
    return loaded


def load_all(override: bool = False) -> tuple[Path | None, list[str]]:
    """Load from the first keys file that exists. Returns (path, NAMES)."""
    p = resolve()
    return (p, load(p, override=override)) if p else (None, [])


def load_quietly(path: str | Path | None = None) -> list[str]:
    """`load`, but a tracked-file refusal becomes a warning on stderr.

    Used on the CLI's startup path. Refusing to run at all would be the safer
    reflex and the wrong one here: the key is already exposed, and preventing
    the user from using their own tool does not un-expose it. Being loud does.
    """
    import sys

    path = path or resolve()
    if path is None:
        return []
    try:
        return load(path)
    except KeysAreTracked as e:
        print(f"\n  !! {e}\n", file=sys.stderr)
        try:
            return [n for n, v in parse(Path(path).read_text(encoding="utf-8")).items()
                    if not os.environ.get(n) and not os.environ.__setitem__(n, v)]
        except Exception:                               # noqa: BLE001
            return []


# ── writing the template ───────────────────────────────────────────────
def template(extra_slots: int = 2) -> str:
    """The file to paste keys into. Multiple accounts per provider.

    `extra_slots` commented lines per provider show the naming convention, so
    adding a second account is uncommenting a line rather than reading docs.
    """
    lines = [
        "# ════════════════════════════════════════════════════════════════",
        "#  agentctl provider keys        NEVER COMMIT THIS FILE",
        "# ════════════════════════════════════════════════════════════════",
        "#",
        "# Paste keys after the `=`. No quotes needed, no spaces around it.",
        "# Blank lines are fine -- leave anything you do not have empty.",
        "#",
        "# Values are read into the environment and NEVER printed, logged, or",
        "# shown by any command. `agentctl keys` says `set (73 chars)`.",
        "#",
        "# ── MULTIPLE ACCOUNTS PER PROVIDER ──────────────────────────────",
        "#",
        "# This is the point of the file. A free-tier cap is usually per",
        "# ACCOUNT, so a second key at the SAME provider buys a second quota:",
        "#",
        "#     OPENROUTER_API_KEY=sk-or-v1-....      <- first account",
        "#     OPENROUTER_API_KEY_2=sk-or-v1-....    <- second, separate quota",
        "#     OPENROUTER_API_KEY_WORK=sk-or-v1-...  <- any label works",
        "#",
        "# Any suffix after the name is accepted: _2, _3, _ALT, _WORK. Each",
        "# becomes its own deployment in the pool, so when one account hits a",
        "# daily cap the others keep serving (`docs/0033`).",
        "#",
        "# Two accounts at ONE provider beats five models at one account.",
        "# Two accounts at DIFFERENT providers is better still -- it survives",
        "# the provider itself going down.",
        "#",
        "# ── AFTER EDITING ───────────────────────────────────────────────",
        "#",
        "#     agentctl keys     what is set now",
        "#     agentctl dash     whether failover is actually ready",
        "#     agentctl proxy    rebuild the pool from these keys",
        "#",
        "",
    ]
    for p in PROVIDERS:
        lines.append("# " + "─" * 62)
        lines.append(f"# {p.name.upper()}{'' if p.free_tier else '   (PAID -- costs money)'}")
        lines.append(f"#   get a key:  {p.console}")
        for i, step in enumerate(p.steps, 1):
            lines.append(f"#     {i}. {step}")
        if p.note:
            # Label the first wrapped line, indent the continuations. The
            # first version compared chunks with `is`, which is identity on
            # strings and was never true, so no note was ever labelled.
            for i, chunk in enumerate(_wrap(p.note, 66)):
                lines.append(f"#   note: {chunk}" if i == 0
                             else f"#         {chunk}")
        lines.append("")
        lines.append(f"{p.key}=")
        for n in range(2, extra_slots + 2):
            lines.append(f"# {p.key}_{n}=")
        lines.append("")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    import textwrap
    return textwrap.wrap(text, width) or [text]


def write_template(path: str | Path | None = None,
                   gitignore: str | Path = ".gitignore") -> tuple[Path, bool]:
    """Write the template, ignoring it FIRST. Never overwrites a filled file.

    Defaults to `~/.agentctl/keys.env`, outside any repository. A gitignore
    entry is a promise that has to be kept by every future `git add`; a
    different directory is a fact that holds regardless.
    """
    p = Path(path) if path else HOME_PATH
    p.parent.mkdir(parents=True, exist_ok=True)

    # Ignore rules FIRST, and in the repository that actually contains the
    # file. The first version wrote them into the current project's
    # `.gitignore` while placing the file under `~/.agentctl` — which on this
    # machine is inside a *different* repo, leaving the file unprotected in the
    # only repo that could commit it (`docs/0033` §5).
    for target in {Path(gitignore), *( [repo / ".gitignore"]
                                       if (repo := enclosing_repo(p)) else [] )}:
        try:
            ensure_ignored(target, name=p.name)
        except Exception:                               # noqa: BLE001
            pass                                        # not a repo: fine
    if p.exists():
        return p, False
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(template(), encoding="utf-8")
    try:
        os.chmod(p, 0o600)                              # no-op on Windows
    except Exception:                                   # noqa: BLE001
        pass
    return p, True


def ensure_ignored(gitignore: str | Path = ".gitignore",
                   name: str | None = None) -> bool:
    """Add the ignore rules if absent. Called BEFORE the file is created.

    `name` adds the specific filename too, so a keys file with an unusual name
    is covered as well as the generic `*.env` patterns.
    """
    g = Path(gitignore)
    have = g.read_text(encoding="utf-8") if g.exists() else ""
    wanted = list(GITIGNORE_LINES) + ([name] if name else [])
    need = [l for l in dict.fromkeys(wanted) if l not in have.splitlines()]
    if not need:
        return False
    g.parent.mkdir(parents=True, exist_ok=True)
    with g.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n# Provider API keys. Written by `agentctl keys --init`.\n")
        fh.write("\n".join(need) + "\n")
    return True


# ── blocking a commit that contains a real key ─────────────────────────
def scan_text(text: str, values: set[str] | None = None) -> list[str]:
    """Which of YOUR keys appear in `text`. Returns env names, never values.

    Compares against the credentials you actually hold rather than against a
    shape. A regex for `sk-[A-Za-z0-9]{20,}` flags every placeholder in every
    test file, and a check that cries wolf is one people learn to ignore --
    which is worse than no check, because it is mistaken for protection.
    """
    path = resolve()
    if values is None:
        if path is None:
            return []
        values = set()
        pairs = parse(path.read_text(encoding="utf-8"))
    else:
        pairs = {}
    names = []
    for name, value in (pairs.items() if pairs else []):
        # Short values are not credentials and would match everywhere.
        if value and len(value) >= 16 and value in text:
            names.append(name)
    for value in values:
        if value and len(value) >= 16 and value in text:
            names.append("<supplied>")
    return names


def scan_staged() -> list[str]:
    """Real keys present in what git is about to commit."""
    r = subprocess.run(["git", "diff", "--cached"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return []
    return scan_text(r.stdout)


PRE_COMMIT_HOOK = """#!/bin/sh
# Installed by `agentctl keys --install-hook`.
# Refuses any commit containing a credential from your keys file.
exec "{python}" -c "
import sys
sys.path.insert(0, r'{root}')
from agentctl.control.keys import scan_staged
hits = scan_staged()
if hits:
    print('COMMIT BLOCKED: these keys appear in the staged changes:')
    for h in sorted(set(hits)):
        print('   ', h)
    print('Remove them, then commit. If one was already pushed, rotate it.')
    raise SystemExit(1)
"
"""


def install_hook(repo: str | Path = ".") -> Path:
    """Install the pre-commit guard in `repo`."""
    import sys

    hooks = Path(repo) / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    p = hooks / "pre-commit"
    p.write_text(
        PRE_COMMIT_HOOK.format(python=sys.executable.replace("\\", "/"),
                               root=str(Path(__file__).resolve().parent.parent.parent)),
        encoding="utf-8", newline="\n")
    try:
        os.chmod(p, 0o755)
    except Exception:                                   # noqa: BLE001
        pass
    return p
