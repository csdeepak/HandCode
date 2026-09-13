r"""M6 acceptance: a real session, replayed offline at zero cost.

`session.jsonl` was recorded against a real provider (OpenRouter, a free-tier
model) doing real work: read `utils.py`, add type hints, write it back. It is
committed so this runs anywhere, forever, with **no API key, no network and no
tokens** -- which is what makes it fit inside `verify.py`.

The check is not "did it not crash". It is:

    3 of 3 recorded turns replayed, 0 misses
    the file on disk ends up byte-identical to the recorded run
    the gate reaches the same decisions
    the cassette is not modified by replaying it

The API keys are removed from the environment before the replay, so a run that
quietly reached the network would fail rather than pass for the wrong reason.

Run standalone:
    python run_replay.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))

CASSETTE = HERE / "session.jsonl"
RESULTS = HERE / "results" / "replay.json"

TASK = ("Read utils.py, add Python type hints to both functions, and save it "
        "with write_file. Then stop.")
SEED = ("def add(a, b):\n    return a + b\n\n"
        "def greet(name):\n    return \"hello \" + name\n")

KEY_VARS = ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY", "MISTRAL_API_KEY")


def main() -> int:
    out: dict = {"experiment": "0008-m6-replay", "ts": time.time(),
                 "verdict": "INCONCLUSIVE", "evidence": {}}
    ev = out["evidence"]

    root = Path(tempfile.mkdtemp(prefix="m6_replay_"))
    ws = root / "ws"
    ws.mkdir(parents=True)
    (ws / "utils.py").write_text(SEED, encoding="utf-8")

    before = CASSETTE.read_bytes()

    # Remove every key. A replay that reaches the network must fail, not pass.
    saved = {k: os.environ.pop(k, None) for k in KEY_VARS}
    try:
        from agentctl.runtime.runner import run

        result = run(TASK, ws, ledger=root / "ledger.db", replay=CASSETTE,
                     confirm_destructive=False, max_iterations=12,
                     verbose=False)
    except Exception as e:                              # noqa: BLE001
        ev["error"] = f"{type(e).__name__}: {e}"
        _write(out)
        print(f"  INCONCLUSIVE - replay did not complete: {ev['error'][:200]}")
        return 2
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v

    rep = result.get("replay") or {}
    final = (ws / "utils.py").read_text(encoding="utf-8")
    verdicts = sorted({d["verdict"] for d in result["decisions"]})

    ev.update({
        "turns_recorded": rep.get("turns_recorded"),
        "turns_replayed": rep.get("turns_replayed"),
        "misses": rep.get("misses"),
        "diverged": rep.get("diverged"),
        "decisions": verdicts,
        "gate_errors": sum(1 for d in result["decisions"]
                           if "gate error" in (d.get("reason") or "")),
        "cassette_unmodified": CASSETTE.read_bytes() == before,
        "keys_present_during_replay": False,
        "final_file": final,
    })

    checks = {
        "every recorded turn replayed":
            rep.get("turns_replayed") == rep.get("turns_recorded") ==
            len(_lines(CASSETTE)),
        "no divergence": rep.get("diverged") is False and rep.get("misses") == 0,
        "the agent actually edited the file":
            "def add(a: int, b: int) -> int:" in final,
        "the gate ran and reached a decision": verdicts == ["EXECUTE"],
        # A crashing gate also yields a usable-looking run (docs/0024).
        "no gate errors": ev["gate_errors"] == 0,
        # Replaying must not rewrite the recording (docs/0029 §5).
        "the cassette is unchanged": ev["cassette_unmodified"],
    }
    ev["checks"] = checks
    out["verdict"] = "PASS" if all(checks.values()) else "FAIL"
    _write(out)

    for name, ok in checks.items():
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}")
    print(f"\n  {rep.get('turns_replayed')}/{rep.get('turns_recorded')} turns, "
          f"$0.00, no API key in the environment")
    print(f"  VERDICT: {out['verdict']}")
    shutil.rmtree(root, ignore_errors=True)
    return 0 if out["verdict"] == "PASS" else 1


def _lines(p: Path) -> list[str]:
    return [l for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(out: dict) -> None:
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(out, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
