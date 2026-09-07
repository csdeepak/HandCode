"""Reconciliation probes: ask the world whether an effect already landed."""
from .base import (
    DID_NOT_LAND,
    INCONCLUSIVE,
    LANDED,
    ProbeRegistry,
    ReconciliationProbe,
)
from .filesystem import FileAppendProbe
from .git import GitProbe

__all__ = [
    "DID_NOT_LAND", "INCONCLUSIVE", "LANDED",
    "ProbeRegistry", "ReconciliationProbe",
    "FileAppendProbe", "GitProbe",
]


def default_registry(repo_root=None) -> ProbeRegistry:
    """The probes worth having on by default."""
    return ProbeRegistry(GitProbe(repo_root), FileAppendProbe())
