"""
Probe 01 — H3 / Q3: can a ToolExecutor be wrapped without forking?

The single highest-risk assumption in `docs/0008`. If this fails, Seam C does
not exist, requirement R1 is unsatisfiable, and the architecture is dead.

Written against the REAL SDK API discovered by probe_00. `docs/0012` §4 assumed
you subclass ToolExecutor and re-register it; in fact `ToolDefinition` carries
the executor in a FIELD, so Seam C binds by replacing that field — less
invasive than designed.

No network, no API key.

    python probe_01_wrap.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

RESULTS = Path(__file__).parent / "results"


def run() -> dict:
    out: dict = {"hypothesis": "H3", "question": "Q3", "verdict": "UNKNOWN",
                 "evidence": {}, "notes": []}
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        import m0_tool
        from openhands.sdk.tool import ToolExecutor
        from openhands.sdk.tool.registry import list_registered_tools, resolve_tool
    except Exception as e:                            # noqa: BLE001
        out["verdict"] = "ERROR"
        out["evidence"]["import_error"] = repr(e)
        out["notes"].append("Run probe_00_api.py first - the SDK import failed.")
        return out

    tmp = Path(tempfile.mkdtemp(prefix="m0_wrap_"))
    gate_calls: list[str] = []

    class GatedExecutor(ToolExecutor):
        """Seam C. Mirrors agentctl.adapters.openhands.executor."""

        def __init__(self, inner):
            self._inner = inner

        def __call__(self, action, conversation=None):
            gate_calls.append(getattr(action, "payload", "?"))
            # A real gate consults the ledger here and may substitute.
            return self._inner(action, conversation)

    try:
        # 1. build a real ToolDefinition
        tool = m0_tool.SideEffectTool.create(
            log_path=tmp / "se.log", marker=tmp / "mk", sleep_s=0.01)[0]
        out["evidence"]["tool_built"] = True
        out["evidence"]["inner_executor"] = type(tool.executor).__name__

        # 2. bind Seam C by replacing the executor field
        gated = tool.model_copy(update={"executor": GatedExecutor(tool.executor)})
        obs = gated.executor(m0_tool.SideEffectAction(payload="probe"), None)

        out["evidence"]["wrapper_invoked"] = gate_calls == ["probe"]
        out["evidence"]["inner_invoked"] = (tmp / "se.log").exists()
        out["evidence"]["result_preserved"] = getattr(obs, "status", None) == "ok"

        # 3. the tool can be registered under a name the agent can request
        m0_tool.register()
        out["evidence"]["register_tool_accepts"] = \
            m0_tool.TOOL_NAME in list_registered_tools()
        out["evidence"]["resolve_tool_available"] = callable(resolve_tool)
    except Exception as e:                            # noqa: BLE001
        out["verdict"] = "FALSIFIED"
        out["evidence"]["error"] = repr(e)
        out["evidence"]["traceback"] = traceback.format_exc()[-1500:]
        out["notes"].append("Seam C could not be bound. See traceback.")
        return out

    ev = out["evidence"]
    if all(ev.get(k) for k in ("wrapper_invoked", "inner_invoked",
                               "result_preserved", "register_tool_accepts")):
        out["verdict"] = "CONFIRMED"
        out["notes"].append(
            "Seam C is reachable by replacing ToolDefinition.executor. No fork. "
            "The architecture in docs/0008 holds.")
        out["notes"].append(
            "CORRECTION to docs/0012 section 4: bind by wrapping the executor "
            "FIELD on a resolved ToolDefinition, not by subclassing ToolExecutor "
            "and re-registering. Simpler and less invasive than designed.")
    else:
        out["verdict"] = "FALSIFIED"
        out["notes"].append(
            "Seam C unavailable. R1 unsatisfiable. Fall back to Option 1 "
            "(detect-and-alarm) and write a successor to docs/0008.")
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
            print(f"    {k:<28} {v}")
    for n in res["notes"]:
        print(f"  -> {n}")
    return 0 if res["verdict"] in ("CONFIRMED", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
