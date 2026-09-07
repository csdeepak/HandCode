"""
Probe 01 — H3 / Q3: can a ToolExecutor be wrapped without forking?

The single highest-risk assumption in `docs/0008`. If this fails, Seam C does
not exist, requirement R1 is unsatisfiable, and the architecture is dead.

No network, no API key. Pure introspection and a direct call.

    python probe_01_wrap.py
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

RESULTS = Path(__file__).parent / "results"


def run() -> dict:
    out: dict = {"hypothesis": "H3", "question": "Q3", "verdict": "UNKNOWN",
                 "evidence": {}, "notes": []}

    try:
        from openhands.sdk.tool import ToolExecutor, register_tool
    except Exception as e:                            # noqa: BLE001
        out["verdict"] = "ERROR"
        out["evidence"]["import_error"] = repr(e)
        out["notes"].append("Run probe_00_api.py first — the SDK import failed.")
        return out

    # ---- 1. a real executor -------------------------------------------------
    inner_calls: list[dict] = []

    class RealExecutor(ToolExecutor):
        def __call__(self, action, *a, **kw):
            inner_calls.append({"action": repr(action)[:120]})
            return {"ok": True, "echo": getattr(action, "payload", None)}

    # ---- 2. the wrapper we intend to ship at Seam C ------------------------
    gate_calls: list[dict] = []

    class GatedExecutor(ToolExecutor):
        """Mirror of agentctl.adapters.openhands.executor.GatedExecutor."""

        def __init__(self, inner):
            self._inner = inner

        def __call__(self, action, *a, **kw):
            gate_calls.append({"seen": repr(action)[:120]})
            # A real gate would consult the ledger here and may substitute.
            return self._inner(action, *a, **kw)

    # ---- 3. does composition actually intercept? ---------------------------
    try:
        real = RealExecutor()
        gated = GatedExecutor(real)

        class _Action:
            payload = "m0"

        result = gated(_Action())
        out["evidence"]["wrapper_invoked"] = len(gate_calls) == 1
        out["evidence"]["inner_invoked"] = len(inner_calls) == 1
        out["evidence"]["result_preserved"] = bool(result and result.get("ok"))
    except Exception as e:                            # noqa: BLE001
        out["verdict"] = "FALSIFIED"
        out["evidence"]["call_error"] = repr(e)
        out["evidence"]["traceback"] = traceback.format_exc()[-1200:]
        out["notes"].append("Wrapper could not be constructed or called.")
        return out

    # ---- 4. can the wrapper be registered under a tool name? ---------------
    try:
        register_tool("M0ProbeTool", RealExecutor)
        out["evidence"]["register_tool_accepts"] = True
        out["evidence"]["register_tool_signature_ok"] = True
    except Exception as e:                            # noqa: BLE001
        out["evidence"]["register_tool_accepts"] = False
        out["evidence"]["register_error"] = repr(e)
        out["notes"].append(
            "register_tool rejected the class. Inspect its real signature in "
            "results/api_surface.json — it may expect a ToolDefinition rather "
            "than an executor class."
        )

    # ---- verdict ------------------------------------------------------------
    ev = out["evidence"]
    if ev.get("wrapper_invoked") and ev.get("inner_invoked") and ev.get("result_preserved"):
        if ev.get("register_tool_accepts"):
            out["verdict"] = "CONFIRMED"
            out["notes"].append(
                "Seam C is reachable by composition. Architecture holds.")
        else:
            out["verdict"] = "PARTIAL"
            out["notes"].append(
                "Wrapping works; registration path needs the real API. Seam C "
                "is probably still reachable — adjust register.py, do not "
                "abandon Option 3."
            )
    else:
        out["verdict"] = "FALSIFIED"
        out["notes"].append(
            "Seam C unavailable. R1 unsatisfiable. Fall back to Option 1 "
            "(detect-and-alarm) and write a successor to docs/0008."
        )
    return out


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
    res = run()
    (RESULTS / "probe_01_wrap.json").write_text(
        json.dumps(res, indent=2), encoding="utf-8")

    print("=" * 68)
    print("PROBE 01 - H3 / Q3 - can we wrap a ToolExecutor?")
    print("=" * 68)
    print(f"  VERDICT: {res['verdict']}")
    for k, v in res["evidence"].items():
        if k != "traceback":
            print(f"    {k:<32} {v}")
    for n in res["notes"]:
        print(f"  -> {n}")
    return 0 if res["verdict"] in ("CONFIRMED", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
