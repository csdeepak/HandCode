"""Reconciliation probes: ask the world whether an effect already landed."""
from .base import (
    DID_NOT_LAND,
    INCONCLUSIVE,
    LANDED,
    SAFE_TO_RETRY,
    ProbeRegistry,
    ReconciliationProbe,
)
from .external import IdempotencyProbe
from .filesystem import FileAppendProbe
from .git import GitProbe

__all__ = [
    "DID_NOT_LAND", "INCONCLUSIVE", "LANDED", "SAFE_TO_RETRY",
    "ProbeRegistry", "ReconciliationProbe",
    "FileAppendProbe", "GitProbe", "IdempotencyProbe",
]


def default_registry(repo_root=None, idempotency_fields=None) -> ProbeRegistry:
    """The probes worth having on by default.

    Order matters for auto-selection: the specific probes are tried before the
    idempotency one, which handles any call carrying a key.
    """
    return ProbeRegistry(
        GitProbe(repo_root),
        FileAppendProbe(),
        IdempotencyProbe(idempotency_fields),
    )
