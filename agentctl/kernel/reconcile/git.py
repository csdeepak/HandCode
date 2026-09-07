"""Git reconciliation probe.

The headline case: an agent runs `git commit`, the process dies before the
observation is recorded, and on resume we must decide whether to run it again.

Method — fingerprint, not marker:

    capture()   HEAD sha + a hash of `git status --porcelain`
    probe()     HEAD moved?            -> LANDED
                HEAD same, tree same?  -> DID_NOT_LAND
                anything else          -> INCONCLUSIVE

No command mutation, so this works at Seam B (`docs/0016` §4).
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from .base import DID_NOT_LAND, INCONCLUSIVE, LANDED

#: Commands that move HEAD. `git push` is deliberately absent — it is EXTERNAL,
#: and a local probe cannot see whether the remote accepted it.
_MOVES_HEAD = ("commit", "merge", "cherry-pick", "revert", "am", "rebase")

NO_COMMITS = "__NO_COMMITS__"


class GitProbe:
    name = "git"

    def __init__(self, repo_root: str | Path | None = None, timeout_s: float = 10.0):
        self.repo_root = Path(repo_root) if repo_root else None
        self.timeout_s = timeout_s

    # ── selection ──────────────────────────────────────────────────────
    def handles(self, call) -> bool:
        if shutil.which("git") is None:
            return False
        # A dedicated tool ("commit", "git_commit") carries no command string
        # to sniff, so match on the tool name too.
        name = (call.tool_name or "").lower()
        if any(verb in name for verb in _MOVES_HEAD):
            return True
        text = self._command_text(call)
        if "git " not in text:
            return False
        return any(f"git {verb}" in text for verb in _MOVES_HEAD)

    # ── before ─────────────────────────────────────────────────────────
    def capture(self, call) -> dict | None:
        try:
            root = self._root(call)
            if root is None:
                return None
            head = self._head(root)
            if head is None:
                return None                     # not a git repo
            return {
                "probe": self.name,
                "root": str(root),
                # The repo we actually attached to. A workspace nested inside a
                # larger repo silently resolves to the ANCESTOR, whose HEAD
                # moves for reasons that have nothing to do with this agent.
                "toplevel": self._git(root, "rev-parse", "--show-toplevel"),
                "head": head,
                "tree": self._tree_hash(root),
            }
        except Exception:                               # noqa: BLE001
            return None

    # ── after a crash ──────────────────────────────────────────────────
    def probe(self, call, record) -> str:
        try:
            pre = _pre(record)
            if not pre or pre.get("probe") != self.name:
                return INCONCLUSIVE

            root = Path(pre["root"])
            head_now = self._head(root)
            if head_now is None:
                return INCONCLUSIVE

            # A different repo than the one we fingerprinted: say nothing.
            if self._git(root, "rev-parse", "--show-toplevel") != pre.get("toplevel"):
                return INCONCLUSIVE

            if head_now != pre.get("head"):
                # HEAD moved during the crash window. With a single writer in
                # the workspace, that was our commit.
                return LANDED

            tree_now = self._tree_hash(root)
            if tree_now is not None and tree_now == pre.get("tree"):
                # HEAD unchanged AND the working tree is exactly as we left it:
                # nothing was committed and nothing else happened either.
                return DID_NOT_LAND

            # HEAD unchanged but the tree moved. Something happened that was
            # not a commit; we cannot attribute it. Do not guess.
            return INCONCLUSIVE
        except Exception:                               # noqa: BLE001
            return INCONCLUSIVE

    # ── internals ──────────────────────────────────────────────────────
    def _root(self, call) -> Path | None:
        for key in ("cwd", "working_dir", "path", "repo"):
            if (v := call.args.get(key)):
                p = Path(str(v))
                if p.is_dir():
                    return p
        return self.repo_root

    def _git(self, root: Path, *args: str) -> str | None:
        try:
            r = subprocess.run(
                ["git", *args], cwd=str(root), capture_output=True,
                text=True, timeout=self.timeout_s,
            )
        except Exception:                               # noqa: BLE001
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    def _head(self, root: Path) -> str | None:
        if self._git(root, "rev-parse", "--is-inside-work-tree") != "true":
            return None
        head = self._git(root, "rev-parse", "HEAD")
        # A repo with no commits yet has no HEAD; that is a valid state.
        return head if head else NO_COMMITS

    def _tree_hash(self, root: Path) -> str | None:
        status = self._git(root, "status", "--porcelain=v1", "--untracked-files=all")
        if status is None:
            return None
        return hashlib.sha256(status.encode()).hexdigest()

    @staticmethod
    def _command_text(call) -> str:
        if "command" in call.args:
            return str(call.args["command"])
        return " ".join(str(v) for v in call.args.values())


def _pre(record) -> dict | None:
    import json
    raw = getattr(record, "pre_state", None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:                                   # noqa: BLE001
        return None
