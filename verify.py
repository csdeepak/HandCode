"""Prove the whole system works. One command, zero cost.

    python verify.py            unit tests + every experiment
    python verify.py --fast     unit tests only (~15s)

Everything runs against a local mock provider: no API key, no network, no
tokens. That is deliberate — `docs/0009` R1 requires re-verifying every
source-derived claim on each SDK upgrade, and a check nobody can afford to run
is a check nobody runs.

Exit code 0 means the correctness claims in `docs/0016`, `0017` and `0018` still
hold on this machine, against the versions currently installed.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
PY = sys.executable

CHECKS = [
    ("unit tests",
     ["-m", "pytest", "tests/", "-q", "--ignore=tests/test_chaos_nine_point.py"],
     "the kernel, adapters and CLI"),
    ("nine-point chaos",
     ["-m", "pytest", "tests/test_chaos_nine_point.py", "-q"],
     "crash at every protocol point; the effect lands at most once"),
    ("M0  falsification",
     ["experiments/0000-falsification/run_all.py"],
     "double execution is real; the seams exist"),
    ("M2a gate",
     ["experiments/0001-m2a-chaos/run_chaos.py"],
     "the gate prevents the duplicate"),
    ("M4  probe",
     ["experiments/0002-m4-probe/run_probe_chaos.py"],
     "ambiguity resolves with no human"),
    ("M2b substitution",
     ["experiments/0003-m2b-substitute/run_substitute_chaos.py"],
     "the agent resumes with a result"),
    ("M1  Seam A",
     ["experiments/0005-m1-seam-a/run_m1.py"],
     "the proxy hook fires; two accounts fail over"),
    ("FULL STACK",
     ["experiments/0006-full-stack/run_full_stack.py"],
     "agent -> proxy -> backends, with the gate. The integration."),
    ("M6  replay",
     ["experiments/0008-m6-replay/run_replay.py"],
     "a real recorded session replays offline, identically, for nothing"),
]


def _ascii_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def run(name: str, argv: list[str], why: str) -> tuple[bool, float, str]:
    start = time.time()
    env_args = ["-X", "utf8"] + argv
    p = subprocess.run([PY, *env_args], cwd=str(ROOT), capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       env={**_env(), "OPENHANDS_SUPPRESS_BANNER": "1"})
    elapsed = time.time() - start
    out = (p.stdout or "") + (p.stderr or "")

    # An experiment that could not observe its own scenario is NOT a pass and
    # NOT a failure -- docs/0012 §6.
    if "INCONCLUSIVE" in out:
        return False, elapsed, "INCONCLUSIVE"
    return p.returncode == 0, elapsed, ("ok" if p.returncode == 0 else "FAILED")


def _env() -> dict:
    import os
    return dict(os.environ)


def main() -> int:
    _ascii_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true",
                    help="unit tests + the nine-point suite only (~60s)")
    args = ap.parse_args()

    checks = CHECKS[:2] if args.fast else CHECKS
    print("=" * 70)
    print("agentctl verification - no API key, no network, no tokens")
    print("=" * 70)

    results = []
    for name, argv, why in checks:
        print(f"\n  running {name} ...", flush=True)
        ok, secs, status = run(name, argv, why)
        results.append((name, ok, secs, status, why))
        mark = "PASS" if ok else status
        print(f"  {mark:<13} {name:<20} {secs:5.1f}s   {why}")

    print("\n" + "=" * 70)
    failed = [r for r in results if not r[1]]
    total = sum(r[2] for r in results)
    if failed:
        print(f"{len(failed)} of {len(results)} checks did not pass  ({total:.0f}s)")
        for name, _, _, status, _ in failed:
            print(f"  {status:<13} {name}")
        print("\nAn INCONCLUSIVE result is a broken harness, not a broken system.")
        print("Re-run the individual experiment to see why.")
        return 1

    print(f"all {len(results)} checks passed  ({total:.0f}s)")
    if not args.fast:
        print("\nThe correctness claims still hold on this machine:")
        print("  - no duplicate side effect at ANY of the nine crash points")
        print("  - ambiguity resolves automatically where the world can be asked")
        print("  - the agent resumes with a result, not a refusal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
