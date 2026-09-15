r"""Shared fixtures.

## Why the environment is snapshotted

`keys.load()` writes credentials straight into `os.environ`, which is its job.
`monkeypatch.delenv(name, raising=False)` on a variable that did not exist
records nothing to restore, so a value written afterwards **survives the test**
— and the next test sees a provider it never configured.

That made the suite order-dependent in the worst way: every file passed on its
own and three failed together, which reads as a code bug and is a test bug.
Caught by an autouse hook that printed the leaked names after each test rather
than by reasoning about it.

The fixture below snapshots every credential-shaped variable and puts the
environment back exactly as it was.
"""
from __future__ import annotations

import os

import pytest

MARKERS = ("_API_KEY", "AGENTCTL_KEYS", "AGENTCTL_WORKSPACE",
           "AGENTCTL_TELEMETRY", "_BASE_URL")


def _snapshot() -> dict[str, str]:
    return {k: v for k, v in os.environ.items()
            if any(m in k for m in MARKERS)}


@pytest.fixture(autouse=True)
def isolate_credentials():
    """Restore the environment after every test, whoever mutated it."""
    before = _snapshot()
    yield
    after = _snapshot()
    for name in after:
        if name not in before:
            os.environ.pop(name, None)          # added by the test: remove
    for name, value in before.items():
        if os.environ.get(name) != value:
            os.environ[name] = value            # changed or deleted: restore
