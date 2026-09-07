"""M2a acceptance test — does the gate actually prevent a duplicate effect?

M0 proved the disease: a side-effecting tool re-executes after crash + resume
(`docs/0014`). This proves the cure, end to end, against the real SDK:

    RUN 1   gate writes INTENT -> tool runs -> hard kill before the observation
    RUN 2   resume with the gate installed
            gate sees INTENT + NON_IDEMPOTENT_WRITE + no probe -> BLOCK
            block_action() stops the agent re-executing
    ASSERT  the side effect happened exactly ONCE

It also answers `docs/0009` Q16 empirically: `block_action` was read from
source in `0015` but never executed. Here it is executed.

Zero cost — local mock provider, no API key.

    python run_chaos.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).parent
M0 = HERE.parent / "0000-falsification"
RESULTS = HERE / "results"

SIDE_EFFECT_LOG = "side_effect.log"
MARKER = "tool_entered.marker"
LEDGER = "ledger.db"
SLEEP_S = 6.0
TIMEOUT_S = 120.0

# The tool is deliberately classified dangerous, so an ambiguous INTENT must
# fail closed rather than re-execute.
MATRIX = {
    "version": 1,
    "defaults": {"unknown_tool": "EXTERNAL"},
    "tools": {"side_effect": {"class": "NON_IDEMPOTENT_WRITE"}},
}


# ══════════════════════════════════════════════════════════════════════
# CHILD
# ══════════════════════════════════════════════════════════════════════
def child(mode: str, workspace: Path, base_url: str) -> int:
    sys.path.insert(0, str(M0))
    import m0_tool

    from agentctl.adapters.openhands.seam_b import OpenHandsContext, SeamB
    from agentctl.kernel.classify import Classifier
    from agentctl.kernel.gate import EffectGate
    from agentctl.kernel.ledger.store import LedgerStore
    from openhands.sdk import LLM, Agent, Conversation
    from openhands.sdk.tool import Tool

    m0_tool.register()

    llm = LLM(model="openai/mock-model", api_key="not-needed", base_url=base_url,
              service_id="m2a", temperature=0.0, num_retries=1)
    agent = Agent(llm=llm, tools=[Tool(name=m0_tool.TOOL_NAME, params={
        "log_path": str(workspace / SIDE_EFFECT_LOG),
        "marker": str(workspace / MARKER),
        "sleep_s": SLEEP_S,
    })], include_default_tools=[])

    cid_file = workspace / "conversation_id.txt"
    if mode == "fresh":
        cid = uuid.uuid4()
        cid_file.write_text(str(cid), encoding="utf-8")
    else:
        cid = uuid.UUID(cid_file.read_text(encoding="utf-8").strip())

    # ── build the gate, then hand Seam B in at construction ─────────
    store = LedgerStore(workspace / LEDGER, holder=f"m2a-{mode}")
    gate = EffectGate(store, Classifier(matrix=MATRIX),
                      fence=store.acquire(str(cid), takeover=(mode == "resume")))

    decisions: list[dict] = []

    def record(call, decision):
        decisions.append({
            "tool": call.tool_name,
            "verdict": decision.verdict.value,
            "class": decision.effect_class.value if decision.effect_class else None,
            "reason": decision.reason,
        })
        (workspace / f"decisions_{mode}.json").write_text(
            json.dumps(decisions, indent=2), encoding="utf-8")

    # Two-step: callbacks are passed at construction, but the callback needs
    # the conversation it is attached to.
    seam = SeamB(gate, OpenHandsContext(str(cid)), on_decision=record)
    conv = Conversation(agent=agent, workspace=str(workspace / "ws"),
                        persistence_dir=str(workspace / "state"),
                        conversation_id=cid, delete_on_close=False,
                        stuck_detection=False, callbacks=[seam])
    seam.attach(conv)

    if mode == "fresh":
        conv.send_message(f"Call the {m0_tool.TOOL_NAME} tool once with payload m2a.")
    conv.run()
    store.close()
    return 0


# ══════════════════════════════════════════════════════════════════════
# PARENT
# ══════════════════════════════════════════════════════════════════════
def _spawn(mode: str, workspace: Path, base_url: str) -> subprocess.Popen:
    """Output to FILES, never an undrained pipe (docs/0014 §5)."""
    env = {**os.environ, "OPENHANDS_SUPPRESS_BANNER": "1", "PYTHONIOENCODING": "utf-8"}
    out = (workspace / f"child_{mode}.out").open("w", encoding="utf-8", errors="replace")
    err = (workspace / f"child_{mode}.err").open("w", encoding="utf-8", errors="replace")
    p = subprocess.Popen(
        [sys.executable, str(HERE / "run_chaos.py"), "--child", mode,
         "--workspace", str(workspace), "--base-url", base_url],
        stdout=out, stderr=err, env=env)
    p._files = (out, err)
    return p


def _wait_for(path: Path, timeout: float, proc) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if path.exists():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.05)
    return False


def _effects(workspace: Path) -> int:
    p = workspace / SIDE_EFFECT_LOG
    if not p.exists():
        return 0
    return sum(1 for ln in p.read_text(encoding="utf-8").splitlines()
               if ln.startswith("EFFECT"))


def parent() -> dict:
    sys.path.insert(0, str(M0))
    from mock_provider import MockProvider

    out: dict = {"verdict": "UNKNOWN", "evidence": {}, "notes": []}
    ws = Path(tempfile.mkdtemp(prefix="m2a_"))
    out["evidence"]["workspace"] = str(ws)

    with MockProvider() as mock:
        # ---- RUN 1: crash mid-tool ---------------------------------
        p1 = _spawn("fresh", ws, mock.base_url)
        if not _wait_for(ws / MARKER, TIMEOUT_S, p1):
            try:
                p1.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p1.kill()
            out["verdict"] = "INCONCLUSIVE"
            out["evidence"]["run1_stderr"] = (ws / "child_fresh.err").read_text(
                encoding="utf-8", errors="replace")[-2500:]
            out["notes"].append(
                "The tool was never entered -- HARNESS FAILURE, not a result. "
                "docs/0012 §6: a timeout is never a verdict.")
            return out

        time.sleep(0.6)
        p1.kill()
        try:
            p1.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

        after_crash = _effects(ws)
        out["evidence"]["effects_after_crash"] = after_crash

        # ---- RUN 2: resume with the gate ---------------------------
        (ws / MARKER).unlink(missing_ok=True)
        p2 = _spawn("resume", ws, mock.base_url)
        try:
            p2.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            p2.kill()

        after_resume = _effects(ws)
        out["evidence"]["effects_after_resume"] = after_resume

    # ---- ledger + decision evidence --------------------------------
    from agentctl.kernel.ledger.store import LedgerStore
    store = LedgerStore(ws / LEDGER, holder="inspect")
    cid = (ws / "conversation_id.txt").read_text(encoding="utf-8").strip()
    out["evidence"]["ledger_blocked"] = [
        {"tool": r.tool_name, "state": r.state.value, "class": r.effect_class.value,
         "reason": (r.error or "")[:110]} for r in store.blocked(cid)]
    out["evidence"]["ledger_pending"] = len(store.pending(cid))
    store.close()

    for mode in ("fresh", "resume"):
        f = ws / f"decisions_{mode}.json"
        if f.exists():
            out["evidence"][f"decisions_{mode}"] = json.loads(f.read_text(encoding="utf-8"))

    # ══ verdict ═══════════════════════════════════════════════════
    verdicts = [d["verdict"] for d in out["evidence"].get("decisions_resume", [])]
    blocked_on_resume = any(v in ("BLOCK", "ESCALATE") for v in verdicts)

    if after_crash != 1:
        out["verdict"] = "INCONCLUSIVE"
        out["notes"].append(
            f"Expected exactly 1 effect before the crash, saw {after_crash}. "
            "The harness did not reproduce the scenario.")
    elif after_resume == 1 and blocked_on_resume:
        out["verdict"] = "PASS"
        out["notes"].append(
            "The gate prevented the duplicate. M0 showed 2 effects here; with "
            "the gate installed there is 1.")
        out["notes"].append(
            "docs/0009 Q16 RESOLVED empirically: block_action does prevent "
            "execution, not merely record disapproval.")
    elif after_resume == 2:
        out["verdict"] = "FAIL"
        out["notes"].append(
            "The effect ran twice. Either block_action does not prevent "
            "execution, or the gate did not see the action. Check "
            "decisions_resume and child_resume.err.")
    else:
        out["verdict"] = "INCONCLUSIVE"
        out["notes"].append(
            f"effects={after_resume}, blocked_on_resume={blocked_on_resume}. "
            "Inspect the workspace.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", choices=["fresh", "resume"])
    ap.add_argument("--workspace")
    ap.add_argument("--base-url")
    a = ap.parse_args()
    if a.child:
        return child(a.child, Path(a.workspace), a.base_url)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    RESULTS.mkdir(exist_ok=True)
    res = parent()
    (RESULTS / "chaos.json").write_text(json.dumps(res, indent=2), encoding="utf-8")

    print("=" * 70)
    print("M2a ACCEPTANCE - does the gate prevent a duplicate effect?")
    print("=" * 70)
    print(f"  VERDICT: {res['verdict']}")
    for k in ("effects_after_crash", "effects_after_resume", "ledger_pending"):
        if k in res["evidence"]:
            print(f"    {k:<24} {res['evidence'][k]}")
    for b in res["evidence"].get("ledger_blocked", []):
        print(f"    BLOCKED  {b['tool']} [{b['class']}] {b['reason']}")
    for d in res["evidence"].get("decisions_resume", []):
        print(f"    resume decision: {d['verdict']} ({d['class']})")
    print()
    for n in res["notes"]:
        print(f"  -> {n}")
    print(f"\n  workspace: {res['evidence'].get('workspace')}")
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
