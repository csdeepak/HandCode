r"""Installing software into the user's environment asks first. `docs/0052`.

A live run (`docs/0047` §5) showed the agent running `pip install pytest` on
the host, unasked: it writes no file `escaping_writes` can name, and it is not
DESTRUCTIVE, so nothing caught it. It is the same authorization question as a
write outside the workspace -- not the agent's business -- and it gets the
same answer: ask at a terminal, queue without one, and say nothing inside the
container, where it cannot reach the machine.
"""
from __future__ import annotations

import uuid

import pytest

from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import EffectState, ToolCall, Verdict
from agentctl.kernel.ledger.store import LedgerStore
from agentctl.kernel.paths import environment_installs

WS = r"C:\work\proj"


def call(cmd: str) -> ToolCall:
    return ToolCall("t", "c", "t", "execute_bash", {"command": cmd})


@pytest.mark.parametrize("cmd", [
    "pip install pytest",                          # the live case
    "python -m pip install requests",
    "pip3 install -U numpy",
    "cd src && pip install -e .",
    "/usr/bin/pip install x",
    "uv pip install pytest",
    "uv tool install ruff",
    "pipx install black",
    "npm install -g typescript",
    "sudo apt-get install -y jq",
    "brew install jq",
    "cargo install ripgrep",
    "gem install rails",
    "go install golang.org/x/tools/gopls@latest",
])
def test_installs_into_the_environment_are_flagged(cmd):
    assert environment_installs(call(cmd), WS)


@pytest.mark.parametrize("cmd", [
    ".venv/bin/pip install pytest",                # a venv inside the repo
    r".venv\Scripts\python.exe -m pip install pytest",
    "pip install --target ./vendor requests",
    "uv pip install --python .venv/bin/python pytest",
    "npm install lodash",                          # local node_modules
    "pip list",
    "pip show pytest",
    "python -m pytest -q",
])
def test_what_stays_in_the_workspace_or_installs_nothing_is_not(cmd):
    """A prompt that is wrong teaches the operator to answer `y` unread."""
    assert environment_installs(call(cmd), WS) == []


def test_a_venv_outside_the_workspace_is_still_the_users_environment():
    assert environment_installs(call("/home/me/.venv/bin/pip install x"), WS)


# ══ the wrapper ════════════════════════════════════════════════════════
@pytest.fixture
def wired(tmp_path, monkeypatch):
    monkeypatch.delenv("HANDCODE_CONTAINER", raising=False)
    from agentctl.runtime.runner import _install_confirmation
    store = LedgerStore(tmp_path / "l.db", holder="t")
    cid = str(uuid.uuid4())
    gate = EffectGate(store, Classifier(), fence=store.acquire(cid))
    guard = type("G", (), {})()
    guard.gate = gate
    _install_confirmation(guard, verbose=False, workspace=tmp_path, interactive=False)
    yield gate, store, cid
    store.close()


def test_unattended_a_pip_install_is_queued_for_approval(wired):
    gate, store, cid = wired
    d = gate.guard(ToolCall("p1", cid, "t", "execute_bash",
                            {"command": "pip install pytest"}))
    assert d.verdict is Verdict.BLOCK and "queued" in d.reason
    assert "installs into your environment" in d.reason
    assert store.lookup("p1").state is EffectState.BLOCKED


def test_inside_the_container_it_is_not_asked(tmp_path, monkeypatch):
    monkeypatch.setenv("HANDCODE_CONTAINER", "1")
    from agentctl.runtime.runner import _install_confirmation
    store = LedgerStore(tmp_path / "l.db", holder="t")
    cid = str(uuid.uuid4())
    gate = EffectGate(store, Classifier(), fence=store.acquire(cid))
    guard = type("G", (), {})()
    guard.gate = gate
    _install_confirmation(guard, verbose=False, workspace=tmp_path, interactive=False)
    d = gate.guard(ToolCall("p1", cid, "t", "execute_bash",
                            {"command": "pip install pytest"}))
    assert d.verdict is Verdict.EXECUTE
    store.close()


def test_the_image_says_it_is_a_container():
    from pathlib import Path
    df = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "HANDCODE_CONTAINER=1" in df
