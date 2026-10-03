"""`agentctl demo`: the one thing this project exists for, in a minute, for $0.

`docs/0043` Phase 5. An agent runs `git commit`; its process is killed after
the commit has landed but before the result was recorded; the run is resumed.
Plain OpenHands re-drives the pending action and commits AGAIN (`docs/0014`
reproduced it). With agentctl the git probe sees the commit already landed and
hands the agent its result instead.

Both arms run for real: real git, real process death (`kill`, not a polite
shutdown), the real OpenHands SDK. Only the MODEL is scripted -- a local mock
that asks for the commit once and then stops -- which is what makes it free,
offline, deterministic, and the same on every OS. A recorded cassette was the
alternative and could not be: the SDK writes the shell name into the system
prompt, so a cassette replays only on the platform it was recorded on
(`docs/0029` §6), and git hashes and timings in tool output would break an
exact replay anyway (`docs/0050`).
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MARKER = "commit_landed.marker"
SLEEP_S = 8.0               # the crash window: committed, result not recorded
TIMEOUT_S = 150.0


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True,
                          text=True)


def _commits(repo: Path) -> int:
    r = _git(repo, "rev-list", "--count", "HEAD")
    return int(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else 0


def _seed(ws: Path) -> Path:
    repo = ws / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    # Local identity: the demo must not depend on, or touch, the user's own.
    _git(repo, "config", "user.name", "agentctl demo")
    _git(repo, "config", "user.email", "demo@agentctl.invalid")
    (repo / "README.md").write_text("demo\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    return repo


def _child(arm: str, mode: str, ws: Path, base_url: str) -> subprocess.Popen:
    env = {**os.environ, "OPENHANDS_SUPPRESS_BANNER": "1",
           "PYTHONIOENCODING": "utf-8",
           # A private run index: the demo's runs are not the user's.
           "AGENTCTL_HOME": str(ws / "home")}
    out = open(ws / f"{arm}_{mode}.log", "w", encoding="utf-8", errors="replace")
    p = subprocess.Popen(
        [sys.executable, "-m", "agentctl.demo.child", "--arm", arm, "--mode", mode,
         "--ws", str(ws), "--base-url", base_url],
        stdout=out, stderr=subprocess.STDOUT, env=env, stdin=subprocess.DEVNULL)
    p._log = out                                        # type: ignore[attr-defined]
    return p


def _wait_marker(ws: Path, p: subprocess.Popen) -> bool:
    t0 = time.time()
    while time.time() - t0 < TIMEOUT_S:
        if (ws / MARKER).exists():
            return True
        if p.poll() is not None:
            return False
        time.sleep(0.05)
    return False


def _tail(path: Path, n: int = 12) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join("      " + l for l in lines[-n:])


def _arm(arm: str, root: Path, base_url: str, say) -> dict:
    """Commit, kill inside the window, resume. Count commits at each step."""
    ws = root / arm
    ws.mkdir()
    repo = _seed(ws)
    before = _commits(repo)

    p = _child(arm, "fresh", ws, base_url)
    if not _wait_marker(ws, p):
        p.kill(); p.wait(); p._log.close()
        return {"error": "the commit never ran", "log": _tail(ws / f"{arm}_fresh.log")}
    time.sleep(0.5)
    p.kill()                    # not a shutdown: no finally, no flush, no atexit
    p.wait(); p._log.close()
    after_crash = _commits(repo) - before
    say(f"     the agent committed, then its process was killed ... "
        f"{after_crash} new commit")

    (ws / MARKER).unlink(missing_ok=True)
    p = _child(arm, "resume", ws, base_url)
    try:
        p.wait(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        p.kill(); p.wait()
    p._log.close()
    after_resume = _commits(repo) - before
    return {"after_crash": after_crash, "after_resume": after_resume,
            "ws": ws, "log": _tail(ws / f"{arm}_resume.log")}


def _rmtree(path: Path) -> None:
    def onerror(func, p, _exc):                         # git marks objects read-only
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=onerror)


def run_demo(keep: bool = False) -> int:
    from agentctl.demo.mock import MockModel

    def say(msg=""):
        print(msg, flush=True)

    if shutil.which("git") is None:
        say("  the demo needs git on PATH.")
        return 2

    say("agentctl demo   (no API key, no network, $0)")
    say("")
    say("  An agent runs `git commit`. Its process is killed AFTER the commit")
    say("  lands but BEFORE the result is recorded. Then the run is resumed.")
    say("  Real git, real OpenHands, real process death; only the model is")
    say("  scripted, so this costs nothing and runs the same everywhere.")
    say("")

    root = Path(tempfile.mkdtemp(prefix="agentctl-demo-"))
    results: dict = {}
    try:
        with MockModel() as model:
            say("  1. Plain OpenHands, no agentctl")
            results["bare"] = r = _arm("bare", root, model.base_url, say)
            if "error" not in r:
                say(f"     resumed ............................................ "
                    f"{r['after_resume']} new commits"
                    + ("   <- the same commit, twice" if r["after_resume"] > 1 else ""))
            say("")
            say("  2. With agentctl")
            results["guarded"] = g = _arm("guarded", root, model.base_url, say)
            if "error" not in g:
                say(f"     resumed ............................................ "
                    f"{g['after_resume']} new commit"
                    + ("    <- once" if g["after_resume"] == 1 else ""))
                ledger = _ledger_summary(g["ws"])
                if ledger:
                    say(f"     {ledger}")
        say("")
        return _verdict(results, say, root)
    finally:
        if keep:
            say(f"  kept: {root}")
        else:
            try:
                _rmtree(root)
            except OSError:
                pass


def _ledger_summary(ws: Path) -> str:
    try:
        from agentctl.kernel.ledger.store import LedgerStore
        with LedgerStore(ws / "ledger.db", holder="demo") as s:
            rows = s._db.execute("SELECT state, probe_verdict FROM effect_record"
                                 ).fetchall()
            blocked = len(s.blocked())
        parts = [f"{r['state']}" + (f" (git probe: {r['probe_verdict']})"
                                    if r["probe_verdict"] else "") for r in rows]
        return ("the ledger: the commit is " + ", ".join(parts)
                + f" · {blocked} waiting on you")
    except Exception:                                   # noqa: BLE001
        return ""


def _verdict(results: dict, say, root: Path) -> int:
    bare, guarded = results.get("bare", {}), results.get("guarded", {})
    for name, r in (("plain OpenHands", bare), ("agentctl", guarded)):
        if "error" in r:
            say(f"  the demo could not run the {name} arm: {r['error']}.")
            say(r.get("log", ""))
            say("  This is a broken demo, not a result. `agentctl doctor` checks "
                "the install.")
            return 2
    if guarded["after_resume"] == 1 and bare["after_resume"] >= 2:
        say("  Without agentctl the crash cost a duplicate commit. With it, the")
        say("  agent got the commit's result back and carried on, and nothing")
        say("  needed a human.")
        say("")
        say("  On a real task:   agentctl init")
        say('                    agentctl run "<task>" --accept "<your tests>"')
        return 0
    # Never claim what was not shown.
    say(f"  The demo did NOT show what it claims: plain OpenHands made "
        f"{bare['after_resume']} commit(s), agentctl {guarded['after_resume']}.")
    say(guarded.get("log", ""))
    say(f"  Please report this with the logs in {root} (re-run with --keep).")
    return 1
