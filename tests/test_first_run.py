"""Three rough edges from the owner's first real run of 0.3.0. docs/0056.

  1. The report listed `__pycache__/*.pyc` as changes. One came from the
     agent's own test run, the other from agentctl's `--accept` check.
  2. The agent spent a step on `python: command not found`, then tried
     `python3`.
  3. Two SDK INFO lines, timestamped, sat in the middle of agentctl's header.
"""
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentctl.runtime import report as rp
from agentctl.runtime import tools as rt


def _repo(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    for args in (["init", "-q"], ["config", "user.name", "t"],
                 ["config", "user.email", "t@example.invalid"]):
        subprocess.run(["git", *args], cwd=ws, check=True)
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (ws / "test_calc.py").write_text("from calc import add\nassert add(2, 3) == 5\n")
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=ws, check=True)
    return ws


# ── 1. byproducts are counted, not listed ─────────────────────────────────
@pytest.mark.parametrize("path", ["__pycache__/calc.cpython-312.pyc",
                                  "pkg/__pycache__/m.cpython-313.pyc",
                                  ".pytest_cache/v/cache/nodeids", "old.pyc"])
def test_what_running_python_leaves_behind_is_a_byproduct(path):
    assert rp.byproduct(path)


@pytest.mark.parametrize("path", ["calc.py", "pycache_notes.md", "docs/__init__.py"])
def test_real_files_are_not(path):
    assert not rp.byproduct(path)


def test_a_new_pycache_is_counted_and_not_listed(tmp_path):
    ws = _repo(tmp_path)
    start = rp.snapshot(ws)
    (ws / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (ws / "__pycache__").mkdir()
    (ws / "__pycache__" / "calc.cpython-312.pyc").write_bytes(b"\x00\x01")
    c = rp.changes(ws, start)
    assert [p for p, _, _ in c.files] == ["calc.py"] and c.generated == 1


def test_a_tracked_byproduct_that_changes_is_still_listed(tmp_path):
    """Changing a file git tracks is real, whatever its name."""
    ws = _repo(tmp_path)
    (ws / "kept.pyc").write_bytes(b"one")
    subprocess.run(["git", "add", "-A"], cwd=ws, check=True)
    subprocess.run(["git", "commit", "-qm", "tracked"], cwd=ws, check=True)
    start = rp.snapshot(ws)
    (ws / "kept.pyc").write_bytes(b"two")
    assert [p for p, _, _ in rp.changes(ws, start).files] == ["kept.pyc"]


def test_the_check_itself_writes_no_bytecode(tmp_path):
    ws = _repo(tmp_path)
    (ws / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    r = rp.accept(f'"{sys.executable}" test_calc.py', ws)
    assert r["passed"]
    assert not (ws / "__pycache__").exists()


def test_the_report_says_what_it_left_out():
    rep = rp.Report(outcome="PASS", accept=None,
                    changes=rp.Changes(files=[("calc.py", 1, 1)], generated=2),
                    agent_said=None, usage=rp.Usage(1, 10, 0.0), model="m",
                    seconds=1.0, decisions=[], blocked=[], ledger="l",
                    conversation_id="c", workspace="w")
    assert "(2 generated files left out: __pycache__ and the like)" in "\n".join(rep.lines())
    assert rep.to_json()["generated"] == 2


# ── 2. the agent is told which Python works ───────────────────────────────
def _fake(works: dict):
    """A shell where each name prints what `works` says (None: not found)."""
    def run(cmd):
        return works.get(cmd.split()[0])
    return run


def test_python_is_used_when_it_works():
    assert rt.first_python(_fake({"python": "12345\n", "python3": "12345\n"})) == "python"


def test_python3_when_python_is_missing():
    assert rt.first_python(_fake({"python3": "12345\n"})) == "python3"


def test_the_store_stub_does_not_count():
    """Windows' python.exe that only opens the Microsoft Store prints nothing."""
    assert rt.first_python(_fake({"python": "", "py": "12345"})) == "py"


def test_no_python_at_all():
    assert rt.first_python(_fake({})) is None


def test_what_the_agent_is_told():
    assert rt.python_note("python") == "" and rt.python_note(None) == ""
    assert rt.python_note("python3") == " In this shell Python runs as `python3`, not `python`."
    assert rt.python_note("py") == (" In this shell Python runs as `py`, "
                                    "not `python` or `python3`.")


def test_the_bash_tool_carries_the_note(monkeypatch):
    monkeypatch.setattr(rt, "_NOTE", rt.python_note("python3"))
    (tool,) = rt.BashTool.create()
    assert tool.description.endswith("Python runs as `python3`, not `python`.")


# ── 3. the SDK's INFO lines stay out of the header ────────────────────────
def test_the_sdk_logs_warnings_only(monkeypatch):
    from agentctl.runtime.runner import _quiet_sdk_logs
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    log = logging.getLogger("openhands")
    monkeypatch.setattr(log, "level", logging.NOTSET)
    _quiet_sdk_logs()
    assert log.level == logging.WARNING
    assert not logging.getLogger("openhands.sdk.conversation.state").isEnabledFor(logging.INFO)


def test_log_level_set_by_the_user_wins(monkeypatch):
    from agentctl.runtime.runner import _quiet_sdk_logs
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    log = logging.getLogger("openhands")
    monkeypatch.setattr(log, "level", logging.NOTSET)
    _quiet_sdk_logs()
    assert log.level == logging.NOTSET


# ── all three, through a real run ─────────────────────────────────────────
def test_the_owners_first_run_reads_cleanly(tmp_path):
    """The scripted model fixes calc.py, then imports it, which leaves
    bytecode behind, as running the tests did on the owner's machine."""
    from scripted_model import bash, serve

    ws = _repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    py = Path(sys.executable).as_posix()
    script = [("write_file", {"path": "calc.py",
                              "content": "def add(a, b):\n    return a + b\n"}),
              bash(f'"{py}" -c "import calc"')]
    env = {k: v for k, v in os.environ.items()
           if not k.endswith("_API_KEY")
           and k not in ("AGENTCTL_MODEL", "AGENTCTL_BASE_URL", "LOG_LEVEL",
                         "PYTHONDONTWRITEBYTECODE")}
    env.update(HOME=str(home), USERPROFILE=str(home), AGENTCTL_HOME=str(home / ".agentctl"),
               OPENHANDS_SUPPRESS_BANNER="1", PYTHONIOENCODING="utf-8")
    srv, url = serve(script)
    try:
        p = subprocess.run([sys.executable, "-m", "agentctl.cli", "run", "fix calc.py",
                            "--workspace", str(ws), "--model", "openai/scripted",
                            "--base-url", url, "--accept", f'"{sys.executable}" test_calc.py',
                            "--report-json", str(tmp_path / "report.json")],
                           env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=300)
    finally:
        srv.shutdown()
    out = p.stdout + p.stderr
    assert p.returncode == 0, out[-3000:]
    assert (ws / "__pycache__").exists(), "the import should have left bytecode"
    r = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert r["outcome"] == "PASS" and r["files"] == ["calc.py"] and r["generated"] >= 1
    assert "Created new conversation" not in out and "Loaded 3 tools" not in out
