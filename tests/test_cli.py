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


# ══ an id a human can actually type ══════════════════════════════════
def test_a_model_minted_id_is_shown_short_and_found_by_prefix(tmp_path):
    """Gemini smuggles a thought signature through `tool_call_id`
    (`research/phase-10-3` V4). A real one from a live run was over 300
    characters, and `agentctl resolve` was asking a human to retype it --
    which makes the human half of fail-closed unusable exactly when it is
    needed (`docs/0013` §3).
    """
    from agentctl.kernel.ledger.models import EffectClass, ToolCall
    from agentctl.kernel.ledger.store import SHORT_ID, LedgerStore, short_id

    monster = "call_2524396__thought__" + "EpgBCpUBAWkUfRPnWX0Lt8BP" * 12
    assert len(monster) > 300, "fixture must reproduce the real shape"

    with LedgerStore(tmp_path / "l.db", holder="t") as s:
        call = ToolCall(monster, "conv", "turn", "bash", {"command": "x"})
        s.acquire("conv")
        s.write_intent(call, EffectClass.EXTERNAL, 1)

        assert short_id(monster).endswith("..."), "must mark the truncation"
        assert len(short_id(monster)) == SHORT_ID + 3
        # The prefix a human would copy off the screen resolves.
        assert s.resolve_id(monster[:SHORT_ID]) == monster
        assert s.resolve_id(monster) == monster, "an exact id must still work"


def test_an_ambiguous_prefix_is_refused_not_guessed(tmp_path):
    """This is the path that records an effect as having happened."""
    import pytest

    from agentctl.kernel.ledger.models import EffectClass, ToolCall
    from agentctl.kernel.ledger.store import AmbiguousPrefix, LedgerStore

    with LedgerStore(tmp_path / "l.db", holder="t") as s:
        s.acquire("conv")
        for suffix in ("aaa", "bbb"):
            s.write_intent(ToolCall("call_same_" + suffix, "conv", "t", "bash",
                                    {"command": suffix}),
                           EffectClass.EXTERNAL, 1)
        with pytest.raises(AmbiguousPrefix) as e:
            s.resolve_id("call_same_")
        assert len(e.value.matches) == 2


def test_an_unknown_prefix_resolves_to_nothing(tmp_path):
    from agentctl.kernel.ledger.store import LedgerStore

    with LedgerStore(tmp_path / "l.db", holder="t") as s:
        assert s.resolve_id("call_nothing") is None
