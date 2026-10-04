"""What a run did, in words a user can act on. `docs/0043` Phase 3.

Phase 0 (`docs/0044` F6, F10) ended every run with `decisions {'EXECUTE': 9}`
-- the gate's vocabulary, not the user's -- and nothing about whether the task
worked, what changed, or what it cost. The report answers four questions, and
derives every line from the same records the precise output uses, because a
friendly line computed some other way is how a tool starts saying confidently
wrong things (`docs/0039`):

    outcome     did it work?          only what was CHECKED; never implied
    changed     what is different?    from git, against the run's start
    used        what did it cost?     requests, tokens, money -- labelled
    needs you   what is left?         blocked effects, with the command
"""
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

# ── the vocabulary (`docs/0043` §3, Phase 3) ──────────────────────────────
#: The gate's verdicts, as a user would say them.
VERDICT_WORDS = {
    "EXECUTE": "ran",
    "SUBSTITUTE": "already done; reused the recorded result",
    "BLOCK": "paused; needs your decision",
    "ESCALATE": "paused; needs your decision",
}

#: Effect classes, as kinds of action.
CLASS_WORDS = {
    "PURE_READ": "read",
    "IDEMPOTENT_WRITE": "file write",
    "NON_IDEMPOTENT_WRITE": "command",
    "EXTERNAL": "command",
    "DESTRUCTIVE": "dangerous command",
}


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# ── what changed ──────────────────────────────────────────────────────────
def _git(ws: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", *args], cwd=str(ws), capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=30)
    except Exception:                                   # noqa: BLE001
        return None
    return r.stdout if r.returncode == 0 else None


def _porcelain(ws: Path, prefix: str = "") -> set[str]:
    """Changed paths under `ws`, relative to it. `prefix` is `ws` relative to
    the repository's top level: porcelain paths are always top-level ones."""
    out = _git(ws, "status", "--porcelain=v1", "--untracked-files=all",
               "--", ".") or ""
    paths = set()
    for line in out.splitlines():
        path = line[3:].strip().strip('"')
        if prefix and path.startswith(prefix):
            path = path[len(prefix):]
        if path and not path.startswith(".agentctl"):
            paths.add(path)
    return paths


@dataclass(frozen=True)
class Start:
    """The workspace as the run found it."""
    is_git: bool
    head: str | None                 # None: a repo with no commits yet
    dirty: frozenset[str]            # paths already changed before the run
    at: float
    #: `ws` relative to the repository's top level, "" when it IS the top.
    #: Non-empty means the workspace sits inside a bigger repository -- on
    #: the machine this was built on, the home directory itself -- and every
    #: git question must be scoped to the workspace, or the report describes
    #: someone else's files (`docs/0048`).
    prefix: str = ""
    toplevel: str = ""


def snapshot(ws: str | Path) -> Start:
    ws = Path(ws)
    if _git(ws, "rev-parse", "--is-inside-work-tree") is None:
        return Start(False, None, frozenset(), time.time())
    head = (_git(ws, "rev-parse", "HEAD") or "").strip() or None
    prefix = (_git(ws, "rev-parse", "--show-prefix") or "").strip()
    top = (_git(ws, "rev-parse", "--show-toplevel") or "").strip()
    return Start(True, head, frozenset(_porcelain(ws, prefix)), time.time(),
                 prefix, top)


@dataclass
class Changes:
    files: list[tuple[str, int | None, int | None]] = field(default_factory=list)
    commits: int = 0
    already_dirty: int = 0
    note: str = ""

    @property
    def added(self) -> int:
        return sum(a or 0 for _, a, _ in self.files)

    @property
    def removed(self) -> int:
        return sum(d or 0 for _, _, d in self.files)


def changes(ws: str | Path, start: Start) -> Changes:
    """Files that differ from where the run started, commits included.

    Measured against the starting commit, so work the agent committed counts
    as well as work it left uncommitted. Files that were ALREADY modified
    before the run are counted only if they differ now, and their number is
    reported, because their diff mixes the user's edits with the agent's.
    """
    ws = Path(ws)
    if not start.is_git:
        return Changes(note="not a git repository, so changes are not tracked")
    c = Changes(already_dirty=len(start.dirty))
    if start.prefix:
        c.note = f"(inside the repository at {start.toplevel})"
    seen: set[str] = set()
    if start.head:
        c.commits = int((_git(ws, "rev-list", "--count", f"{start.head}..HEAD",
                              "--", ".") or "0").strip() or 0)
        # --relative: limited to the workspace, with paths relative to it.
        for line in (_git(ws, "diff", "--numstat", "--relative", start.head)
                     or "").splitlines():
            parts = line.split("\t")
            if len(parts) != 3 or parts[2].startswith(".agentctl"):
                continue
            a, d, path = parts
            c.files.append((path, None if a == "-" else int(a),
                            None if d == "-" else int(d)))
            seen.add(path)
    for path in sorted(_porcelain(ws, start.prefix) - start.dirty - seen):
        p = ws / path
        try:
            n = sum(1 for _ in p.open(encoding="utf-8", errors="replace"))
        except Exception:                               # noqa: BLE001
            n = None
        c.files.append((path, n, 0))
    return c


# ── what it cost ──────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Usage:
    requests: int
    tokens: int
    cost: float

    @staticmethod
    def of(conv) -> "Usage":
        try:
            m = conv.state.stats.get_combined_metrics()
            t = m.accumulated_token_usage
            tokens = ((getattr(t, "prompt_tokens", 0) or 0)
                      + (getattr(t, "completion_tokens", 0) or 0)) if t else 0
            return Usage(len(m.response_latencies or []), tokens,
                         float(m.accumulated_cost or 0.0))
        except Exception:                               # noqa: BLE001
            return Usage(0, 0, 0.0)

    def __sub__(self, o: "Usage") -> "Usage":
        return Usage(self.requests - o.requests, self.tokens - o.tokens,
                     self.cost - o.cost)


def describe_cost(model: str, cost: float) -> str:
    """A money figure with what it can and cannot be trusted for.

    `docs/0042` I-10: litellm puts LIST prices on free-tier calls and reports
    nothing for OpenRouter's `:free` ids, so the bare number is wrong in both
    directions. Three honest states instead of one dishonest one.
    """
    from agentctl.control.providers import PROVIDERS
    from agentctl.control.proxy import POOL

    if model.endswith(":free") or model.split("/", 1)[-1].startswith(POOL):
        return "$0.00 (free-tier model)"
    provider = next((p for p in PROVIDERS if model.startswith(p.prefix)), None)
    if provider and provider.free_tier:
        return (f"${cost:.4f} at list price; a free-tier key is not billed "
                f"(per the provider's plan, unverified here)"
                if cost else "$0.00 (free tier, unpriced)")
    if not cost:
        return "unknown (the provider's price was not reported)"
    return f"${cost:.4f} (as litellm priced it)"


def _k(n: int) -> str:
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def _duration(s: float) -> str:
    s = int(round(s))
    return f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


# ── the report ────────────────────────────────────────────────────────────
@dataclass
class Report:
    outcome: str                    # "PASS" | "FAIL" | "not checked"
    accept: dict | None
    changes: Changes
    agent_said: str | None
    usage: Usage
    model: str
    seconds: float
    decisions: list[dict]
    blocked: list[str]
    ledger: str
    conversation_id: str
    workspace: str
    #: (tool_call_id, what it would do) for actions queued for approval
    #: rather than refused -- a different question from an ambiguous effect.
    awaiting: list[tuple[str, str]] = field(default_factory=list)
    #: Stopped by Ctrl-C after a step. Not done, and resumable.
    paused: bool = False

    @property
    def ok(self) -> bool:
        """Done, as far as anything here can tell: nothing failed a check,
        nothing waits on a human, and the user did not pause it. "not
        checked" is not a failure -- and is never printed as a success."""
        return self.outcome != "FAIL" and not self.blocked and not self.paused

    def to_json(self) -> dict:
        """What a program reading the report needs (`--report-json`, the
        GitHub Action of `docs/0053`). `text` is the report as printed, so a
        reader never re-renders it and drifts from the terminal."""
        return {
            "outcome": self.outcome, "ok": self.ok, "paused": self.paused,
            "accept": ({k: self.accept.get(k) for k in ("command", "exit", "passed")}
                       if self.accept else None),
            "files": [p for p, _, _ in self.changes.files],
            "commits": self.changes.commits,
            "awaiting": [{"id": t, "what": w} for t, w in self.awaiting],
            "blocked": len(self.blocked),
            "model": self.model, "requests": self.usage.requests,
            "tokens": self.usage.tokens, "seconds": round(self.seconds, 1),
            "conversation_id": self.conversation_id,
            "text": "\n".join(self.lines()).strip("\n"),
        }

    def lines(self) -> list[str]:
        out = ["", "  ── result " + "─" * 58]
        if self.accept:
            a = self.accept
            out.append(f"  outcome     {self.outcome}   `{a['command']}` exited "
                       f"{a['exit']} (run by agentctl after the agent finished)")
            if self.outcome == "FAIL" and a.get("tail"):
                out += [f"                {l}" for l in a["tail"]]
        else:
            out.append("  outcome     not checked   (add --accept \"<test command>\" "
                       "to have agentctl check it)")

        c = self.changes
        if c.note and not c.note.startswith("(inside"):
            out.append(f"  changed     {c.note}")
        elif not c.files:
            out.append("  changed     nothing" + (f" ({plural(c.commits, 'commit')})"
                                                  if c.commits else ""))
        else:
            head = f"  changed     {plural(len(c.files), 'file')}  +{c.added} -{c.removed}"
            if c.commits:
                head += f"   ({plural(c.commits, 'commit')})"
            out.append(head)
            width = min(max(len(p) for p, _, _ in c.files), 40)
            for path, a, d in c.files[:8]:
                stat = "binary" if a is None else f"+{a} -{d}"
                out.append(f"                {path:<{width}}  {stat}")
            if len(c.files) > 8:
                out.append(f"                ... and {len(c.files) - 8} more")
            if c.already_dirty:
                out.append(f"                ({plural(c.already_dirty, 'file')} "
                           f"already had changes before the run)")
        if c.note.startswith("(inside"):
            out.append(f"                {c.note}")

        if self.agent_said:
            said = [l for l in self.agent_said.strip().splitlines() if l.strip()]
            first = said[0][:96] + ("..." if len(said[0]) > 96 else "")
            out.append(f"  agent said  \"{first}\"")
            if len(said) > 1:
                out.append(f"                (+{len(said) - 1} more line(s) above)")

        u = self.usage
        out.append(f"  used        {plural(u.requests, 'request')} · "
                   f"{_k(u.tokens)} tokens · {describe_cost(self.model, u.cost)} · "
                   f"{_duration(self.seconds)}")

        kinds: dict[str, int] = {}
        verdicts: dict[str, int] = {}
        for d in self.decisions:
            w = CLASS_WORDS.get(d.get("class") or "", "action")
            kinds[w] = kinds.get(w, 0) + 1
            verdicts[d["verdict"]] = verdicts.get(d["verdict"], 0) + 1
        if kinds:
            parts = ", ".join(plural(n, w) for w, n in sorted(kinds.items(),
                                                              key=lambda kv: -kv[1]))
            extra = []
            if (n := verdicts.get("SUBSTITUTE")):
                extra.append(f"{n} already done, reused")
            if (n := verdicts.get("BLOCK", 0) + verdicts.get("ESCALATE", 0)):
                extra.append(f"{n} paused")
            out.append(f"  actions     {plural(len(self.decisions), 'action')}: "
                       f"{parts}" + (" · " + ", ".join(extra) if extra else ""))

        waiting = {tid for tid, _ in self.awaiting}
        other = [b for b in self.blocked if b not in waiting]
        if not self.blocked:
            out.append("  needs you   nothing")
        if self.awaiting:
            out.append(f"  needs you   {plural(len(self.awaiting), 'action')} "
                       f"waiting for your approval:")
            for tid, what in self.awaiting:
                short = tid[:12]
                out.append(f"                {what[:70]}")
                out.append(f"                  agentctl approve {short}   |   "
                           f"agentctl deny {short}")
        if other:
            label = "             " if self.awaiting else "  needs you  "
            out.append(f"{label} {plural(len(other), 'action')} whose outcome "
                       f"is unknown: agentctl blocked")
        short_cid = self.conversation_id[:8]
        if self.paused:
            out.append(f"  paused      by you. Continue:  agentctl resume {short_cid}")
        elif self.awaiting:
            out.append(f"  then        agentctl resume {short_cid}   (the agent is "
                       f"told what you decided)")
        else:
            out.append(f"  resume      agentctl resume {short_cid}")
        return out


# ── acceptance ────────────────────────────────────────────────────────────
def accept(command: str, ws: str | Path, timeout_s: float = 900.0) -> dict:
    """Run the user's check, OUTSIDE the agent and outside the ledger.

    It is not an effect the agent chose, so it is not gated, and its result is
    the harness's own observation rather than the agent's claim about itself.
    """
    t0 = time.time()
    try:
        r = subprocess.run(command, shell=True, cwd=str(ws), capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout_s)
        code, text = r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        code, text = None, f"timed out after {timeout_s:.0f}s"
    lines = [l for l in text.strip().splitlines() if l.strip()]
    return {"command": command, "exit": code, "seconds": time.time() - t0,
            "passed": code == 0, "tail": lines[-6:]}
