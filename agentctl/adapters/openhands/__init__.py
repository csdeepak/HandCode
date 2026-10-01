"""OpenHands adapter — the harness-specific layer (`docs/0008` §12).

One call wires both seams:

    from agentctl.adapters.openhands import protect

    guard = protect(ledger="./ledger.db", conversation_id=cid,
                    tools={"commit": CommitTool}, repo_root="./repo")
    conv = Conversation(agent=agent, callbacks=[guard.seam_b], ...)
    guard.attach(conv)

Everything below `agentctl.kernel` stays harness-neutral; porting to another
harness means rewriting this package and nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.store import LeaseHeartbeat, LedgerStore
from agentctl.kernel.reconcile import (
    IdempotencyProbe,
    ProbeRegistry,
    default_registry,
)

from .handoff import SubstitutionHandoff
from .seam_b import OpenHandsContext, SeamB
from .seam_c import gate_tool_class, gate_tools, install as install_seam_c

__all__ = [
    "protect", "Guard", "SeamB", "OpenHandsContext", "SubstitutionHandoff",
    "gate_tools", "gate_tool_class", "install_seam_c",
]


@dataclass
class Guard:
    """Everything wired together, so callers hold one object."""

    store: LedgerStore
    gate: EffectGate
    handoff: SubstitutionHandoff
    seam_b: SeamB
    gated_tools: list[str] = field(default_factory=list)
    heartbeat: LeaseHeartbeat | None = None
    conversation_id: str = ""
    _closed: bool = field(default=False, repr=False)

    def attach(self, conversation: Any) -> "Guard":
        """Bind Seam B to a live conversation. Required."""
        self.seam_b.attach(conversation)
        return self

    # ── inspection, for the CLI and the eventual dashboard ────────────
    def blocked(self):
        return self.store.blocked(self.seam_b.ctx.conversation_id
                                  if self.seam_b.ctx else None)

    def pending(self):
        cid = self.seam_b.ctx.conversation_id if self.seam_b.ctx else None
        return self.store.pending(cid) if cid else []

    def close(self) -> None:
        """Stop renewing, give the lease back, close the ledger.

        Releasing on a clean exit is what lets the next `--resume` start
        straight away. A crash skips this, and the lease then expires within
        one TTL, or is taken over once its holder is known to be dead.
        """
        if self.heartbeat is not None:
            self.heartbeat.stop()
            self.heartbeat = None
        if self._closed:
            return
        self._closed = True
        try:
            if self.conversation_id:
                self.store.release(self.conversation_id)
        finally:
            self.store.close()

    def __enter__(self) -> "Guard":
        return self

    def __exit__(self, *_) -> None:
        self.close()


def protect(
    ledger: str | Path,
    conversation_id: str,
    tools: dict[str, type] | None = None,
    *,
    matrix: dict | str | Path | None = None,
    repo_root: str | Path | None = None,
    probes: ProbeRegistry | None = None,
    holder: str | None = None,
    takeover: bool = False,
    lease_ttl_s: float = 60.0,
    on_decision: Callable | None = None,
    heartbeat: bool = True,
) -> Guard:
    """Wire the gate, the ledger, and both seams.

    Args:
        ledger: path to the SQLite effect ledger.
        conversation_id: the conversation this guard owns the lease for.
        tools: `{name: ToolDefinition subclass}` to gate at Seam C. Omit to run
            Seam B only — still correct, but an already-landed effect is
            blocked rather than resumed cleanly (`docs/0008` §3.5).
        matrix: capability matrix as a dict, or a path to one. Defaults to the
            bundled `tools.yaml`.
        repo_root: workspace repo, used by the git probe.
        holder: who holds the lease. Defaults to `run@<host>:<pid>`, unique
            per process, which is what lets a resume tell a dead holder from
            a live one (`agentctl.runtime.lease`).
        takeover: steal a LIVE lease. Only right when its holder is known to
            be dead; fencing then refuses the old holder's writes. A live
            holder stolen from is two drivers of one conversation
            (`docs/0042` I-02).
        heartbeat: renew the lease from a background thread until `close()`.

    Returns a `Guard`. You must call `guard.attach(conversation)` after
    constructing the Conversation, or Seam B is inert.
    """
    if holder is None:
        from agentctl.runtime.lease import holder_id
        holder = holder_id()
    store = LedgerStore(ledger, holder=holder)
    fence = store.acquire(conversation_id, ttl_s=lease_ttl_s, takeover=takeover)
    beat = (LeaseHeartbeat(ledger, holder, conversation_id, ttl_s=lease_ttl_s).start()
            if heartbeat else None)

    if isinstance(matrix, (str, Path)):
        classifier = Classifier(matrix_path=matrix)
    elif isinstance(matrix, dict):
        classifier = Classifier(matrix=matrix)
    else:
        classifier = Classifier()

    idem_fields = classifier.idempotency_fields()
    gate = EffectGate(
        store,
        classifier,
        probes=probes if probes is not None
        else default_registry(repo_root, idem_fields),
        fence=fence,
    )

    handoff = SubstitutionHandoff()
    gated: list[str] = []
    if tools:
        # Seam C must be installed BEFORE the Agent resolves its tools. It also
        # stamps the idempotency key the EXTERNAL probe depends on.
        gated = install_seam_c(handoff, tools, IdempotencyProbe(idem_fields))

    seam_b = SeamB(
        gate,
        OpenHandsContext(conversation_id),
        on_decision=on_decision,
        handoff=handoff if gated else None,
    )
    return Guard(store=store, gate=gate, handoff=handoff,
                 seam_b=seam_b, gated_tools=gated, heartbeat=beat,
                 conversation_id=conversation_id)
