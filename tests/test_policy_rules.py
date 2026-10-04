"""A policy's effect rules hold for every class. docs/0055.

`effects:` in a policy compiled four rules for any class, and the runner
enforced one of them for one class (`require_human_approval` on DESTRUCTIVE).
`external: block` compiled cleanly and then allowed everything, which is the
failure the policy compiler says it exists to prevent.
"""
import json
import os
import subprocess
import sys
import uuid

import pytest

from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import EffectClass, EffectState, ToolCall, Verdict
from agentctl.kernel.ledger.store import LedgerStore

EXT, DES = EffectClass.EXTERNAL, EffectClass.DESTRUCTIVE


@pytest.fixture
def wire(tmp_path, monkeypatch):
    monkeypatch.delenv("HANDCODE_CONTAINER", raising=False)
    from agentctl.runtime.runner import _install_confirmation
    opened = []

    def make(rules=None, confirm=True):
        store = LedgerStore(tmp_path / f"l{len(opened)}.db", holder="t")
        opened.append(store)
        cid = str(uuid.uuid4())
        gate = EffectGate(store, Classifier(), fence=store.acquire(cid))
        guard = type("G", (), {})()
        guard.gate = gate
        _install_confirmation(guard, verbose=False, workspace=tmp_path,
                              interactive=False, rules=rules, confirm=confirm)
        return gate, store, cid
    yield make
    for s in opened:
        s.close()


def _call(cid, tool, args, tid="c1"):
    return ToolCall(tid, cid, "t", tool, args)


def test_an_unknown_tool_is_external():
    """The cases below use one; the matrix's default for it is EXTERNAL."""
    assert Classifier().classify(_call("x", "send_email", {"to": "a"})) is EXT


def test_without_a_rule_an_external_effect_runs(wire):
    gate, _, cid = wire()
    assert gate.guard(_call(cid, "send_email", {"to": "a"})).verdict is Verdict.EXECUTE


def test_require_human_approval_on_external_queues_it(wire):
    gate, store, cid = wire({EXT: "require_human_approval"})
    d = gate.guard(_call(cid, "send_email", {"to": "a"}))
    assert d.verdict is Verdict.BLOCK and "queued" in d.reason
    assert "your policy says needs approval" in d.reason
    assert store.lookup("c1").state is EffectState.BLOCKED


def test_block_refuses_it_outright(wire):
    gate, store, cid = wire({EXT: "block"})
    d = gate.guard(_call(cid, "send_email", {"to": "a"}))
    assert d.verdict is Verdict.BLOCK and "policy blocks every EXTERNAL" in d.reason
    # Refused, not waiting: it must not show up as something to approve.
    rec = store.lookup("c1")
    assert rec is None or rec.state is EffectState.FAILED


def test_allow_destructive_does_not_loosen_a_policy_block(wire):
    """`--allow-destructive` turns the built-in questions off. It must not
    quietly turn off a rule the operator wrote down."""
    gate, _, cid = wire({EXT: "block"}, confirm=False)
    assert gate.guard(_call(cid, "send_email", {"to": "a"})).verdict is Verdict.BLOCK
    gate, _, cid = wire({EXT: "require_human_approval"}, confirm=False)
    assert "queued" in gate.guard(_call(cid, "send_email", {"to": "a"})).reason


def test_allow_on_destructive_stops_the_question(wire):
    cmd = {"command": "rm -rf build"}
    gate, _, cid = wire()
    assert gate.guard(_call(cid, "execute_bash", cmd)).verdict is Verdict.BLOCK
    gate, _, cid = wire({DES: "allow"})
    assert gate.guard(_call(cid, "execute_bash", cmd)).verdict is Verdict.EXECUTE


def test_a_rule_on_one_class_leaves_the_others_alone(wire):
    gate, _, cid = wire({EXT: "block"})
    assert gate.guard(_call(cid, "read_file", {"path": "x"})).verdict is Verdict.EXECUTE


def test_a_policy_file_yields_every_rule(tmp_path):
    from agentctl.runtime.runner import _effect_rules, _load_policy
    p = tmp_path / "policy.yaml"
    p.write_text("effects:\n  external: block\n  destructive: require_human_approval\n",
                 encoding="utf-8")
    assert _effect_rules(_load_policy(str(p))) == {EXT: "block",
                                                  DES: "require_human_approval"}
    assert _effect_rules(_load_policy(None)) == {}


# ── through `agentctl run --policy`, with the scripted model ──────────────
def _run(tmp_path, effects: str) -> tuple[subprocess.CompletedProcess, dict, bool]:
    """The scripted model writes hello.txt (an IDEMPOTENT_WRITE), under a
    policy with the given `effects:` lines."""
    from scripted_model import serve

    home, ws = tmp_path / "home", tmp_path / "ws"
    home.mkdir()
    ws.mkdir()
    pol = tmp_path / "policy.yaml"
    pol.write_text("effects:\n" + effects, encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if not k.endswith("_API_KEY") and k not in ("AGENTCTL_MODEL", "AGENTCTL_BASE_URL")}
    env.update(HOME=str(home), USERPROFILE=str(home), AGENTCTL_HOME=str(home / ".agentctl"),
               OPENHANDS_SUPPRESS_BANNER="1", PYTHONIOENCODING="utf-8")
    srv, url = serve()
    try:
        p = subprocess.run([sys.executable, "-m", "agentctl.cli", "run", "write hello.txt",
                            "--workspace", str(ws), "--model", "openai/scripted",
                            "--base-url", url, "--policy", str(pol),
                            "--report-json", str(tmp_path / "report.json")],
                           env=env, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=300)
    finally:
        srv.shutdown()
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    return p, report, (ws / "hello.txt").exists()


def test_a_run_under_a_blocking_policy_does_not_write(tmp_path):
    p, report, wrote = _run(tmp_path, "  idempotent_write: block\n")
    assert not wrote, p.stdout[-2000:] + p.stderr[-2000:]
    assert report["files"] == [] and report["awaiting"] == []


def test_a_run_under_an_approval_policy_queues_the_write(tmp_path):
    p, report, wrote = _run(tmp_path, "  idempotent_write: require_human_approval\n")
    assert not wrote, p.stdout[-2000:] + p.stderr[-2000:]
    assert len(report["awaiting"]) == 1 and report["ok"] is False
    assert p.returncode == 1                    # something waits on a person
