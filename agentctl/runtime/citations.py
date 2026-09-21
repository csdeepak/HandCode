r"""Check a scout's citation before believing it.

`docs/0039` §7, fifteenth entry. The first live fan-out returned:

    "The lease TTL is enforced in hook.py ... 900.0 seconds ...
     cited at hook.py:13"

The lease TTL is `store.py:63`, 60.0 seconds. `hook.py`'s 900.0 is the
turn-affinity pin, a different timer — and `hook.py:13` is prose in a
docstring about `tool_call_id`. Nothing malfunctioned: the scout read eight
files, found *a* `ttl_s`, and reported it as *the* one, with a citation, in
the format its prompt demanded.

**Citation discipline did not help, because a citation is only as good as the
check nobody performed.** This is that check.

## What can and cannot be verified here

Mechanically certain:

* the file exists in the workspace,
* the line number is within it,
* what that line actually says.

Mechanically useful, and what caught the live failure: **does the value the
claim asserts appear where the claim says it does?** `900.0` is 81 lines from
`hook.py:13`, and saying so is enough to stop a reader believing it.

Not verifiable here, and not attempted: whether the claim is *true*. A line
can exist, contain the token, and still not support the sentence wrapped
around it. This narrows what must be read by hand; it does not replace
reading.

**A citation that fails these checks is not a false claim, and a citation
that passes is not a true one.** The output says which check ran.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: `store.py:63`, `agentctl/kernel/hook.py:94`, with optional backticks.
_CITE = re.compile(r"`?([\w./\\-]+\.[A-Za-z]\w*):(\d+)`?")

#: Tokens worth looking for at the cited line: decimals, backticked spans,
#: and identifiers distinctive enough that finding one means something.
#: Bare short words are deliberately excluded — "the" appearing near a line
#: would corroborate nothing.
_NUMBER = re.compile(r"\b\d+\.\d+\b|\b\d{2,}\b")
_BACKTICK = re.compile(r"`([^`\n]{2,40})`")
_IDENT = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{4,})\b")

#: How far from the cited line a token still counts as "there". Small on
#: purpose: a citation that is 80 lines out is the failure being caught.
WINDOW = 3


@dataclass
class Citation:
    path: str
    line: int
    resolved: Path | None = None
    text: str | None = None
    problem: str | None = None
    #: (token, line where it actually is, or None if nowhere in the file)
    misplaced: list[tuple[str, int | None]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.problem is None and not self.misplaced


def _tokens(context: str) -> list[str]:
    """Distinctive things the claim asserts, worth finding at the line."""
    out: list[str] = []
    for m in _BACKTICK.findall(context):
        m = m.strip()
        # A backticked path:line is the citation itself, not a claim about it.
        if not _CITE.fullmatch(m) and len(m) >= 2:
            out.append(m)
    out += _NUMBER.findall(context)
    out += [t for t in _IDENT.findall(context)
            if "_" in t or not t.islower()]
    # Stable order, no duplicates, and nothing that is just the filename.
    seen, keep = set(), []
    for t in out:
        low = t.lower()
        if low in seen or low.endswith((".py", ".md", ".yaml")):
            continue
        seen.add(low)
        keep.append(t)
    return keep[:6]


def find(report: str) -> list[tuple[str, int, str]]:
    """Every `path:line` in the report, with the sentence around it."""
    out = []
    for m in _CITE.finditer(report):
        start = max(0, m.start() - 220)
        end = min(len(report), m.end() + 80)
        out.append((m.group(1), int(m.group(2)), report[start:end]))
    return out


def check(path: str, line: int, context: str, workspace: str | Path,
          window: int = WINDOW) -> Citation:
    """Resolve one citation and test the claim's tokens against it."""
    c = Citation(path=path, line=line)
    ws = Path(workspace).resolve()

    candidate = (ws / path).resolve()
    if not str(candidate).startswith(str(ws)):
        c.problem = "cites a path outside the workspace"
        return c
    if not candidate.is_file():
        hits = list(ws.rglob(Path(path).name))
        c.problem = ("no such file in the workspace"
                     + (f"; closest match {hits[0].relative_to(ws)}"
                        if len(hits) == 1 else ""))
        return c
    c.resolved = candidate

    try:
        lines = candidate.read_text(encoding="utf-8",
                                    errors="replace").splitlines()
    except Exception as e:                              # noqa: BLE001
        c.problem = f"unreadable: {type(e).__name__}"
        return c

    if not 1 <= line <= len(lines):
        c.problem = f"line {line} is past the end of the file ({len(lines)})"
        return c
    c.text = lines[line - 1].strip()

    lo, hi = max(0, line - 1 - window), min(len(lines), line + window)
    near = "\n".join(lines[lo:hi]).lower()
    # Strip the citations themselves first. `store.py:63` otherwise yields the
    # token `63`, and "63 is not at line 63" flags a correct report -- a
    # verifier that cries wolf on good citations trains you to ignore it,
    # which is worse than not checking at all.
    for tok in _tokens(_CITE.sub(" ", context)):
        if tok.lower() in near:
            continue
        where = next((i + 1 for i, l in enumerate(lines)
                      if tok.lower() in l.lower()), None)
        c.misplaced.append((tok, where))
    return c


def verify(report: str, workspace: str | Path,
           window: int = WINDOW) -> list[Citation]:
    """Every citation in a scout's report, checked."""
    return [check(p, n, ctx, workspace, window) for p, n, ctx in find(report)]


def describe(cites: list[Citation]) -> str:
    """What a reader needs to decide whether to believe the report."""
    if not cites:
        return ("  no citation to check -- this report asserts things it does "
                "not point at, so none of it has been verified.")
    out = []
    for c in cites:
        if c.problem:
            out.append(f"  !!  {c.path}:{c.line}  {c.problem}")
            continue
        if c.misplaced:
            out.append(f"  !!  {c.path}:{c.line}  says: {(c.text or '')[:56]}")
            for tok, where in c.misplaced:
                loc = f"line {where}" if where else "nowhere in this file"
                out.append(f"        {tok!r} is not there -- it is at {loc}")
            continue
        out.append(f"  ok  {c.path}:{c.line}  {(c.text or '')[:60]}")
    bad = sum(1 for c in cites if not c.ok)
    if bad:
        out.append(f"      {bad} of {len(cites)} citation(s) did not check "
                   f"out. A citation that fails is not a false claim -- it is "
                   f"one nobody can take on trust.")
    return "\n".join(out)
