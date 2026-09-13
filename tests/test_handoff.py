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


# ── regressions found by CI on Python 3.12 (docs/0028) ─────────────────
def test_the_mailbox_keeps_the_action_alive():
    """`id()` is unique only among LIVE objects.

    With no strong reference, a pending action can be collected and a new,
    unrelated action allocated at the same address -- which would then claim
    the first call's recorded observation. CPython 3.13 happened not to
    recycle the address; 3.12 did, and two tests failed.
    """
    import gc
    import weakref

    h = SubstitutionHandoff()
    a = Action(message="x")
    ref = weakref.ref(a)
    h.offer(a, call(), b"{}")

    del a
    gc.collect()
    assert ref() is not None, (
        "the mailbox dropped the action; its id() can now be recycled "
        "under a different action and claimed by the wrong call")


def test_two_offers_are_two_entries():
    """The symptom: the second offer overwrote the first at a recycled id."""
    h = SubstitutionHandoff()
    h.offer(Action(m=1), call("tc_a"), b"{}")
    h.offer(Action(m=2), call("tc_b", message="y"), b"{}")
    assert h.pending() == 2


def test_a_fingerprint_match_also_clears_the_identity_entry():
    """Otherwise the same substitution is honoured twice.

    The fingerprint path popped `id(call)` from a dict keyed by `id(action)`,
    which removed nothing and left the entry claimable again.
    """
    h = SubstitutionHandoff()
    a = Action(message="x")
    h.offer(a, call(), b'{"status":"ok"}')

    # claim by fingerprint, using a DIFFERENT action object
    first = h.claim(Action(message="x"), "commit", {"message": "x"})
    assert first is not None, "fingerprint fallback should have matched"
    assert h.pending() == 0, "identity entry survived a fingerprint claim"

    # the original action must now find nothing
    assert h.claim(a, "commit", {"message": "x"}) is None
