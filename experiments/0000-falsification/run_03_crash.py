"""
Probe 03 — H1/Q1 (double execution) and H2/Q2 (tool_call_id stability).

Also answers H4/Q13 as a side effect: the mock records which URL path the SDK
actually called.

Design: a parent orchestrates two child processes against a local mock
provider. The child runs an agent whose only tool appends a line to a log file
and then sleeps. The parent hard-kills the child during that sleep — after the
side effect has landed, before the ObservationEvent is written. That is exactly
the ambiguous state in `docs/0008` §6.5.

    python run_03_crash.py            # parent (what you want)
    python run_03_crash.py --child fresh --workspace DIR --base-url URL
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
RESULTS = HERE / "results"

SIDE_EFFECT_LOG = "side_effect.log"
MARKER = "tool_entered.marker"
SLEEP_S = 6.0          # crash window
POLL_TIMEOUT_S = 90.0


# ══════════════════════════════════════════════════════════════════════
# CHILD
# ══════════════════════════════════════════════════════════════════════
def child(mode: str, workspace: Path, base_url: str) -> int:
    """Run (or resume) one conversation. Killed mid-tool by the parent."""
    import uuid as _uuid

    sys.path.insert(0, str(HERE))
    import m0_tool
    from openhands.sdk import LLM, Agent, Conversation
    from openhands.sdk.tool import Tool

    m0_tool.register()

    llm = LLM(model="openai/mock-model", api_key="not-needed",
              base_url=base_url, service_id="m0", temperature=0.0,
              num_retries=1, retry_min_wait=1, retry_max_wait=2)
    agent = Agent(llm=llm, tools=[Tool(name=m0_tool.TOOL_NAME, params={
        "log_path": str(workspace / SIDE_EFFECT_LOG),
        "marker": str(workspace / MARKER),
        "sleep_s": SLEEP_S,
    })], include_default_tools=[])

    persist = workspace / "state"
    cid_file = workspace / "conversation_id.txt"

    if mode == "fresh":
        cid = _uuid.uuid4()
        cid_file.write_text(str(cid), encoding="utf-8")
        conv = Conversation(agent=agent, workspace=str(workspace / "ws"),
                            persistence_dir=str(persist), conversation_id=cid,
                            delete_on_close=False, stuck_detection=False)
        conv.send_message(f"Call the {m0_tool.TOOL_NAME} tool once with payload m0-spike.")
        conv.run()
    else:
        cid = _uuid.UUID(cid_file.read_text(encoding="utf-8").strip())
        conv = Conversation(agent=agent, workspace=str(workspace / "ws"),
                            persistence_dir=str(persist), conversation_id=cid,
                            delete_on_close=False, stuck_detection=False)
        conv.run()
    return 0


# ══════════════════════════════════════════════════════════════════════
# PARENT
# ══════════════════════════════════════════════════════════════════════
def _spawn(mode: str, workspace: Path, base_url: str) -> subprocess.Popen:
    """Child output goes to FILES, never to an undrained PIPE.

    The SDK's visualizer is verbose enough to fill a pipe buffer, which blocks
    the child until someone reads it -- the parent is polling for a marker at
    that moment, so it deadlocks and times out. Files avoid it entirely.
    """
    env = {**os.environ, "OPENHANDS_SUPPRESS_BANNER": "1", "PYTHONIOENCODING": "utf-8"}
    out = (workspace / f"child_{mode}.out").open("w", encoding="utf-8", errors="replace")
    err = (workspace / f"child_{mode}.err").open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, str(HERE / "run_03_crash.py"),
         "--child", mode, "--workspace", str(workspace), "--base-url", base_url],
        stdout=out, stderr=err, env=env,
    )
    proc._m0_files = (out, err)          # keep handles alive
    return proc


def _child_log(workspace: Path, mode: str, stream: str) -> str:
    p = workspace / f"child_{mode}.{stream}"
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def _wait_for(path: Path, timeout: float, proc: subprocess.Popen) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if path.exists():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.05)
    return False


def _read_events(workspace: Path) -> list[dict]:
    """Load every persisted event JSON, wherever the SDK put it."""
    events = []
    for p in sorted((workspace / "state").rglob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:                              # noqa: BLE001
            continue
        events.append({"file": p.name, "data": data})
    return events


def _find_tool_call_ids(events: list[dict]) -> list[str]:
    """Pull any tool_call_id-ish field out of the persisted events."""
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("tool_call_id", "toolCallId", "id") and isinstance(v, str) \
                        and v.startswith("call_"):
                    found.append(v)
                walk(v)
        elif isinstance(node, list):
            for i in node:
                walk(i)

    for e in events:
        walk(e["data"])
    return found


def _count_effects(workspace: Path) -> int:
    p = workspace / SIDE_EFFECT_LOG
    if not p.exists():
        return 0
    return sum(1 for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("EFFECT"))


def parent() -> dict:
    import tempfile
    from mock_provider import MockProvider

    out: dict = {"hypotheses": ["H1", "H2", "H4"],
                 "questions": ["Q1", "Q2", "Q13"],
                 "verdicts": {}, "evidence": {}, "notes": []}

    workspace = Path(tempfile.mkdtemp(prefix="m0_crash_"))
    out["evidence"]["workspace"] = str(workspace)

    with MockProvider() as mock:
        base_url = mock.base_url
        out["evidence"]["base_url"] = base_url

        # ---- RUN 1: crash mid-tool -------------------------------------
        p1 = _spawn("fresh", workspace, base_url)
        entered = _wait_for(workspace / MARKER, POLL_TIMEOUT_S, p1)

        if not entered:
            try:
                p1.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p1.kill()
            out["verdicts"] = {h: "ERROR" for h in out["hypotheses"]}
            out["evidence"]["run1_stdout"] = _child_log(workspace, "fresh", "out")[-2500:]
            out["evidence"]["run1_stderr"] = _child_log(workspace, "fresh", "err")[-2500:]
            out["notes"].append(
                "The tool was never entered. Usually an SDK API mismatch — "
                "check results/api_surface.json and the stderr above.")
            return out

        time.sleep(0.6)                    # firmly inside the sleep window
        p1.kill()
        try:
            p1.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

        effects_after_crash = _count_effects(workspace)
        events_before = _read_events(workspace)
        ids_before = _find_tool_call_ids(events_before)
        out["evidence"]["effects_after_crash"] = effects_after_crash
        out["evidence"]["tool_call_ids_before"] = sorted(set(ids_before))
        out["evidence"]["event_files_before"] = len(events_before)

        # ---- RUN 2: resume ---------------------------------------------
        (workspace / MARKER).unlink(missing_ok=True)
        p2 = _spawn("resume", workspace, base_url)
        try:
            p2.wait(timeout=POLL_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            p2.kill()
        out["evidence"]["run2_stderr_tail"] = _child_log(workspace, "resume", "err")[-1500:]

        effects_after_resume = _count_effects(workspace)
        ids_after = _find_tool_call_ids(_read_events(workspace))
        out["evidence"]["effects_after_resume"] = effects_after_resume
        out["evidence"]["tool_call_ids_after"] = sorted(set(ids_after))

        # ---- H4 / Q13: which endpoint? ---------------------------------
        paths = [r["path"] for r in mock.requests if r["method"] == "POST"]
        out["evidence"]["endpoint_paths"] = sorted(set(paths))
        out["evidence"]["anthropic_shaped_calls"] = sum(
            1 for r in mock.requests if r.get("anthropic_shaped"))

    # ══ verdicts ═══════════════════════════════════════════════════════
    # H1 — double execution
    if effects_after_crash == 1 and effects_after_resume == 2:
        out["verdicts"]["H1"] = "CONFIRMED"
        out["notes"].append(
            "Double execution reproduced. docs/0007's BUILD verdict stands; "
            "the Effect Ledger is the product.")
    elif effects_after_crash == 1 and effects_after_resume == 1:
        out["verdicts"]["H1"] = "FALSIFIED"
        out["notes"].append(
            "No re-execution on resume. An executor-level guard may already "
            "exist — docs/0007 needs revisiting and the ledger may reduce to "
            "an audit layer. Verify the resume actually replayed the action "
            "before concluding.")
    else:
        out["verdicts"]["H1"] = "INCONCLUSIVE"
        out["notes"].append(
            f"Unexpected counts (crash={effects_after_crash}, "
            f"resume={effects_after_resume}). Inspect the workspace by hand.")

    # H2 — tool_call_id stability
    before, after = set(ids_before), set(ids_after)
    if before and before <= after:
        out["verdicts"]["H2"] = "CONFIRMED"
        out["notes"].append(
            "tool_call_id survived the crash. The ledger's primary key "
            "(docs/0012 §2.1) is valid.")
    elif not before:
        out["verdicts"]["H2"] = "INCONCLUSIVE"
        out["notes"].append(
            "No tool_call_id found in persisted events — the extractor may be "
            "looking for the wrong field. Inspect the state directory.")
    else:
        out["verdicts"]["H2"] = "FALSIFIED"
        out["notes"].append(
            "tool_call_id changed across resume. The ledger must be re-keyed "
            "on action_event_id or a content hash. docs/0012 §2.1 is invalid.")

    # H4 — endpoint format
    if any("chat/completions" in p for p in out["evidence"]["endpoint_paths"]):
        out["verdicts"]["H4"] = "CONFIRMED"
        out["notes"].append("OpenAI-format endpoint in use. Seam A hooks will fire.")
    elif any("messages" in p for p in out["evidence"]["endpoint_paths"]):
        out["verdicts"]["H4"] = "FALSIFIED"
        out["notes"].append(
            "Anthropic /v1/messages endpoint in use. LiteLLM #27518 means Seam A "
            "hooks are SILENTLY bypassed. M1 must force the OpenAI format.")
    else:
        out["verdicts"]["H4"] = "INCONCLUSIVE"
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", choices=["fresh", "resume"])
    ap.add_argument("--workspace")
    ap.add_argument("--base-url")
    args = ap.parse_args()

    if args.child:
        sys.path.insert(0, str(HERE))
        return child(args.child, Path(args.workspace), args.base_url)

    sys.path.insert(0, str(HERE))
    RESULTS.mkdir(exist_ok=True)
    res = parent()
    (RESULTS / "probe_03_crash.json").write_text(
        json.dumps(res, indent=2), encoding="utf-8")

    print("=" * 68)
    print("PROBE 03 - H1/Q1 double execution - H2/Q2 id stability - H4/Q13 endpoint")
    print("=" * 68)
    for h, v in res["verdicts"].items():
        print(f"  {h}: {v}")
    print()
    for k in ("effects_after_crash", "effects_after_resume",
              "tool_call_ids_before", "tool_call_ids_after", "endpoint_paths"):
        if k in res["evidence"]:
            print(f"    {k:<26} {res['evidence'][k]}")
    print()
    for n in res["notes"]:
        print(f"  -> {n}")
    print(f"\n  workspace kept for inspection: {res['evidence'].get('workspace')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
