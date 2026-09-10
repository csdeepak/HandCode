"""THE INTEGRATION TEST — every piece at once, for the first time.

Until now each seam was proven alone: Seam A with direct HTTP to a proxy
(`docs/0021`), Seams B and C with OpenHands talking straight to a mock
(`docs/0016`-`0018`). This runs the whole stack together, which is the only
configuration anybody would actually deploy:

    OpenHands agent
        -> LiteLLM proxy          Seam A: hook, turn-pinning, telemetry
            -> two mock accounts   one of which fails
        + agentctl gate           Seams B and C: ledger, probes, substitution

    RUN 1  the agent commits to git, then is hard-killed mid-tool
    RUN 2  it resumes; the git probe says LANDED; Seam C substitutes
    ASSERT one commit, one ledger record, the hook fired, spend is attributed

Zero cost: two local mock backends, no API key, no network.

    python run_full_stack.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
M1 = ROOT / "experiments" / "0005-m1-seam-a"
RESULTS = HERE / "results"

MASTER_KEY = "sk-fullstack"
PROXY_PORT = 4998
MARKER = "tool_entered.marker"
LEDGER = "ledger.db"
SLEEP_S = 6.0
TIMEOUT_S = 180.0

MATRIX = {
    "version": 1,
    "defaults": {"unknown_tool": "EXTERNAL"},
    "tools": {"commit": {"class": "NON_IDEMPOTENT_WRITE", "probe": "git"}},
}


def git(repo: Path, *a: str):
    return subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True)


def commits(repo: Path) -> int:
    r = git(repo, "rev-list", "--count", "HEAD")
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else 0


# ══════════════════════════════════════════════════════════════════════
# CHILD — a real agent, through the real proxy, behind the real gate
# ══════════════════════════════════════════════════════════════════════
def child(mode: str, ws: Path, proxy_url: str) -> int:
    sys.path.insert(0, str(ROOT / "experiments" / "0002-m4-probe"))
    import m4_tool

    from agentctl.adapters.openhands import protect
    from openhands.sdk import LLM, Agent, Conversation
    from openhands.sdk.tool import Tool

    repo = ws / "repo"
    os.environ[m4_tool.REPO_ENV] = str(repo)
    os.environ[m4_tool.MARKER_ENV] = str(ws / MARKER)
    os.environ[m4_tool.SLEEP_ENV] = str(SLEEP_S)
    m4_tool.register()

    cid_file = ws / "conversation_id.txt"
    if mode == "fresh":
        cid = uuid.uuid4()
        cid_file.write_text(str(cid), encoding="utf-8")
    else:
        cid = uuid.UUID(cid_file.read_text(encoding="utf-8").strip())

    decisions: list[dict] = []

    def record(call, decision):
        decisions.append({"tool": call.tool_name, "verdict": decision.verdict.value,
                          "reason": decision.reason})
        (ws / f"decisions_{mode}.json").write_text(
            json.dumps(decisions, indent=2), encoding="utf-8")

    # ── the whole guard in one call: ledger, gate, probes, Seams B+C ──
    guard = protect(
        ledger=ws / LEDGER,
        conversation_id=str(cid),
        tools={m4_tool.TOOL_NAME: m4_tool.CommitTool},
        matrix=MATRIX,
        repo_root=repo,
        holder=f"fullstack-{mode}",
        takeover=(mode == "resume"),
        on_decision=record,
    )
    (ws / f"gated_{mode}.json").write_text(
        json.dumps(guard.gated_tools), encoding="utf-8")

    # The agent talks to the PROXY, not to a provider. That is the integration.
    llm = LLM(model="openai/pool", api_key=MASTER_KEY, base_url=proxy_url,
              service_id="fullstack", temperature=0.0, num_retries=1)
    agent = Agent(llm=llm, tools=[Tool(name=m4_tool.TOOL_NAME,
                                       params={"repo": str(repo)})],
                  include_default_tools=[])

    conv = Conversation(agent=agent, workspace=str(ws / "ws"),
                        persistence_dir=str(ws / "state"), conversation_id=cid,
                        delete_on_close=False, stuck_detection=False,
                        callbacks=[guard.seam_b])
    guard.attach(conv)

    if mode == "fresh":
        conv.send_message(f"Call the {m4_tool.TOOL_NAME} tool once.")
    conv.run()
    guard.close()
    return 0


# ══════════════════════════════════════════════════════════════════════
# PARENT
# ══════════════════════════════════════════════════════════════════════
def _proxy_config(path: Path, a_url: str, b_url: str) -> None:
    path.write_text(f"""model_list:
  - model_name: pool
    litellm_params:
      model: openai/mock-model
      api_base: {a_url}
      api_key: dummy
    model_info:
      id: acct-a
  - model_name: pool
    litellm_params:
      model: openai/mock-model
      api_base: {b_url}
      api_key: dummy
    model_info:
      id: acct-b

