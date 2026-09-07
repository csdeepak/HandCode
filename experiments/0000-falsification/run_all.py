"""
M0 orchestrator — runs every probe, writes a report.

    python run_all.py

Exit code 0 means the architecture in docs/0008 survived. Anything else means
read the report before writing another line of code.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"

PROBES = [
    ("probe_00_api.py", "SDK API surface", True),   # True = abort run if it fails
    ("probe_01_wrap.py", "H3/Q3 executor wrapping", False),
    ("run_03_crash.py", "H1/Q1 · H2/Q2 · H4/Q13", False),
]

DECISION = {
    "H1": ("Double execution is real",
           "Effect Ledger is the product. Proceed to M2.",
           "docs/0007 BUILD verdict collapses. Ledger becomes an audit layer."),
    "H2": ("tool_call_id stable across resume",
           "docs/0012 §2.1 primary key is valid.",
           "Re-key the ledger on action_event_id or a content hash."),
    "H3": ("Executor wrappable without a fork",
           "Seam C exists. Option 3 architecture holds.",
           "Seam C unavailable. Fall back to Option 1; supersede docs/0008."),
    "H4": ("OpenAI-format endpoint in use",
           "Seam A hooks will fire. M1 can proceed.",
           "LiteLLM #27518 silently bypasses Seam A. Force OpenAI format in M1."),
}


def _run(script: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(HERE / script)],
                       capture_output=True, text=True, cwd=str(HERE))
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _collect() -> dict[str, str]:
    verdicts: dict[str, str] = {}
    for name in ("probe_01_wrap.json", "probe_03_crash.json"):
        f = RESULTS / name
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        if "verdicts" in data:
            verdicts.update(data["verdicts"])
        elif "hypothesis" in data:
            verdicts[data["hypothesis"]] = data["verdict"]
    return verdicts


def _report(verdicts: dict[str, str], log: list[str]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    versions = {}
    api = RESULTS / "api_surface.json"
    if api.exists():
        versions = json.loads(api.read_text(encoding="utf-8")).get("versions", {})

    lines = [
        "# M0 Falsification — Results", "",
        f"**Run:** {now}", "",
        "## Versions", "",
        "| Package | Version |", "|---|---|",
    ]
    lines += [f"| `{k}` | {v} |" for k, v in versions.items()]
    lines += ["", "## Verdicts", "",
              "| # | Hypothesis | Verdict | Consequence |", "|---|---|---|---|"]

    for h, (claim, if_yes, if_no) in DECISION.items():
        v = verdicts.get(h, "NOT RUN")
        conseq = if_yes if v == "CONFIRMED" else (if_no if v == "FALSIFIED" else "—")
        mark = {"CONFIRMED": "✅", "FALSIFIED": "❌",
                "PARTIAL": "⚠️", "INCONCLUSIVE": "⚠️"}.get(v, "·")
        lines.append(f"| {h} | {claim} | {mark} {v} | {conseq} |")

    survived = all(verdicts.get(h) in ("CONFIRMED", "PARTIAL") for h in DECISION)
    lines += ["", "## Outcome", ""]
    lines.append(
        "**The architecture in `docs/0008` survived.** Proceed to M1."
        if survived else
        "**At least one assumption failed.** Do not start M1. Update "
        "`docs/0009` with the resolutions, then revise `docs/0008` and "
        "`docs/0012` before writing further code."
    )
    lines += ["", "## Next actions", "",
              "1. Record every verdict in `docs/0009` §Resolution log.",
              "2. Write a numbered DECISION document for anything falsified.",
              "3. Promote `docs/0008` from DRAFT only when Q1-Q3 and Q13 are closed.",
              "", "## Raw output", "", "```", *log, "```", ""]
    return "\n".join(lines)


def _ascii_stdout() -> None:
    """Windows consoles default to cp1252 and crash on non-ASCII output."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    _ascii_stdout()
    RESULTS.mkdir(exist_ok=True)
    log: list[str] = []

    for script, label, gating in PROBES:
        print(f"\n>>> {script}  -  {label}")
        code, output = _run(script)
        print(output.rstrip())
        log += [f"$ python {script}", output.rstrip(), ""]
        if gating and code != 0:
            log.append("ABORTED: API surface mismatch — later probes would be noise.")
            print("\n  ABORTED. Fix the API mismatch first (results/api_surface.json).")
            (RESULTS / "report.md").write_text(_report({}, log), encoding="utf-8")
            return 2

    verdicts = _collect()
    report = _report(verdicts, log)
    (RESULTS / "report.md").write_text(report, encoding="utf-8")
    (RESULTS / "verdicts.json").write_text(
        json.dumps(verdicts, indent=2), encoding="utf-8")

    print("\n" + "=" * 68)
    print("M0 COMPLETE")
    print("=" * 68)
    for h, (claim, _, _) in DECISION.items():
        print(f"  {h}  {verdicts.get(h, 'NOT RUN'):<14} {claim}")
    print(f"\n  report: {RESULTS / 'report.md'}")

    survived = all(verdicts.get(h) in ("CONFIRMED", "PARTIAL") for h in DECISION)
    return 0 if survived else 1


if __name__ == "__main__":
    raise SystemExit(main())
