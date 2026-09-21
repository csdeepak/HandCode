r"""A citation is only as good as the check nobody performed.

`docs/0039` §7, fifteenth entry. The first live fan-out returned a confident,
correctly-formatted, wrong answer: it named `hook.py:13` for a value that lives
at `hook.py:94`, and the thing at line 13 is prose in a docstring.

Its system prompt demanded a `path:line` citation, and it gave one. **Citation
discipline produced the wrong answer in the right format**, which is worse than
no citation at all, because the format is what makes it believable.

So the tests that matter are the two directions: the real wrong report must be
caught, and a correct report must pass clean. A verifier that cries wolf on
good citations trains a reader to ignore it, which leaves them worse off than
before it existed.
"""
import pytest

from agentctl.runtime.citations import check, describe, find, verify


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "store.py").write_text(
        "\n".join([
            "import time",                    # 1
            "",                               # 2
            "class LedgerStore:",             # 3
            "    def acquire(self, cid,",     # 4
            "                ttl_s: float = 60.0):",   # 5
            "        pass",                   # 6
        ]), encoding="utf-8")
    (tmp_path / "hook.py").write_text(
        "\n".join(["# a docstring about tool_call_id"] * 10
                  + ["class TurnAffinity:",                     # 11
                     "    def __init__(self, ttl_s=900.0):",    # 12
                     "        pass"]),                          # 13
        encoding="utf-8")
    return tmp_path


# ══ the failure that prompted this ═══════════════════════════════════
def test_the_real_wrong_report_is_caught(repo):
    """Verbatim shape of the live failure: right file, wrong line, wrong timer."""
    report = ("The lease TTL is enforced in `hook.py`, in the `TurnAffinity` "
              "class. The value is `900.0` seconds, cited at `hook.py:1`.")
    cites = verify(report, repo)
    assert len(cites) == 1
    c = cites[0]
    assert not c.ok
    misplaced = dict(c.misplaced)
    assert "900.0" in misplaced, "the asserted value was not checked"
    assert misplaced["900.0"] == 12, "should point at where it actually is"


def test_a_correct_report_passes_clean(repo):
    """The other direction, and the one that decides whether this is usable."""
    report = ("The lease TTL is acquired in `store.py`. The default is "
              "`60.0` seconds, at `store.py:5`.")
    cites = verify(report, repo)
    assert len(cites) == 1 and cites[0].ok, \
        f"flagged a correct citation: {cites[0].misplaced or cites[0].problem}"
    assert "60.0" in (cites[0].text or "")


def test_the_citations_own_line_number_is_not_treated_as_a_claim(repo):
    """`store.py:5` must not assert that the token `5` appears at line 5.

    This flagged a correct report on the first attempt.
    """
    c = check("store.py", 5, "the default is at `store.py:5`", repo)
    assert c.ok, f"the citation's own line number was checked as a claim: {c.misplaced}"


# ══ resolution ═══════════════════════════════════════════════════════
def test_a_missing_file_is_reported(repo):
    c = check("nope.py", 3, "see `nope.py:3`", repo)
    assert not c.ok and "no such file" in c.problem


def test_a_line_past_the_end_is_reported(repo):
    c = check("store.py", 900, "see `store.py:900`", repo)
    assert not c.ok and "past the end" in c.problem


def test_a_path_outside_the_workspace_is_refused(repo):
    """A scout cannot vouch for a file it was never allowed to read."""
    c = check("../../../etc/passwd", 1, "see it", repo)
    assert not c.ok and "outside the workspace" in c.problem


def test_the_cited_line_text_comes_back(repo):
    """What is actually there is the thing a reader needs most."""
    c = check("store.py", 5, "at `store.py:5`", repo)
    assert "60.0" in c.text


# ══ extraction ═══════════════════════════════════════════════════════
def test_citations_are_found_with_and_without_backticks():
    got = {(p, n) for p, n, _ in find("see `a/b.py:12` and c.py:7 for detail")}
    assert got == {("a/b.py", 12), ("c.py", 7)}


def test_a_report_with_no_citation_says_so(repo):
    out = describe(verify("The lease TTL is 60 seconds.", repo))
    assert "no citation" in out
    assert "none of it has been verified" in out, (
        "an uncited report must be marked unverified, not silently passed -- "
        "it is the easiest way to evade the check")


# ══ what the reader sees ═════════════════════════════════════════════
def test_a_failure_points_at_where_the_value_really_is(repo):
    out = describe(verify("`900.0` is cited at `hook.py:1`.", repo))
    assert "not there" in out and "line 12" in out


def test_the_summary_does_not_call_a_failed_citation_a_lie(repo):
    """It is an unverifiable claim, which is a different thing."""
    out = describe(verify("`900.0` at `hook.py:1`.", repo))
    assert "not a false claim" in out


def test_the_output_is_ascii(repo):
    describe(verify("`900.0` at `hook.py:1`.", repo)).encode("cp437")
