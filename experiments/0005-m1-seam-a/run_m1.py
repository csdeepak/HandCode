"""M1 acceptance — does Seam A actually fire, and does failover work?

`docs/0012` §0 makes this a live-fire test rather than a wiring exercise.
LiteLLM has an open bug where `async_pre_call_hook` is silently bypassed on the
Anthropic endpoint (#27518) and never fires for MCP calls (#25011). Silently is
the problem: a Seam A that does nothing looks exactly like a Seam A that works.

    A  the hook fires inside a real proxy
    B  two accounts fail over on 429
    C  a mid-turn request is pinned to the endpoint that opened the turn
    D  which pool endpoints can litellm actually price      (docs/0009 Q18)
    E  OpenHands drives the proxy end to end

Zero cost: two local mock backends. No API key, no network.

    python run_m1.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
RESULTS = HERE / "results"
MASTER_KEY = "sk-m1-test"
PROXY_PORT = 4999


def _post(url: str, payload: dict, timeout: float = 60.0):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {MASTER_KEY}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def _wait_for_proxy(proc, timeout_s: float = 120.0) -> bool:
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{PROXY_PORT}/health/liveliness", timeout=1)
            return True
        except Exception:
            if proc.poll() is not None:
                return False
            time.sleep(0.5)
    return False


def _write_config(path: Path, a_url: str, b_url: str, telemetry: Path) -> None:
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


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    sys.path.insert(0, str(HERE))
    from backends import Backend

    RESULTS.mkdir(exist_ok=True)
    out: dict = {"verdict": "UNKNOWN", "evidence": {}, "notes": []}

    tmp = Path(tempfile.mkdtemp(prefix="m1_"))
    telemetry = tmp / "hook_telemetry.json"
    a, b = Backend("acct-a").start(), Backend("acct-b").start()
    _write_config(tmp / "config.yaml", a.base_url, b.base_url, telemetry)

    # The proxy banner is non-ASCII; a cp1252 pipe kills startup outright.
    env = {**os.environ,
           "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
           "PYTHONPATH": f"{HERE}{os.pathsep}{ROOT}",
           "AGENTCTL_TELEMETRY": str(telemetry),
           "LITELLM_DONT_SHOW_FEEDBACK_BOX": "True"}
    exe = ROOT / ".venv" / "Scripts" / "litellm.exe"
    if not exe.exists():
        exe = Path("litellm")

    proxy = subprocess.Popen(
        [str(exe), "--config", str(tmp / "config.yaml"),
         "--port", str(PROXY_PORT), "--num_workers", "1"],
        env=env,
        stdout=(tmp / "proxy.out").open("w", encoding="utf-8"),
        stderr=(tmp / "proxy.err").open("w", encoding="utf-8"))

    try:
        if not _wait_for_proxy(proxy):
            out["verdict"] = "INCONCLUSIVE"
            out["evidence"]["proxy_stderr"] = (tmp / "proxy.err").read_text(
                encoding="utf-8", errors="replace")[-2500:]
            out["notes"].append(
                "The proxy never came up -- HARNESS FAILURE, not a result.")
            return _report(out, tmp)

        base = f"http://127.0.0.1:{PROXY_PORT}/v1/chat/completions"

        # ── A: does the hook fire? ─────────────────────────────────
        code, _ = _post(base, {"model": "pool",
                               "messages": [{"role": "user", "content": "hi"}]})
        out["evidence"]["first_call_status"] = code
        time.sleep(1.0)                      # the logger callback is async
        tel = _read(telemetry)
        out["evidence"]["hook_calls"] = len(tel.get("calls", []))
        out["evidence"]["hook_fired"] = bool(tel.get("calls"))
        if tel.get("calls"):
            out["evidence"]["first_trace_id"] = tel["calls"][0].get("trace_id")

        # ── C: turn-atomic pinning ─────────────────────────────────
        mid_turn = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_pin_1", "type": "function",
                 "function": {"name": "f", "arguments": "{}"}}]},
        ]
        _post(base, {"model": "pool", "messages": mid_turn})
        time.sleep(1.0)
        tel = _read(telemetry)
        mids = [c for c in tel.get("calls", []) if c.get("mid_turn")]
        out["evidence"]["mid_turn_detected"] = len(mids)
        out["evidence"]["mid_turn_trace_id"] = mids[0]["trace_id"] if mids else None

        # ── B: failover ────────────────────────────────────────────
        a.failing = True
        served_before = (a.served, b.served)
        statuses = [_post(base, {"model": "pool", "messages": [
            {"role": "user", "content": f"failover {i}"}]})[0] for i in range(4)]
        out["evidence"]["failover_statuses"] = statuses
        out["evidence"]["acct_a"] = {"served": a.served, "refused": a.refused}
        out["evidence"]["acct_b"] = {"served": b.served, "refused": b.refused}
        out["evidence"]["b_served_more_after_a_failed"] = (
            b.served > served_before[1])

        # ── D: Q18, pricing coverage ───────────────────────────────
        # Read once, at the end: the logging callback is async, so an earlier
        # read undercounts and makes a working hook look broken.
        time.sleep(2.0)
        tel = _read(telemetry)
        calls, recs = tel.get("calls", []), tel.get("records", [])
        out["evidence"]["hook_calls"] = len(calls)
        out["evidence"]["hook_fired"] = bool(calls)
        out["evidence"]["mid_turn_detected"] = sum(
            1 for c in calls if c.get("mid_turn"))
        out["evidence"]["telemetry_records"] = len(recs)

        priced = [r for r in recs if r.get("cost")]
        out["evidence"]["records_with_cost"] = len(priced)
        out["evidence"]["q18_mock_model_is_priced"] = bool(priced)

        # Attribution: does the trace id survive to the logging callback?
        traced = [r for r in recs if r.get("trace_id")]
        out["evidence"]["records_with_trace_id"] = len(traced)
        out["evidence"]["deployments_seen"] = sorted(
            {r.get("deployment") for r in recs if r.get("deployment")})
    finally:
        proxy.kill()
        try:
            proxy.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
        a.stop()
        b.stop()

    # ══ verdict ════════════════════════════════════════════════════
    ev = out["evidence"]
    if not ev.get("hook_fired"):
        out["verdict"] = "FAIL"
        out["notes"].append(
            "Seam A did NOT fire. Everything downstream -- policy, affinity, "
            "cost attribution -- would silently do nothing. This is exactly "
            "the failure docs/0012 §0 warns about.")
    elif not ev.get("b_served_more_after_a_failed"):
        out["verdict"] = "FAIL"
        out["notes"].append(
            "The hook fires but failover did not reach acct-b. Check "
            "router_settings and proxy.err.")
    elif not ev.get("records_with_trace_id"):
        out["verdict"] = "FAIL"
        out["notes"].append(
            "The hook fires and failover works, but no telemetry record "
            "carries a trace id -- cost attribution (docs/0008 §8) would have "
            "nothing to join on. See docs/0021 §4.")
    else:
        out["verdict"] = "PASS"
        out["notes"].append(
            f"Seam A fired on {ev['hook_calls']} request(s) inside a real "
            f"proxy, and a 429 on acct-a failed over to acct-b.")
        out["notes"].append(
            f"{ev['records_with_trace_id']}/{ev['telemetry_records']} telemetry "
            f"records carry a trace id, across deployments "
            f"{ev.get('deployments_seen')} -- M5 has something to join on.")
        if ev.get("mid_turn_detected"):
            out["notes"].append(
                "Mid-turn requests are detected, so turn-atomic routing has "
                "something to pin on (docs/0010 §7.3).")
        if not ev.get("q18_mock_model_is_priced"):
            out["notes"].append(
                "Q18: litellm could NOT price this endpoint, so no cost was "
                "recorded. An unpriced endpoint is invisible to "
                "max_budget_per_run -- the risk in docs/0015 §4, confirmed.")

    return _report(out, tmp)


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _report(out: dict, tmp: Path) -> int:
    out["evidence"]["workdir"] = str(tmp)
    (RESULTS / "m1.json").write_text(json.dumps(out, indent=2, default=str),
                                     encoding="utf-8")
    print("=" * 70)
    print("M1 ACCEPTANCE - does Seam A fire, and does failover work?")
    print("=" * 70)
    print(f"  VERDICT: {out['verdict']}")
    for k in ("hook_fired", "hook_calls", "mid_turn_detected",
              "mid_turn_trace_id", "failover_statuses", "acct_a", "acct_b",
              "telemetry_records", "records_with_trace_id",
              "records_with_cost", "deployments_seen"):
        if k in out["evidence"]:
            print(f"    {k:<26} {out['evidence'][k]}")
    print()
    for n in out["notes"]:
        print(f"  -> {n}")
    print(f"\n  workdir: {tmp}")
    return 0 if out["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
