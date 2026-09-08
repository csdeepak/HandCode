"""CLI — the human interface to fail-closed. docs/0013 §3.

Without these commands the gate blocks and nobody can answer it, which makes a
correct design unusable.
"""
import pytest

from agentctl.cli import main
from agentctl.kernel.ledger.models import EffectClass, EffectState, ToolCall
from agentctl.kernel.ledger.store import LedgerStore


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "ledger.db"
    s = LedgerStore(path, holder="seed")
    f = s.acquire("conv_1")
    ok = ToolCall("tc_ok", "conv_1", "t1", "read_file", {"path": "a.txt"})
    blk = ToolCall("tc_blk", "conv_1", "t2", "execute_bash",
                   {"command": "git commit -m x"})
    s.write_intent(ok, EffectClass.PURE_READ, f)
    s.commit("tc_ok", b'{"ok":1}')
    s.write_intent(blk, EffectClass.NON_IDEMPOTENT_WRITE, f, '{"probe":"git"}')
    s.block("tc_blk", "cannot determine whether it already executed")
    s.close()
    return path


def run(ledger, *args):
    return main(["--ledger", str(ledger), *args])


def test_status_summarises(ledger, capsys):
    assert run(ledger, "status") == 0
    out = capsys.readouterr().out
    assert "BLOCKED" in out and "COMMITTED" in out
    assert "need a decision" in out


def test_blocked_lists_and_tells_you_what_to_type(ledger, capsys):
    assert run(ledger, "blocked") == 0
    out = capsys.readouterr().out
    assert "tc_blk" in out
    assert "agentctl resolve tc_blk --landed" in out
    assert "tc_ok" not in out, "only blocked effects belong here"


def test_show_includes_the_probe_fingerprint(ledger, capsys):
    assert run(ledger, "show", "tc_blk") == 0
    out = capsys.readouterr().out
    assert "NON_IDEMPOTENT_WRITE" in out and "pre_state" in out


def test_show_unknown_id_is_an_error(ledger, capsys):
    assert run(ledger, "show", "nope") == 2


def test_resolve_landed_marks_committed(ledger, capsys):
    assert run(ledger, "resolve", "tc_blk", "--landed") == 0
    with LedgerStore(ledger) as s:
        assert s.lookup("tc_blk").state is EffectState.COMMITTED
        assert s.lookup("tc_blk").probe_verdict == "HUMAN"


def test_resolve_retry_marks_failed_so_it_can_run_again(ledger):
    assert run(ledger, "resolve", "tc_blk", "--retry") == 0
    with LedgerStore(ledger) as s:
        assert s.lookup("tc_blk").state is EffectState.FAILED


def test_cannot_resolve_something_that_is_not_blocked(ledger, capsys):
    assert run(ledger, "resolve", "tc_ok", "--landed") == 2


def test_resolve_requires_an_explicit_choice(ledger):
    """No 'probably fine' -- the human must say which happened."""
    with pytest.raises(SystemExit):
        run(ledger, "resolve", "tc_blk")


def test_missing_ledger_exits_cleanly(tmp_path):
    with pytest.raises(SystemExit) as e:
        run(tmp_path / "nope.db", "status")
    assert e.value.code == 2
