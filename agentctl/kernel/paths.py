r"""Which files would this call write, and do any of them escape the workspace?

Separate from `classify.py` on purpose. The classifier answers *what kind of
effect is this* -- the question the ledger needs to decide whether replaying it
is safe. This module answers *where does it land*, which is a question about
authority, not about replay.

`docs/0025` §4 draws that line:

    the gate               stops an effect happening TWICE
    confirmation           stops an effect happening AT ALL without a human

Escalating `write_file(path="~/.ssh/authorized_keys")` to `DESTRUCTIVE` would
have collapsed the two -- the ledger would then treat an ordinary idempotent
write as unrecoverable, and a perfectly safe replay would start failing closed.
`cp a.txt /tmp/b.txt` is not destructive. It is merely none of the agent's
business. So the effect class stays honest and the *authorization* layer asks.

## What counts as a write target

Only things that are unambiguously write destinations:

* the declared path argument of a structured tool (`write_file`, `edit`, ...)
* a shell redirect target -- `> f`, `>> f`, `tee f`
* arguments to commands whose entire purpose is to mutate a named file

Read paths are deliberately NOT collected. `grep secret /etc/shadow` reads
outside the workspace, which is a real concern and a different one
(exfiltration, not authority over the machine); pretending this module covers
it would be worse than not covering it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePath

from .ledger.models import ToolCall

# Arguments that name a file, for structured (non-shell) tools.
PATH_ARGS = ("path", "file_path", "filename", "file", "dest", "destination")

# `> f`, `>> f`, `2> f` -- but not `2>&1`, which writes no file.
_REDIRECT = re.compile(r"(?<![>&\-])>{1,2}(?![>&])\s*([^\s;&|<>]+)")

# Commands whose named arguments ARE the thing being changed.
_FILE_MUTATORS = re.compile(
    r"^\s*(?:sudo\s+)?(rm|mv|cp|touch|chmod|chown|shred|truncate|tee|ln|mkdir"
    r"|rmdir|install)\b(.*)$"
)

# `cp`, `mv` and friends take sources then ONE destination, and only the
# destination is written. Collecting every operand would flag
# `cp /etc/hosts ./local` -- a read from outside, copied in -- as an
# unauthorised write, and a prompt that is wrong is worse than no prompt (§5).
_LAST_OPERAND_ONLY = {"cp", "mv", "ln", "install"}

# Not paths: flags, operators, and the shell's own punctuation.
_NOT_A_PATH = re.compile(r"^(-|\d+$|&|\||;|<|>)")


def write_targets(call: ToolCall, *, arg_key: str = "command") -> list[str]:
    """Every path this call would write to. Best effort, biased to over-report.

    A path reported here that is not really written costs one confirmation
    prompt. A path missed here is an unauthorised write, so the bias is
    deliberate -- but see the module docstring for what is out of scope.
    """
    out: list[str] = []

    for name in PATH_ARGS:
        if (v := call.args.get(name)) and isinstance(v, str):
            out.append(v)

    if isinstance(command := call.args.get(arg_key), str):
        out.extend(_shell_write_targets(command))

    seen: set[str] = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def _shell_write_targets(command: str) -> list[str]:
    """Redirect destinations and the operands of file-mutating commands."""
    from .classify import Classifier          # same layer, no cycle at import

    out: list[str] = []
    for segment in Classifier._segments(command):
        out.extend(_REDIRECT.findall(segment))
        if m := _FILE_MUTATORS.match(segment):
            operands = [
                t for token in m.group(2).split()
                if (t := token.strip("'\"")) and not _NOT_A_PATH.match(t)
            ]
            if m.group(1) in _LAST_OPERAND_ONLY:
                operands = operands[-1:]
            out.extend(operands)
    return out


def escapes(target: str, root: str | Path) -> bool:
    """Does `target` resolve outside `root`?

    Resolution is lexical, and that is a deliberate choice: `Path.resolve()`
    follows symlinks, so a link planted inside the workspace would resolve
    outside it and be reported -- correct -- but a link planted OUTSIDE could
    resolve back in and be waved through. Lexical normalisation cannot be
    tricked that way, at the cost of treating a benign symlink as an escape.

    `~` is expanded first. Without that, `~/.bashrc` is a relative path and
    looks like it sits safely inside the workspace, which is precisely the case
    that prompted this module.
    """
    root_p = PurePath(os.path.abspath(str(root)))
    expanded = os.path.expanduser(os.path.expandvars(target))

    if not os.path.isabs(expanded):
        expanded = os.path.join(str(root_p), expanded)

    resolved = PurePath(os.path.normpath(expanded))
    try:
        resolved.relative_to(root_p)
        return False
    except ValueError:
        return True


def escaping_writes(call: ToolCall, root: str | Path | None) -> list[str]:
    """Write targets that land outside `root`. Empty when `root` is None."""
    if root is None:
        return []
    return [t for t in write_targets(call) if escapes(t, root)]
