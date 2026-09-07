"""Reconciliation probes. Spec: `docs/0012` §3.3, revised.

The problem: after a crash we hold an `INTENT` record and cannot tell whether
the effect landed. A probe asks the world.

**Design change from `docs/0012` §3.3.** That section specified injecting the
intent hash into the effect itself (a git trailer), which requires mutating the
command before execution — only possible at Seam C. This uses *world
fingerprinting* instead:

    capture()  before execution   -> record what the world looked like
    probe()    after a crash      -> compare; did it change?

That needs no cooperation from the tool, works at Seam B, and generalises to
effects that have nowhere to carry a marker.

**The assumption it rests on**, stated plainly: the agent's workspace has a
single writer. If a human commits to the same repo during the crash window, a
probe can misread that as the agent's effect. Every probe returns
`INCONCLUSIVE` rather than guessing when it can distinguish the cases, and the
gate fails closed on `INCONCLUSIVE`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

LANDED = "LANDED"
DID_NOT_LAND = "DID_NOT_LAND"
INCONCLUSIVE = "INCONCLUSIVE"


@runtime_checkable
class ReconciliationProbe(Protocol):
    """Answers 'did this effect already happen?' from outside the ledger."""

    name: str

    def handles(self, call) -> bool:
        """Can this probe say anything about this call?"""

    def capture(self, call) -> dict | None:
        """Fingerprint the world BEFORE execution.

        Returns a JSON-serialisable dict stored on the INTENT record, or None
        if nothing useful can be captured. Must never raise — a probe that
        explodes here would block the call entirely.
        """

    def probe(self, call, record) -> str:
        """LANDED | DID_NOT_LAND | INCONCLUSIVE, using `record.pre_state`.

        Must never raise. When in doubt, return INCONCLUSIVE and let the gate
        fail closed.
        """


class ProbeRegistry:
    """Holds the probes and picks one per call."""

    def __init__(self, *probes: ReconciliationProbe):
        self._probes = list(probes)
        self._by_name = {p.name: p for p in probes}

    def add(self, probe: ReconciliationProbe) -> "ProbeRegistry":
        self._probes.append(probe)
        self._by_name[probe.name] = probe
        return self

    def get(self, name: str | None):
        return self._by_name.get(name) if name else None

    def for_call(self, call, name: str | None = None):
        """Prefer the probe the capability matrix named; else the first match.

        A *named* probe is trusted without consulting `handles()`. The matrix is
        an operator declaration -- "this tool commits to git" -- and it knows
        things a heuristic cannot: a dedicated `commit` tool carries no "git
        commit" string in its arguments to sniff for.
        """
        if name and (p := self._by_name.get(name)) is not None:
            return p
        for p in self._probes:
            if _safe_handles(p, call):
                return p
        return None

    def __len__(self) -> int:
        return len(self._probes)


def _safe_handles(probe, call) -> bool:
    try:
        return bool(probe.handles(call))
    except Exception:                                   # noqa: BLE001
        return False
