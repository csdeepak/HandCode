"""Seam B -> Seam C handoff. docs/0012 §4.

Seam B has the tool_call_id; Seam C has the action object. Neither has both,
so a substitution has to be carried between them.
"""
import pytest

from agentctl.adapters.openhands.handoff import SubstitutionHandoff
from agentctl.kernel.ledger.models import ToolCall


def call(cid="tc_1", tool="commit", **args):
    return ToolCall(cid, "conv", "turn", tool, args or {"message": "x"})


class Action:
    """Stand-in for an SDK Action: no identity of its own."""
    def __init__(self, **kw): self.__dict__.update(kw)
    def model_dump(self): return dict(self.__dict__)


def test_claim_matches_by_object_identity():
    h, a = SubstitutionHandoff(), Action(message="x")
    h.offer(a, call(), b'{"status":"ok"}')
    got = h.claim(a, "commit", {"message": "x"})
    assert got is not None and got[1] == b'{"status":"ok"}'


def test_a_claim_is_consumed_exactly_once():
    """A repeated call must not be silently short-circuited twice."""
    h, a = SubstitutionHandoff(), Action(message="x")
    h.offer(a, call(), b"{}")
    assert h.claim(a, "commit", {"message": "x"}) is not None
    assert h.claim(a, "commit", {"message": "x"}) is None


def test_falls_back_to_fingerprint_when_identity_differs():
    """Degrade to a missed substitution, never a wrong one."""
    h = SubstitutionHandoff()
    h.offer(Action(message="x"), call(), b'{"status":"ok"}')
    other = Action(message="x")                    # same content, new object
    got = h.claim(other, "commit", {"message": "x"})
    assert got is not None and got[1] == b'{"status":"ok"}'


def test_no_claim_for_a_different_call():
    h = SubstitutionHandoff()
    h.offer(Action(message="x"), call(), b"{}")
    assert h.claim(Action(message="DIFFERENT"), "commit",
                   {"message": "DIFFERENT"}) is None


def test_nothing_offered_means_nothing_claimed():
    """A miss means Seam B said EXECUTE -- Seam C passes through."""
    assert SubstitutionHandoff().claim(Action(m=1), "commit", {"m": 1}) is None


def test_pending_count():
    h = SubstitutionHandoff()
    assert h.pending() == 0
    h.offer(Action(m=1), call("tc_a"), b"{}")
    h.offer(Action(m=2), call("tc_b", message="y"), b"{}")
    assert h.pending() == 2
