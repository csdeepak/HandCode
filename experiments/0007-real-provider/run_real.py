"""The full stack against a REAL provider. `docs/0023`.

Everything until now was verified against local mocks. Deliberately — it keeps
`verify.py` free to run — but it is also a real limit: a mock agrees with
whatever you assumed. This runs the same stack against OpenRouter.

    OpenHands agent
        -> LiteLLM proxy         Seam A: hook, turn-pinning, telemetry
            -> a pool of two FREE OpenRouter models
        + agentctl gate          Seams B and C

    RUN 1  the agent commits to git, then is hard-killed mid-tool
    RUN 2  it resumes; the git probe says LANDED; Seam C substitutes
    ASSERT one commit, real tool_call_ids, real telemetry

**Cost.** Free-tier models only (`:free`), one tool call, capped output. Expect
$0.00 of billed spend and a handful of tokens. The key is read from
`OPENROUTER_API_KEY` and never printed.

The pool is two *models* through one key, not two accounts — an honest
multi-model pool, which also exercises the cross-model `tool_call_id` variance
that motivated turn-atomic routing (`docs/0010` §7.3).

    python run_real.py
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

MASTER_KEY = "sk-real-run"
PROXY_PORT = 4997
MARKER = "tool_entered.marker"
LEDGER = "ledger.db"
SLEEP_S = 6.0
TIMEOUT_S = 240.0

#: Both free, both verified to support tool calling. See docs/0023 §2.
PRIMARY = "openrouter/nvidia/nemotron-3-super-120b-a12b:free"
SECONDARY = "openrouter/nex-agi/nex-n2.5-pro:free"

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
# CHILD
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
        decisions.append({"tool": call.tool_name,
                          "tool_call_id": call.tool_call_id,
                          "verdict": decision.verdict.value,
                          "reason": decision.reason})
        (ws / f"decisions_{mode}.json").write_text(
            json.dumps(decisions, indent=2), encoding="utf-8")

    guard = protect(
        ledger=ws / LEDGER, conversation_id=str(cid),
        tools={m4_tool.TOOL_NAME: m4_tool.CommitTool},
        matrix=MATRIX, repo_root=repo,
        holder=f"real-{mode}", takeover=(mode == "resume"),
        on_decision=record,
    )

    llm = LLM(model="openai/pool", api_key=MASTER_KEY, base_url=proxy_url,
              service_id="real", temperature=0.0, num_retries=2,
              max_output_tokens=512)
    agent = Agent(llm=llm, tools=[Tool(name=m4_tool.TOOL_NAME,
                                       params={"repo": str(repo)})],
                  include_default_tools=[])

    conv = Conversation(agent=agent, workspace=str(ws / "ws"),
                        persistence_dir=str(ws / "state"), conversation_id=cid,
                        delete_on_close=False, stuck_detection=False,
                        callbacks=[guard.seam_b])
    guard.attach(conv)

    if mode == "fresh":
        conv.send_message(
            "Call the commit tool exactly once with the message "
            "'real provider run'. Do not call any other tool. "
            "After it returns, reply 'done' and stop.")
    # NOTE: the tool takes no path argument. Where the commit lands is
    # configuration (docs/0023 section 3), not something the model chooses.
    conv.run()
    guard.close()
    return 0


# ══════════════════════════════════════════════════════════════════════
# PARENT
# ══════════════════════════════════════════════════════════════════════
def _config(path: Path) -> None:
    path.write_text(f"""model_list:
  - model_name: pool
    litellm_params:
      model: {PRIMARY}
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      id: nemotron-free
  - model_name: pool
    litellm_params:
      model: {SECONDARY}
      api_key: os.environ/OPENROUTER_API_KEY
    model_info:
      id: nex-free

litellm_settings:
  callbacks: hook_module.proxy_handler_instance
  drop_params: true

router_settings:
  routing_strategy: simple-shuffle
  num_retries: 2
  allowed_fails: 2
  cooldown_time: 30

