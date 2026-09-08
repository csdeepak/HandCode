"""One run of the write-ahead protocol, crashable at a named point.

Spec: `docs/0012` §6, `docs/0008` §10.

Driven directly against the kernel rather than through the SDK. That is
deliberate: the guarantee in `docs/0008` §10 is a property of the *protocol*,
and testing it here is precise (the crash point is chosen, not raced for) and
fast enough to run on every commit. The SDK-level experiments in `0001`-`0003`
cover the integration.

The crash is a real one — `os._exit()` skips every finally block, atexit hook
and buffer flush, which is as close to `kill -9` as a process can do to itself.

    python worker.py --point after_intent --workdir DIR --effect git
    python worker.py --point none --workdir DIR --effect git --resume
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentctl.kernel.classify import Classifier          # noqa: E402
from agentctl.kernel.gate import EffectGate               # noqa: E402
from agentctl.kernel.ledger.models import ToolCall, Verdict  # noqa: E402
from agentctl.kernel.ledger.store import LedgerStore      # noqa: E402
from agentctl.kernel.reconcile import (                   # noqa: E402
    FileAppendProbe, GitProbe, ProbeRegistry,
)

#: `docs/0012` §6. Pairs 6/7 and 8/9 name the same instant from either side —
#: kept because the spec names them, and because a future change could separate
#: them. See `docs/0019` §2.
CRASH_POINTS = [
    "before_action_event",
    "after_action_event",
    "before_intent",
    "after_intent",
    "mid_tool",
    "after_tool",
    "before_commit",
    "after_commit",
    "before_observation",
]

CONV_ID = "conv_nine_point"
TOOL_CALL_ID = "call_nine_point_0001"
APPEND_TEXT = "EFFECT-LINE\n"

MATRIX = {
    "version": 1,
    "defaults": {"unknown_tool": "EXTERNAL"},
    "tools": {
        "git_commit": {"class": "NON_IDEMPOTENT_WRITE", "probe": "git"},
        "append": {"class": "NON_IDEMPOTENT_WRITE", "probe": "filesystem"},
    },
}

EXIT_CRASHED = 137          # conventionally SIGKILL


class Crasher:
    """Exits hard at one named point, once."""

    def __init__(self, point: str | None):
        self.point = point

    def maybe(self, here: str) -> None:
        if here == self.point:
            sys.stderr.write(f"CRASH at {here}\n")
            sys.stderr.flush()
            os._exit(EXIT_CRASHED)


class CrashingStore(LedgerStore):
    """LedgerStore that can die inside the write-ahead protocol.

    Wrapping the store is what makes `before_intent` and `after_intent`
    distinguishable — the gate writes INTENT internally, so the crash point has
    to live where the write happens.
    """

    def __init__(self, *a, crasher: Crasher, **kw):
        super().__init__(*a, **kw)
        self._crasher = crasher

    def write_intent(self, *a, **kw):
        self._crasher.maybe("before_intent")
        rec = super().write_intent(*a, **kw)
        self._crasher.maybe("after_intent")
        return rec

    def commit(self, *a, **kw):
        self._crasher.maybe("before_commit")
        out = super().commit(*a, **kw)
        self._crasher.maybe("after_commit")
        return out


# ── the effects ────────────────────────────────────────────────────────
def git(repo: Path, *args: str):
    return subprocess.run(["git", *args], cwd=str(repo),
                          capture_output=True, text=True)


def do_git_commit(repo: Path, crasher: Crasher) -> None:
    """Atomic from our side: the commit either exists or it does not."""
    crasher.maybe("mid_tool")
    git(repo, "commit", "--allow-empty", "-m", "nine-point effect")


def do_append(target: Path, crasher: Crasher) -> None:
    """Non-atomic: `mid_tool` leaves a genuinely half-written effect."""
    half = len(APPEND_TEXT) // 2
    with target.open("a", encoding="utf-8") as fh:
        fh.write(APPEND_TEXT[:half])
        fh.flush()
        os.fsync(fh.fileno())
        crasher.maybe("mid_tool")            # <- half the line is on disk
        fh.write(APPEND_TEXT[half:])
        fh.flush()
        os.fsync(fh.fileno())


def build_call(effect: str, repo: Path, target: Path) -> ToolCall:
    if effect == "git":
        return ToolCall(TOOL_CALL_ID, CONV_ID, "turn_1", "git_commit",
                        {"message": "nine-point effect", "cwd": str(repo)})
    return ToolCall(TOOL_CALL_ID, CONV_ID, "turn_1", "append",
                    {"path": str(target), "content": APPEND_TEXT})


# ── the protocol ───────────────────────────────────────────────────────
def run(point: str | None, workdir: Path, effect: str, resume: bool) -> int:
    crasher = Crasher(point)
    repo, target = workdir / "repo", workdir / "log.txt"

    crasher.maybe("before_action_event")
    # The harness would persist its ActionEvent here. We hold no SDK, and the
    # ledger is our own record, so this point means "nothing recorded yet".
    crasher.maybe("after_action_event")

    store = CrashingStore(workdir / "ledger.db",
                          holder=f"worker-{'resume' if resume else 'fresh'}",
                          crasher=crasher)
    gate = EffectGate(
        store,
        Classifier(matrix=MATRIX),
        probes=ProbeRegistry(GitProbe(repo), FileAppendProbe()),
        fence=store.acquire(CONV_ID, takeover=resume),
    )

    call = build_call(effect, repo, target)
    decision = gate.guard(call)
    _record(workdir, resume, {"verdict": decision.verdict.value,
                              "class": decision.effect_class.value
                              if decision.effect_class else None,
                              "reason": decision.reason})

    if decision.verdict is Verdict.EXECUTE:
        if effect == "git":
            do_git_commit(repo, crasher)
        else:
            do_append(target, crasher)
        crasher.maybe("after_tool")
        store.commit(call.tool_call_id, b'{"status":"ok"}')
        crasher.maybe("before_observation")
        store.observed(call.tool_call_id)

    store.close()
    return 0


def _record(workdir: Path, resume: bool, payload: dict) -> None:
    (workdir / f"decision_{'resume' if resume else 'fresh'}.json").write_text(
        json.dumps(payload), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--point", default="none")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--effect", choices=["git", "append"], default="git")
    ap.add_argument("--resume", action="store_true")
    a = ap.parse_args()
    point = None if a.point == "none" else a.point
    return run(point, Path(a.workdir), a.effect, a.resume)


if __name__ == "__main__":
    raise SystemExit(main())
