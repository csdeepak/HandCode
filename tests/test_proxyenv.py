"""The managed proxy: its own environment, started and stopped by agentctl.

`docs/0043` Phase 2, `docs/0047`. Zero network and zero installs here; the
live run that creates the environment and serves a task is recorded in 0047.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agentctl.control import proxyenv


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCTL_HOME", str(tmp_path / "ah"))
    return tmp_path / "ah"


@pytest.fixture
def server():
    """Something answering /health/liveliness on a free port."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/health/liveliness" else 404)
            self.end_headers()
            self.wfile.write(b'"I\'m alive!"')

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()          # or the port stays bound for later tests


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pid(home, pid, port):
    proxyenv.run_dir().mkdir(parents=True, exist_ok=True)
    proxyenv._pidfile().write_text(json.dumps({"pid": pid, "port": port}))


# ══ status ═════════════════════════════════════════════════════════════
def test_nothing_running_is_stopped(home, monkeypatch):
    monkeypatch.setattr(proxyenv, "DEFAULT_PORT", _free_port())
    assert proxyenv.status()["state"] == "stopped"


def test_a_pidfile_whose_process_died_is_dead(home):
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    _pid(home, p.pid, _free_port())
    assert proxyenv.status()["state"] == "dead"


def test_a_live_process_that_answers_is_running(home, server):
    _pid(home, os.getpid(), server)
    s = proxyenv.status()
    assert s["state"] == "running" and s["answers"]


def test_a_live_process_not_yet_answering_is_starting(home):
    _pid(home, os.getpid(), _free_port())
    assert proxyenv.status()["state"] == "starting"


def test_a_proxy_agentctl_did_not_start_is_foreign(home, server, monkeypatch):
    monkeypatch.setattr(proxyenv, "DEFAULT_PORT", server)
    assert proxyenv.status()["state"] == "foreign"


# ══ up ═════════════════════════════════════════════════════════════════
def test_up_refuses_a_port_someone_else_is_serving(home, server):
    with pytest.raises(SystemExit, match="not started by agentctl"):
        proxyenv.up(port=server, verify=False)


def test_up_reuses_a_running_proxy(home, server, monkeypatch):
    _pid(home, os.getpid(), server)
    monkeypatch.setattr(proxyenv, "ensure_env",
                        lambda *a: pytest.fail("must not rebuild a running proxy"))
    assert proxyenv.up(port=server, verify=False)["state"] == "running"


def test_up_never_hands_the_proxy_the_main_envs_packages(home, monkeypatch, server):
    """The generated start scripts put the MAIN environment's site-packages on
    PYTHONPATH, which brings the mcp conflict straight back (`docs/0047`)."""
    seen = {}

    class FakeProc:
        pid = os.getpid()
        returncode = None

        def poll(self):
            return None

    def fake_popen(argv, **kw):
        seen["argv"], seen["env"] = argv, kw["env"]
        _pid(home, os.getpid(), server)          # what up() writes, for status
        return FakeProc()

    monkeypatch.setenv("PYTHONPATH", r"C:\main\site-packages")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(proxyenv, "ensure_env", lambda *a: None)
    monkeypatch.setattr(proxyenv.subprocess, "Popen", fake_popen)
    port = _free_port()
    monkeypatch.setattr(proxyenv, "answers",
                        lambda p, timeout=2.0: "argv" in seen and p == port)

    proxyenv.up(port=port, verify=False, wait_s=5)
    assert "PYTHONPATH" not in seen["env"]
    # The env's own python, not the litellm.exe wrapper, which died at
    # startup with 0xC000013A when launched detached (docs/0047).
    assert seen["argv"][0] == str(proxyenv._env_python())
    assert "run_server" in seen["argv"][2]
    assert (proxyenv.run_dir() / "proxy_config.yaml").exists()


def test_a_proxy_that_dies_at_startup_says_why(home, monkeypatch):
    class Dead:
        pid, returncode = 999999, 3

        def poll(self):
            return 3

    def fake_popen(argv, **kw):
        kw["stdout"].write(b"ImportError: no module named fastapi\n")
        return Dead()

    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(proxyenv, "ensure_env", lambda *a: None)
    monkeypatch.setattr(proxyenv.subprocess, "Popen", fake_popen)
    with pytest.raises(SystemExit, match="fastapi"):
        proxyenv.up(port=_free_port(), verify=False, wait_s=5)
    assert not proxyenv._pidfile().exists()


# ══ the agentctl copy ══════════════════════════════════════════════════
def test_the_proxy_env_gets_this_exact_agentctl(home, tmp_path, monkeypatch):
    purelib = tmp_path / "site-packages"
    purelib.mkdir()
    real = subprocess.run

    def fake_run(argv, **kw):
        if "sysconfig" in " ".join(map(str, argv)):
            return subprocess.CompletedProcess(argv, 0, stdout=str(purelib) + "\n")
        return real(argv, **kw)

    monkeypatch.setattr(proxyenv.subprocess, "run", fake_run)
    dst = proxyenv._copy_agentctl(tmp_path / "python")
    assert (dst / "adapters" / "litellm" / "hook.py").exists()
    assert (dst / "kernel" / "ledger" / "schema.sql").exists()
    assert not list(dst.rglob("__pycache__"))


# ══ down ═══════════════════════════════════════════════════════════════
def test_down_with_nothing_running_is_harmless(home):
    assert proxyenv.down(log=lambda m: None) is False


def test_down_stops_a_real_process(home):
    """The child shares THIS process's group on POSIX, on purpose: `down`
    must stop it without signalling the group, or it kills the test runner
    (it did, on every Linux CI job)."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    _pid(home, p.pid, _free_port())
    assert proxyenv.down(log=lambda m: None) is True
    assert p.wait(timeout=10) is not None
    assert not proxyenv._pidfile().exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_down_signals_the_proxys_own_group(home):
    """A proxy started the way `up` starts it, in its own session, is stopped
    with its children (litellm's workers) by signalling that group."""
    p = subprocess.Popen([sys.executable, "-c",
                          "import subprocess, sys, time; "
                          "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                          "time.sleep(60)"], start_new_session=True)
    _pid(home, p.pid, _free_port())
    assert proxyenv.down(log=lambda m: None) is True
    assert p.wait(timeout=10) is not None


# ══ run --pool ═════════════════════════════════════════════════════════
def test_run_pool_routes_through_the_managed_proxy(home, monkeypatch, server):
    from agentctl import cli

    _pid(home, os.getpid(), server)
    got = {}

    def fake_run(**kw):
        got.update(kw)
        return {"conversation_id": "c", "ledger": "l", "decisions": [],
                "blocked": [], "workspace": "w"}

    monkeypatch.setattr("agentctl.runtime.runner.run", fake_run)
    assert cli.main(["run", "x", "--pool", "--workspace", str(home)]) == 0
    assert got["model"] == "openai/pool"
    assert got["base_url"] == f"http://127.0.0.1:{server}"