general_settings:
  master_key: {MASTER_KEY}
""", encoding="utf-8")


def _env(telemetry: Path) -> dict:
    return {**os.environ,
            "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
            "OPENHANDS_SUPPRESS_BANNER": "1",
            "PYTHONPATH": os.pathsep.join([str(M1), str(ROOT)]),
            "AGENTCTL_TELEMETRY": str(telemetry),
            "LITELLM_DONT_SHOW_FEEDBACK_BOX": "True"}


def _spawn(mode: str, ws: Path, proxy_url: str, telemetry: Path):
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", str(HERE / "run_real.py"),
         "--child", mode, "--workspace", str(ws), "--proxy", proxy_url],
        stdout=(ws / f"child_{mode}.out").open("w", encoding="utf-8", errors="replace"),
        stderr=(ws / f"child_{mode}.err").open("w", encoding="utf-8", errors="replace"),
        env=_env(telemetry))


def _wait(path: Path, timeout: float, proc) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        if path.exists():
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.05)
    return False


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def parent() -> dict:
    out: dict = {"verdict": "UNKNOWN", "evidence": {}, "notes": []}
    if not os.environ.get("OPENROUTER_API_KEY"):
        out["verdict"] = "SKIPPED"
        out["notes"].append("OPENROUTER_API_KEY is not set.")
        return out

    ws = Path(tempfile.mkdtemp(prefix="real_"))
    telemetry = ws / "hook_telemetry.json"
    out["evidence"]["workspace"] = str(ws)
    out["evidence"]["models"] = [PRIMARY, SECONDARY]

    repo = ws / "repo"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "real@example.com")
    git(repo, "config", "user.name", "real")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "initial")
    out["evidence"]["commits_before"] = commits(repo)

    _config(ws / "config.yaml")
    exe = ROOT / ".venv" / "Scripts" / "litellm.exe"
    if not exe.exists():
        exe = Path("litellm")
    proxy = subprocess.Popen(
        [str(exe), "--config", str(ws / "config.yaml"),
         "--port", str(PROXY_PORT), "--num_workers", "1"],
        env=_env(telemetry),
        stdout=(ws / "proxy.out").open("w", encoding="utf-8"),
        stderr=(ws / "proxy.err").open("w", encoding="utf-8"))

    proxy_url = f"http://127.0.0.1:{PROXY_PORT}/v1"
    try:
        up, start = False, time.time()
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

        p1 = _spawn("fresh", ws, proxy_url, telemetry)
        if not _wait(ws / MARKER, TIMEOUT_S, p1):
            try:
                p1.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p1.kill()
            out["verdict"] = "INCONCLUSIVE"
            out["evidence"]["run1_stderr"] = (ws / "child_fresh.err").read_text(
                encoding="utf-8", errors="replace")[-3000:]
            out["notes"].append(
                "The agent never reached the tool. With a real model this is "
                "usually the model declining to call it, or a provider error -- "
                "check run1_stderr before treating it as a system failure.")
            return out

        time.sleep(0.6)
        p1.kill()
        try:
            p1.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        out["evidence"]["commits_after_crash"] = commits(repo)

        (ws / MARKER).unlink(missing_ok=True)
        p2 = _spawn("resume", ws, proxy_url, telemetry)
        try:
            p2.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            p2.kill()
        out["evidence"]["commits_after_resume"] = commits(repo)

        time.sleep(2.0)
        tel = _read(telemetry)
        recs = tel.get("records", [])
        out["evidence"]["hook_calls"] = len(tel.get("calls", []))
        out["evidence"]["telemetry_records"] = len(recs)
        out["evidence"]["records_with_trace_id"] = sum(
            1 for r in recs if r.get("trace_id"))
        out["evidence"]["deployments_seen"] = sorted(
            {r.get("deployment") for r in recs if r.get("deployment")})
        out["evidence"]["real_prompt_tokens"] = sum(
            r.get("prompt_tokens") or 0 for r in recs)
        out["evidence"]["real_completion_tokens"] = sum(
            r.get("completion_tokens") or 0 for r in recs)
        out["evidence"]["records_with_cost"] = sum(1 for r in recs if r.get("cost"))
    finally:
        proxy.kill()
        try:
            proxy.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    from agentctl.kernel.ledger.store import LedgerStore
    cid = (ws / "conversation_id.txt").read_text(encoding="utf-8").strip()
    with LedgerStore(ws / LEDGER, holder="inspect") as s:
        rows = s._db.execute(
            "SELECT tool_call_id, tool_name, state, probe_verdict "
            "FROM effect_record WHERE conversation_id=?", (cid,)).fetchall()
        out["evidence"]["ledger"] = [dict(r) for r in rows]
        out["evidence"]["blocked"] = len(s.blocked(cid))
    for mode in ("fresh", "resume"):
        f = ws / f"decisions_{mode}.json"
        if f.exists():
            out["evidence"][f"decisions_{mode}"] = json.loads(
                f.read_text(encoding="utf-8"))

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
    if crash != (before or 0) + 1:
        out["verdict"] = "INCONCLUSIVE"
        out["notes"].append(f"Expected one commit before the crash, saw "
                            f"{before} -> {crash}.")
    elif resume != crash:
        out["verdict"] = "FAIL"
        out["notes"].append(
            f"THE COMMIT WAS REPEATED ({crash} -> {resume}) against a real "
            f"provider. Decisions: {ev.get('decisions_resume')}")
    elif ev.get("gate_errors"):
        out["verdict"] = "FAIL"
        out["notes"].append(
            f"No duplicate, but the gate CRASHED {ev['gate_errors']} time(s) and "
            f"fail-closed produced the right outcome by the wrong route. A "
            f"correct result via an incorrect mechanism is not a pass "
            f"(docs/0024).")
    else:
        out["verdict"] = "PASS"
        ids = [r["tool_call_id"] for r in ev.get("ledger", [])]
        out["notes"].append(
            "The full stack held against a real provider: one commit, no "
            "duplicate, real model, real tokens.")
        out["notes"].append(
            f"Real tool_call_id from the provider: {ids}")
        out["notes"].append(
            f"{ev['real_prompt_tokens']} prompt + "
            f"{ev['real_completion_tokens']} completion tokens across "
            f"{ev['telemetry_records']} calls on {ev.get('deployments_seen')}.")
        if not ev.get("records_with_cost"):
            out["notes"].append(
                "Q18 IN THE WILD: every record reports cost 0.0. These are "
                "free-tier models, so that may be true -- and litellm gives you "
                "no way to tell it apart from an unpriced endpoint.")
    return out


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
    (RESULTS / "real.json").write_text(
        json.dumps(res, indent=2, default=str), encoding="utf-8")

    print("=" * 70)
    print("REAL PROVIDER - the full stack against OpenRouter")
    print("=" * 70)
    print(f"  VERDICT: {res['verdict']}")
    for k in ("models", "commits_before", "commits_after_crash",
              "commits_after_resume", "hook_calls", "telemetry_records",
              "records_with_trace_id", "deployments_seen",
              "real_prompt_tokens", "real_completion_tokens",
              "records_with_cost", "blocked"):
        if k in res["evidence"]:
            print(f"    {k:<24} {res['evidence'][k]}")
    for r in res["evidence"].get("ledger", []):
        print(f"    ledger: {r['state']} probe={r['probe_verdict']} "
              f"id={r['tool_call_id']}")
    print()
    for n in res["notes"]:
        print(f"  -> {n}")
    print(f"\n  workspace: {res['evidence'].get('workspace')}")
    return 0 if res["verdict"] in ("PASS", "SKIPPED") else 1


if __name__ == "__main__":
    raise SystemExit(main())
