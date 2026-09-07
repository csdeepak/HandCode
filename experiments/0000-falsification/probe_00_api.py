"""
Probe 00 — discover the real SDK surface.

RUN THIS FIRST.

The rest of the spike is written against an SDK API taken from documentation
and examples, not from execution. This probe reports what is *actually*
installed, so a signature mismatch shows up as a clear report line instead of a
confusing traceback three scripts later.

It also captures exact installed versions, which `docs/0009` R1 requires for
any result to be interpretable later.

    python probe_00_api.py
"""
from __future__ import annotations

import importlib
import inspect
import json
import platform
import sys
from pathlib import Path

RESULTS = Path(__file__).parent / "results"

# (module, [symbols]) — what the later probes expect to import.
EXPECTED = [
    ("openhands.sdk.tool", ["Tool", "ToolExecutor", "register_tool"]),
    ("openhands.sdk", ["LLM", "Agent", "Conversation"]),
]

VERSION_PKGS = [
    "openhands-sdk", "openhands-agent-server", "openhands-tools",
    "litellm", "pydantic", "httpx",
]


def _versions() -> dict[str, str]:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:
        return {}
    out = {}
    for p in VERSION_PKGS:
        try:
            out[p] = version(p)
        except PackageNotFoundError:
            out[p] = "NOT INSTALLED"
        except Exception as e:                       # noqa: BLE001
            out[p] = f"error: {e}"
    return out


def _describe(obj) -> dict:
    d: dict = {"kind": type(obj).__name__}
    try:
        d["signature"] = str(inspect.signature(obj))
    except (TypeError, ValueError):
        d["signature"] = "<not introspectable>"
    if inspect.isclass(obj):
        d["methods"] = sorted(
            n for n, _ in inspect.getmembers(obj, callable)
            if not n.startswith("_")
        )[:40]
        try:
            d["init"] = str(inspect.signature(obj.__init__))
        except (TypeError, ValueError):
            d["init"] = "<not introspectable>"
    return d


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
    report: dict = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "versions": _versions(),
        "modules": {},
        "missing": [],
    }

    for mod_name, symbols in EXPECTED:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:                        # noqa: BLE001
            report["modules"][mod_name] = {"import_error": repr(e)}
            report["missing"].append(f"{mod_name} (import failed)")
            continue

        entry: dict = {"file": getattr(mod, "__file__", "?"), "symbols": {}}
        for sym in symbols:
            obj = getattr(mod, sym, None)
            if obj is None:
                report["missing"].append(f"{mod_name}.{sym}")
                entry["symbols"][sym] = {"present": False}
            else:
                entry["symbols"][sym] = {"present": True, **_describe(obj)}
        entry["exports"] = sorted(
            n for n in dir(mod) if not n.startswith("_")
        )[:60]
        report["modules"][mod_name] = entry

    # Where does persisted conversation state live? The crash probe needs this.
    try:
        conv = importlib.import_module("openhands.sdk").Conversation
        report["conversation_init"] = str(inspect.signature(conv.__init__))
    except Exception as e:                            # noqa: BLE001
        report["conversation_init"] = f"unavailable: {e!r}"

    (RESULTS / "api_surface.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")

    ok = not report["missing"]
    print("=" * 68)
    print("PROBE 00 - SDK API SURFACE")
    print("=" * 68)
    for pkg, ver in report["versions"].items():
        print(f"  {pkg:<28} {ver}")
    print()
    if ok:
        print("  OK - every expected symbol is present.")
        print(f"  Conversation.__init__{report['conversation_init']}")
    else:
        print("  MISMATCH - the spike's assumptions do not hold:")
        for m in report["missing"]:
            print(f"    missing: {m}")
        print("\n  Send results/api_surface.json back before running probes 01-03;")
        print("  the later scripts need adjusting to the real API.")
    print(f"\n  written: {RESULTS / 'api_surface.json'}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