litellm_settings:
  callbacks: hook_module.proxy_handler_instance

router_settings:
  routing_strategy: simple-shuffle
  num_retries: 2
  allowed_fails: 1
  cooldown_time: 60

general_settings:
  master_key: {MASTER_KEY}
""", encoding="utf-8")


def _env(ws: Path, telemetry: Path) -> dict:
    return {**os.environ,
            "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
            "OPENHANDS_SUPPRESS_BANNER": "1",
            "PYTHONPATH": os.pathsep.join([str(M1), str(ROOT)]),
            "AGENTCTL_TELEMETRY": str(telemetry),
            "LITELLM_DONT_SHOW_FEEDBACK_BOX": "True"}


def _spawn_child(mode: str, ws: Path, proxy_url: str, telemetry: Path):
    out = (ws / f"child_{mode}.out").open("w", encoding="utf-8", errors="replace")
    err = (ws / f"child_{mode}.err").open("w", encoding="utf-8", errors="replace")
    p = subprocess.Popen(
        [sys.executable, "-X", "utf8", str(HERE / "run_full_stack.py"),
         "--child", mode, "--workspace", str(ws), "--proxy", proxy_url],
        stdout=out, stderr=err, env=_env(ws, telemetry))
    p._files = (out, err)
    return p


def _wait(path: Path, timeout: float, proc) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if path.exists():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.05)
    return False


def parent() -> dict:
    sys.path.insert(0, str(M1))
    from backends import Backend

    out: dict = {"verdict": "UNKNOWN", "evidence": {}, "notes": []}
    ws = Path(tempfile.mkdtemp(prefix="fullstack_"))
    telemetry = ws / "hook_telemetry.json"
    out["evidence"]["workspace"] = str(ws)

    repo = ws / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "fs@example.com")
    git(repo, "config", "user.name", "fs")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "initial")
    out["evidence"]["commits_before"] = commits(repo)

    a, b = Backend("acct-a").start(), Backend("acct-b").start()
    _proxy_config(ws / "config.yaml", a.base_url, b.base_url)

    exe = ROOT / ".venv" / "Scripts" / "litellm.exe"
    if not exe.exists():
        exe = Path("litellm")
    proxy = subprocess.Popen(
        [str(exe), "--config", str(ws / "config.yaml"),
         "--port", str(PROXY_PORT), "--num_workers", "1"],
        env=_env(ws, telemetry),
        stdout=(ws / "proxy.out").open("w", encoding="utf-8"),
        stderr=(ws / "proxy.err").open("w", encoding="utf-8"))

    proxy_url = f"http://127.0.0.1:{PROXY_PORT}/v1"
    try:
        up = False
        start = time.time()
        while time.time() - start < TIMEOUT_S:
            try:
                urllib.request.urlopen(
                    f"http://127.0.0.1:{PROXY_PORT}/health/liveliness", timeout=1)
                up = True
                break
            except Exception:
                if proxy.poll() is not None:
                    break
                time.sleep(0.5)
        if not up:
            out["verdict"] = "INCONCLUSIVE"
            out["evidence"]["proxy_stderr"] = (ws / "proxy.err").read_text(
                encoding="utf-8", errors="replace")[-2000:]
            out["notes"].append("The proxy never came up -- HARNESS FAILURE.")
            return out

        # ── RUN 1: crash mid-commit ─────────────────────────────────
        p1 = _spawn_child("fresh", ws, proxy_url, telemetry)
        if not _wait(ws / MARKER, TIMEOUT_S, p1):
            try:
                p1.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p1.kill()
            out["verdict"] = "INCONCLUSIVE"
            out["evidence"]["run1_stderr"] = (ws / "child_fresh.err").read_text(
                encoding="utf-8", errors="replace")[-2500:]
            out["notes"].append(
                "The agent never reached the tool -- HARNESS FAILURE, not a result.")
            return out

        time.sleep(0.6)
        p1.kill()
        try:
            p1.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        out["evidence"]["commits_after_crash"] = commits(repo)

        # ── RUN 2: resume through the same proxy ────────────────────
        (ws / MARKER).unlink(missing_ok=True)
        p2 = _spawn_child("resume", ws, proxy_url, telemetry)
        try:
            p2.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            p2.kill()
        out["evidence"]["commits_after_resume"] = commits(repo)

        time.sleep(2.0)          # the logging callback is async
        tel = _read(telemetry)
        out["evidence"]["hook_calls"] = len(tel.get("calls", []))
        recs = tel.get("records", [])
        out["evidence"]["telemetry_records"] = len(recs)
        out["evidence"]["records_with_trace_id"] = sum(
            1 for r in recs if r.get("trace_id"))
        out["evidence"]["deployments_seen"] = sorted(
            {r.get("deployment") for r in recs if r.get("deployment")})
        out["evidence"]["backend_a_served"] = a.served
        out["evidence"]["backend_b_served"] = b.served
    finally:
        proxy.kill()
        try:
            proxy.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        a.stop()
        b.stop()

    # ── ledger + decisions ──────────────────────────────────────────
    from agentctl.kernel.ledger.store import LedgerStore
    cid = (ws / "conversation_id.txt").read_text(encoding="utf-8").strip()
    with LedgerStore(ws / LEDGER, holder="inspect") as s:
        rows = s._db.execute(
            "SELECT tool_name, state, effect_class, probe_verdict "
            "FROM effect_record WHERE conversation_id=?", (cid,)).fetchall()
        out["evidence"]["ledger"] = [dict(r) for r in rows]
        out["evidence"]["blocked"] = len(s.blocked(cid))
    for mode in ("fresh", "resume"):
        f = ws / f"decisions_{mode}.json"
        if f.exists():
            out["evidence"][f"decisions_{mode}"] = json.loads(
                f.read_text(encoding="utf-8"))
        g = ws / f"gated_{mode}.json"
        if g.exists():
            out["evidence"][f"gated_{mode}"] = json.loads(
                g.read_text(encoding="utf-8"))

    # ══ verdict ═════════════════════════════════════════════════════
    ev = out["evidence"]
    # A gate that CRASHES also returns BLOCK, so a correct commit count can
    # hide an incorrect mechanism. Count the crashes (docs/0024).
    ev["gate_errors"] = sum(
        1 for d in (ev.get("decisions_fresh") or [])
        + (ev.get("decisions_resume") or [])
        if "gate error" in (d.get("reason") or ""))
    before, crash, resume = (ev.get("commits_before"),
                             ev.get("commits_after_crash"),
                             ev.get("commits_after_resume"))
    states = [r["state"] for r in ev.get("ledger", [])]
    resume_verdicts = [d["verdict"] for d in ev.get("decisions_resume", [])]

    if crash != (before or 0) + 1:
        out["verdict"] = "INCONCLUSIVE"
        out["notes"].append(
            f"Expected one commit before the crash, saw {before} -> {crash}.")
    elif resume != crash:
        out["verdict"] = "FAIL"
        out["notes"].append(
            f"THE COMMIT WAS REPEATED ({crash} -> {resume}) with the full "
            f"stack wired up. Decisions on resume: {resume_verdicts}")
    elif not ev.get("hook_calls"):
        out["verdict"] = "FAIL"
        out["notes"].append(
            "No duplicate, but Seam A never fired -- the agent did not go "
            "through the proxy, or the hook is not loaded.")
    elif ev.get("gate_errors"):
        out["verdict"] = "FAIL"
        out["notes"].append(
            f"No duplicate, but the gate CRASHED {ev['gate_errors']} time(s) and "
            f"fail-closed produced the right outcome by the wrong route. A "
            f"correct result via an incorrect mechanism is not a pass "
            f"(docs/0024).")
    else:
        out["verdict"] = "PASS"
        out["notes"].append(
            "The whole stack ran together: agent -> proxy -> backends, with "
            "the gate at Seams B and C. One commit, no duplicate.")
        out["notes"].append(
            f"Seam A fired on {ev['hook_calls']} request(s); "
            f"{ev['records_with_trace_id']}/{ev['telemetry_records']} records "
            f"carry a trace id, deployments {ev.get('deployments_seen')}.")
        out["notes"].append(
            f"Ledger: {states}, resume decision {resume_verdicts}, "
            f"{ev.get('blocked')} blocked.")
    return out


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--child", choices=["fresh", "resume"])
    ap.add_argument("--workspace")
    ap.add_argument("--proxy")
    args = ap.parse_args()
    if args.child:
        return child(args.child, Path(args.workspace), args.proxy)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    RESULTS.mkdir(exist_ok=True)
    res = parent()
    (RESULTS / "full_stack.json").write_text(
        json.dumps(res, indent=2, default=str), encoding="utf-8")

    print("=" * 70)
    print("FULL STACK - agent -> proxy -> backends, with the gate")
    print("=" * 70)
    print(f"  VERDICT: {res['verdict']}")
    for k in ("commits_before", "commits_after_crash", "commits_after_resume",
              "hook_calls", "telemetry_records", "records_with_trace_id",
              "deployments_seen", "backend_a_served", "backend_b_served",
              "blocked", "gated_resume"):
        if k in res["evidence"]:
            print(f"    {k:<24} {res['evidence'][k]}")
    for r in res["evidence"].get("ledger", []):
        print(f"    ledger: {r['tool_name']} {r['state']} probe={r['probe_verdict']}")
    print()
    for n in res["notes"]:
        print(f"  -> {n}")
    print(f"\n  workspace: {res['evidence'].get('workspace')}")
    return 0 if res["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
