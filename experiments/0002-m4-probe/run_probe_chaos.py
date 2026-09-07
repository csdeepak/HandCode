"""M4 acceptance — does the git probe resolve an ambiguous commit automatically?

M2a made dangerous effects fail closed. That is correct but annoying: every
ambiguous `git commit` needs a human. M4 asks the world instead.

    RUN 1   gate captures HEAD -> tool commits -> hard kill before the observation
    RUN 2   resume. gate sees INTENT + NON_IDEMPOTENT_WRITE
            git probe: HEAD moved -> LANDED
            record reconciles to COMMITTED. No human involved.
    ASSERT  exactly ONE commit, and the ledger is not BLOCKED

Compare with M2a on the same scenario, where the record ended BLOCKED.

Zero cost — local mock provider, no API key.

    python run_probe_chaos.py
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

MARKER = "tool_entered.marker"
LEDGER = "ledger.db"
SLEEP_S = 6.0
TIMEOUT_S = 120.0

MATRIX = {
    "version": 1,
    "defaults": {"unknown_tool": "EXTERNAL"},
    "tools": {"commit": {"class": "NON_IDEMPOTENT_WRITE", "probe": "git"}},
}


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo),
                          capture_output=True, text=True)


def commit_count(repo: Path) -> int:
    r = git(repo, "rev-list", "--count", "HEAD")
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else 0


# ══════════════════════════════════════════════════════════════════════
# CHILD
# ══════════════════════════════════════════════════════════════════════
def child(mode: str, workspace: Path, base_url: str) -> int:
    sys.path.insert(0, str(M0))
    sys.path.insert(0, str(HERE))

    import m4_tool

    from agentctl.adapters.openhands.seam_b import OpenHandsContext, SeamB
    from agentctl.kernel.classify import Classifier
    from agentctl.kernel.gate import EffectGate
    from agentctl.kernel.ledger.store import LedgerStore
    from agentctl.kernel.reconcile import GitProbe, ProbeRegistry
    from openhands.sdk import LLM, Agent, Conversation
    from openhands.sdk.tool import Tool

    repo = workspace / "repo"
    os.environ[m4_tool.REPO_ENV] = str(repo)
    os.environ[m4_tool.MARKER_ENV] = str(workspace / MARKER)
    os.environ[m4_tool.SLEEP_ENV] = str(SLEEP_S)
    m4_tool.register()

    llm = LLM(model="openai/mock-model", api_key="not-needed", base_url=base_url,
              service_id="m4", temperature=0.0, num_retries=1)
    agent = Agent(llm=llm, tools=[Tool(name=m4_tool.TOOL_NAME,
                                   params={"repo": str(repo)})],
                  include_default_tools=[])

    cid_file = workspace / "conversation_id.txt"
    if mode == "fresh":
        cid = uuid.uuid4()
        cid_file.write_text(str(cid), encoding="utf-8")
    else:
        cid = uuid.UUID(cid_file.read_text(encoding="utf-8").strip())

    store = LedgerStore(workspace / LEDGER, holder=f"m4-{mode}")
    gate = EffectGate(
        store,
        Classifier(matrix=MATRIX),
        probes=ProbeRegistry(GitProbe(repo)),
        fence=store.acquire(str(cid), takeover=(mode == "resume")),
    )

    decisions: list[dict] = []

    def record(call, decision):
        decisions.append({"tool": call.tool_name, "verdict": decision.verdict.value,
                          "reason": decision.reason})
        (workspace / f"decisions_{mode}.json").write_text(
            json.dumps(decisions, indent=2), encoding="utf-8")

    seam = SeamB(gate, OpenHandsContext(str(cid)), on_decision=record)
    conv = Conversation(agent=agent, workspace=str(workspace / "ws"),
                        persistence_dir=str(workspace / "state"),
                        conversation_id=cid, delete_on_close=False,
                        stuck_detection=False, callbacks=[seam])
    seam.attach(conv)

    if mode == "fresh":
        conv.send_message(f"Call the {m4_tool.TOOL_NAME} tool once.")
    conv.run()
    store.close()
    return 0


# ══════════════════════════════════════════════════════════════════════
# PARENT
# ══════════════════════════════════════════════════════════════════════
def _spawn(mode: str, ws: Path, base_url: str) -> subprocess.Popen:
    env = {**os.environ, "OPENHANDS_SUPPRESS_BANNER": "1", "PYTHONIOENCODING": "utf-8"}
    out = (ws / f"child_{mode}.out").open("w", encoding="utf-8", errors="replace")
    err = (ws / f"child_{mode}.err").open("w", encoding="utf-8", errors="replace")
    p = subprocess.Popen(
        [sys.executable, str(HERE / "run_probe_chaos.py"), "--child", mode,
         "--workspace", str(ws), "--base-url", base_url],
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


def parent() -> dict:
    sys.path.insert(0, str(M0))
    from mock_provider import MockProvider

    from agentctl.kernel.ledger.store import LedgerStore

    out: dict = {"verdict": "UNKNOWN", "evidence": {}, "notes": []}
    ws = Path(tempfile.mkdtemp(prefix="m4_"))
    out["evidence"]["workspace"] = str(ws)

    repo = ws / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "m4@example.com")
    git(repo, "config", "user.name", "m4")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "initial")
    out["evidence"]["commits_before"] = commit_count(repo)

    with MockProvider() as mock:
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
                "The tool was never entered -- HARNESS FAILURE, not a result.")
            return out

        time.sleep(0.6)
        p1.kill()
        try:
            p1.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        out["evidence"]["commits_after_crash"] = commit_count(repo)

        (ws / MARKER).unlink(missing_ok=True)
        p2 = _spawn("resume", ws, mock.base_url)
        try:
            p2.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            p2.kill()
        out["evidence"]["commits_after_resume"] = commit_count(repo)

    store = LedgerStore(ws / LEDGER, holder="inspect")
    cid = (ws / "conversation_id.txt").read_text(encoding="utf-8").strip()
    recs = store._db.execute(
        "SELECT tool_name, state, probe_verdict, error FROM effect_record "
        "WHERE conversation_id=?", (cid,)).fetchall()
    out["evidence"]["ledger"] = [
        {"tool": r["tool_name"], "state": r["state"],
         "probe": r["probe_verdict"], "error": (r["error"] or "")[:80]} for r in recs]
    out["evidence"]["blocked_count"] = len(store.blocked(cid))
    store.close()

    for mode in ("fresh", "resume"):
        f = ws / f"decisions_{mode}.json"
        if f.exists():
            out["evidence"][f"decisions_{mode}"] = json.loads(f.read_text(encoding="utf-8"))

    # ══ verdict ═══════════════════════════════════════════════════
    before = out["evidence"]["commits_before"]
    crash = out["evidence"].get("commits_after_crash")
    resume = out["evidence"].get("commits_after_resume")
    states = [r["state"] for r in out["evidence"]["ledger"]]
    probes = [r["probe"] for r in out["evidence"]["ledger"] if r["probe"]]

    if crash != before + 1:
        out["verdict"] = "INCONCLUSIVE"
        out["notes"].append(
            f"Expected one new commit before the crash ({before} -> {before+1}), "
            f"saw {crash}. The scenario did not reproduce.")
    elif resume == crash and "COMMITTED" in states and "LANDED" in probes:
        out["verdict"] = "PASS"
        out["notes"].append(
            "The probe resolved the ambiguity automatically: HEAD had moved, so "
            "the effect was reconciled to COMMITTED and never repeated.")
        out["notes"].append(
            "Compare M2a on this scenario: the record ended BLOCKED and needed a "
            "human. M4 needs nobody.")
    elif resume > crash:
        out["verdict"] = "FAIL"
        out["notes"].append(
            f"The commit was repeated ({crash} -> {resume}). The probe returned "
            f"{probes or 'nothing'} when it should have said LANDED.")
    else:
        out["verdict"] = "INCONCLUSIVE"
        out["notes"].append(
            f"commits {before}->{crash}->{resume}, states={states}, probes={probes}")
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
    (RESULTS / "probe_chaos.json").write_text(json.dumps(res, indent=2), encoding="utf-8")

    print("=" * 70)
    print("M4 ACCEPTANCE - does the git probe resolve the ambiguity alone?")
    print("=" * 70)
    print(f"  VERDICT: {res['verdict']}")
    for k in ("commits_before", "commits_after_crash", "commits_after_resume",
              "blocked_count"):
        if k in res["evidence"]:
            print(f"    {k:<24} {res['evidence'][k]}")
    for r in res["evidence"].get("ledger", []):
        print(f"    ledger: {r['tool']} state={r['state']} probe={r['probe']}")
    for d in res["evidence"].get("decisions_resume", []):
        print(f"    resume: {d['verdict']} - {d['reason']}")
    print()
    for n in res["notes"]:
        print(f"  -> {n}")
    print(f"\n  workspace: {res['evidence'].get('workspace')}")
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
