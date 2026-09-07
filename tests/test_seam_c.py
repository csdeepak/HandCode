"""Seam C substitution. docs/0008 §3.5.

Seam C is NOT a second gate: a lookup miss means Seam B said EXECUTE.
"""
import pytest

pytest.importorskip("openhands.sdk", reason="SDK not installed")

from agentctl.adapters.openhands.handoff import SubstitutionHandoff
from agentctl.adapters.openhands.seam_c import GatedExecutor
from agentctl.kernel.ledger.models import ToolCall


class Obs:
    """Minimal stand-in for an SDK Observation."""
    def __init__(self, status="ok", content=None):
        self.status, self.content = status, content

    @classmethod
    def model_validate_json(cls, raw):
        import json
        return cls(**json.loads(raw))

    def model_copy(self, update=None):
        o = Obs(self.status, self.content)
        for k, v in (update or {}).items():
            setattr(o, k, v)
        return o


class Action:
    def __init__(self, **kw): self.__dict__.update(kw)
    def model_dump(self): return dict(self.__dict__)


class Inner:
    def __init__(self): self.calls = 0
    def __call__(self, action, conversation=None):
        self.calls += 1
        return Obs("executed")


def call(cid="tc_1"):
    return ToolCall(cid, "conv", "turn", "commit", {"message": "x"})


def test_no_claim_passes_through_to_the_inner_executor():
    inner = Inner()
    g = GatedExecutor(inner, SubstitutionHandoff(), Obs, "commit")
    assert g(Action(message="x")).status == "executed"
    assert inner.calls == 1


def test_a_claim_substitutes_and_never_calls_the_tool():
    inner, h, a = Inner(), SubstitutionHandoff(), Action(message="x")
    h.offer(a, call(), b'{"status":"recorded"}')
    g = GatedExecutor(inner, h, Obs, "commit")
    assert g(a).status == "recorded"
    assert inner.calls == 0, "the effect must NOT be repeated"


def test_synthesizes_when_the_effect_landed_but_was_never_recorded():
    """A probe-reconciled effect has no stored observation to revive."""
    inner, h, a = Inner(), SubstitutionHandoff(), Action(message="x")
    h.offer(a, call(), None)                       # LANDED, but no result
    g = GatedExecutor(inner, h, Obs, "commit")
    obs = g(a)
    assert inner.calls == 0, "still must not re-run"
    assert obs is not None
    text = str(getattr(obs, "content", ""))
    assert "already completed" in text and "not run again" in text


def test_raises_rather_than_repeat_when_it_cannot_describe_the_result():
    class Undescribable:
        def __init__(self, required):  # no default: cannot be built blind
            self.required = required

    inner, h, a = Inner(), SubstitutionHandoff(), Action(message="x")
    h.offer(a, call(), None)
    g = GatedExecutor(inner, h, Undescribable, "commit")
    with pytest.raises(RuntimeError, match="NOT be re-run|NOT re-run"):
        g(a)
    assert inner.calls == 0, "raising is safe; repeating is not"


def test_lifecycle_delegates_to_the_wrapped_executor():
    class Lifecycle(Inner):
        closed = interrupted = False
        def close(self): self.closed = True
        def interrupt(self): self.interrupted = True

    inner = Lifecycle()
    g = GatedExecutor(inner, SubstitutionHandoff(), Obs, "commit")
    g.close(); g.interrupt()
    assert inner.closed and inner.interrupted
