"""`agentctl demo` must show what it says, on every OS CI runs. `docs/0050`.

The demo is a claim made to strangers: plain OpenHands duplicates a commit
across a crash, and agentctl does not. So it is run here end to end -- real
git, real process death, the real SDK -- and the claim is asserted from the
repositories, not from the demo's own printout.
"""
from __future__ import annotations

import shutil

import pytest

pytest.importorskip("openhands.sdk")
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def test_the_demo_shows_the_duplicate_and_its_prevention(monkeypatch, capsys):
    import agentctl.demo as demo

    seen = {}
    real = demo._arm

    def spy(arm, root, base_url, say):
        seen[arm] = r = real(arm, root, base_url, say)
        return r

    monkeypatch.setattr(demo, "_arm", spy)
    assert demo.run_demo() == 0, capsys.readouterr().out
    assert seen["bare"]["after_crash"] == 1 and seen["bare"]["after_resume"] == 2
    assert seen["guarded"]["after_crash"] == 1 and seen["guarded"]["after_resume"] == 1
    out = capsys.readouterr().out
    assert "the same commit, twice" in out and "LANDED" in out


def test_the_demo_never_claims_what_it_did_not_show(capsys):
    """If agentctl ever let the duplicate through, the demo must say so."""
    import agentctl.demo as demo

    rc = demo._verdict({"bare": {"after_resume": 2, "after_crash": 1},
                        "guarded": {"after_resume": 2, "after_crash": 1, "log": ""}},
                       print, __import__("pathlib").Path("."))
    assert rc == 1
    assert "did NOT show what it claims" in capsys.readouterr().out
