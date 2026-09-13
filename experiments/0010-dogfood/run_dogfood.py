r"""Dogfood: point agentctl at its own repository and grade the result.

Everything before this drove the agent at a toy workspace. This gives it a
real, documented gap in this codebase and checks the work objectively.

## The task

`docs/0026` §6 admits: *"Windows shells are unhandled. No `Remove-Item`, no
`del`, no `rd /s`."* Verified still true — all four classify `EXTERNAL`, so
`--confirm-destructive` never fires for them:

    EXTERNAL   del /f /s /q C:\important
    EXTERNAL   rd /s /q build
    EXTERNAL   Remove-Item -Recurse -Force .
    EXTERNAL   format C:

## Why this task and not another

It is **self-grading**. The agent either makes those four classify
`DESTRUCTIVE` or it does not, and the existing 75-command corpus either still
passes or it does not. No judgement call, no "looks about right" — which is
what makes it a test of the *system* rather than a demo of the model.

It is also the failure mode that matters: an under-classification waves a real
effect through the gate (`docs/0026` §5).

## Safety

* runs on a **branch**, never on `main`
* the repo must be clean first, so every change is attributable and revertible
* `--confirm-destructive` stays on; unattended, a prompt reads EOF as "no"
* the full suite runs afterwards, because a fix that breaks 413 other tests is
  not a fix

    python run_dogfood.py              # needs quota
    python run_dogfood.py --check-only # grade the current tree, no model
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))

RESULTS = HERE / "results" / "dogfood.json"
BRANCH = "dogfood/windows-shell-classifier"

# The four commands the classifier misses today. The acceptance criterion.
MUST_BE_DESTRUCTIVE = [
    r"del /f /s /q C:\important",
    r"rd /s /q build",
    "Remove-Item -Recurse -Force .",
    "format C:",
]

# ...and these must NOT become destructive, or the "fix" is just
# "everything is dangerous", which protects nothing (`docs/0026` §5).
MUST_STAY_BENIGN = [
    ("ls -la", "PURE_READ"),
    ("cat README.md", "PURE_READ"),
    ("echo x > notes.txt", "IDEMPOTENT_WRITE"),
    ("dir", None),                      # any class but DESTRUCTIVE
    ("Get-ChildItem", None),
]

TASK = (
    "In agentctl/control/matrix/data/tools.yaml, the execute_bash rules only "
    "recognise POSIX deletion commands. Windows deletion commands are "
    "classified EXTERNAL instead of DESTRUCTIVE, which means no confirmation "
    "prompt fires for them.\n\n"
    "Add rules under the '-- destructive --' section of execute_bash so that "
    "these are classified DESTRUCTIVE:\n"
    r"  del /f /s /q C:\important" "\n"
    "  rd /s /q build\n"
    "  rmdir /s /q build\n"
    "  Remove-Item -Recurse -Force .\n"
    "  format C:\n\n"
    "Rules are regex matched against each shell segment; copy the style of the "
    "existing rules. Do NOT make plain listing commands destructive: 'dir' and "
    "'Get-ChildItem' must not match, and 'ls', 'cat', 'echo x > f.txt' must "
    "keep their current classes.\n\n"
    "Use read_file to read the file first and write_file to save it. "
    "Then stop."
)


def _run(*argv: str, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def classify_now() -> dict[str, str]:
    """Fresh subprocess: the agent edits YAML the classifier loads at import."""
    code = (
        "import json;"
        "from agentctl.kernel.classify import Classifier;"
        "from agentctl.kernel.ledger.models import ToolCall;"
        "c=Classifier();"
        "cmds=json.loads(input());"
        "print(json.dumps({x: c.classify("
        "ToolCall('t','c','t1','execute_bash',{'command':x})).value "
        "for x in cmds}))"
    )
    cmds = MUST_BE_DESTRUCTIVE + [c for c, _ in MUST_STAY_BENIGN]
    p = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT),
                       input=json.dumps(cmds), capture_output=True, text=True)
    if p.returncode != 0:
        return {"__error__": (p.stderr or "")[-400:]}
    return json.loads(p.stdout.strip().splitlines()[-1])


def grade() -> tuple[dict, dict]:
    """Objective pass/fail. No judgement calls."""
    got = classify_now()
    if "__error__" in got:
        return ({"the matrix still loads": False},
                {"classifier_error": got["__error__"]})

    checks = {}
    for cmd in MUST_BE_DESTRUCTIVE:
        checks[f"DESTRUCTIVE: {cmd}"] = got.get(cmd) == "DESTRUCTIVE"
    for cmd, expected in MUST_STAY_BENIGN:
        checks[f"unchanged: {cmd}"] = (
            got.get(cmd) == expected if expected else
            got.get(cmd) != "DESTRUCTIVE")

    suite = _run(sys.executable, "-m", "pytest", "tests/", "-q")
    checks["the other 413 tests still pass"] = suite.returncode == 0
    tail = (suite.stdout or "").strip().splitlines()[-1:] or [""]
    return checks, {"classified": got, "pytest": tail[0]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true",
                    help="grade the current tree without running a model")
    ap.add_argument("--model", default="openrouter/nex-agi/nex-n2.5-pro:free")
    ap.add_argument("--max-iterations", type=int, default=25)
    args = ap.parse_args()

    out: dict = {"experiment": "0010-dogfood", "ts": time.time(),
                 "verdict": "INCONCLUSIVE", "evidence": {}}

    if not args.check_only:
        dirty = _run("git", "status", "--porcelain").stdout.strip()
        if dirty:
            print("  refusing: the repo is not clean. Every change the agent")
            print("  makes must be attributable and revertible.")
            print(dirty[:400])
            return 2

        start = _run("git", "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        _run("git", "checkout", "-B", BRANCH)
        print(f"  branch        {BRANCH}  (was on {start})")

        before = classify_now()
        out["evidence"]["before"] = before
        print(f"  before        {sum(1 for c in MUST_BE_DESTRUCTIVE if before.get(c) == 'DESTRUCTIVE')}"
              f"/{len(MUST_BE_DESTRUCTIVE)} classified DESTRUCTIVE")
        print()

        from agentctl.runtime.runner import run
        try:
            result = run(TASK, ROOT, model=args.model,
                         ledger=HERE / "results" / "dogfood.db",
                         max_iterations=args.max_iterations,
                         confirm_destructive=True, verbose=True)
        except SystemExit as e:
            out["evidence"]["stopped"] = str(e)
            _write(out)
            print(f"\n  stopped before finishing:\n{e}")
            return 2
        out["evidence"]["decisions"] = result["decisions"]
        out["evidence"]["blocked"] = result["blocked"]

    checks, ev = grade()
    out["evidence"].update(ev)
    out["evidence"]["checks"] = checks
    out["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    _write(out)

    print()
    for name, ok in checks.items():
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    print(f"\n  VERDICT: {out['verdict']}")
    if not args.check_only:
        print(f"  diff:    git diff main..{BRANCH}")
        print(f"  undo:    git checkout main && git branch -D {BRANCH}")
    return 0 if out["verdict"] == "PASS" else 1


def _write(out: dict) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
