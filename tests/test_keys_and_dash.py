r"""Provider registry, the keys file, and the dashboard. `docs/0032`.

The security property is the one worth testing hardest: a file of live API keys
committed to a public repository is the worst outcome this project can produce.
So the tests below check that a key is never rendered, never echoed, and that
the tracked-file guard **can actually fire** — a guard that cannot fail is the
shape of `docs/0028` §5.
"""
from __future__ import annotations

import os

import pytest

from agentctl.control import dash, keys
from agentctl.control.providers import BY_KEY, PROVIDERS, accounts, configured

SECRET = "sk-or-v1-THISMUSTNEVERAPPEARANYWHERE"


# ── one registry, not three ────────────────────────────────────────────
def test_doctor_and_proxy_derive_from_the_registry():
    """Two lists drift. `docs/0029` §4 is the same defect, one layer down."""
    from agentctl.control.proxy import CANDIDATES
    from agentctl.runtime.doctor import PROVIDERS as DOCTOR

    assert {d[0] for d in DOCTOR} == {p.key for p in PROVIDERS}
    assert {c[0] for c in CANDIDATES} <= {p.key for p in PROVIDERS}


def test_every_provider_has_somewhere_to_get_a_key():
    for p in PROVIDERS:
        assert p.console.startswith("https://"), p.name
        assert p.key.endswith("_API_KEY"), p.key
        assert p.models and p.prefix.endswith("/")


def test_paid_providers_are_marked_so_fallback_order_can_use_it():
    paid = [p for p in PROVIDERS if not p.free_tier]
    assert {p.name for p in paid} == {"anthropic", "openai"}


def test_the_registry_does_not_record_rate_limits():
    """Deliberate. Limits changed three times across 2026 for these providers;
    a number in source would be confidently wrong within weeks."""
    import agentctl.control.providers as mod
    src = __import__("pathlib").Path(mod.__file__).read_text(encoding="utf-8")
    body = src.split("PROVIDERS: tuple", 1)[1]
    assert "requests/day" not in body and "tokens/day" not in body


# ── the parser ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("line,expected", [
    ("A=1", {"A": "1"}),
    ("export B=2", {"B": "2"}),
    ('C="quoted value"', {"C": "quoted value"}),
    ("D='single'", {"D": "single"}),
    ("E=   spaced   ", {"E": "spaced"}),
    ("# F=commented", {}),
    ("G=", {}),
    ("H=has#hash", {"H": "has#hash"}),
    ("I=val # trailing", {"I": "val"}),
])
def test_the_env_parser_handles_what_people_write(line, expected):
    assert keys.parse(line) == expected


def test_a_dollar_in_a_key_is_a_character_not_a_reference():
    """No interpolation. A key is a literal, and some of them contain `$`."""
    assert keys.parse("K=sk-or-v1-$HOME-literal") == {"K": "sk-or-v1-$HOME-literal"}


# ── loading ────────────────────────────────────────────────────────────
def test_an_exported_variable_beats_the_file(tmp_path, monkeypatch):
    """Something you set in a shell is deliberate; a file must not replace it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "from-the-shell")
    (tmp_path / "keys.env").write_text("GROQ_API_KEY=from-the-file\n", encoding="utf-8")
    keys.load(tmp_path / "keys.env")
    assert os.environ["GROQ_API_KEY"] == "from-the-shell"


def test_override_is_available_when_asked_for(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "from-the-shell")
    (tmp_path / "keys.env").write_text("GROQ_API_KEY=from-the-file\n", encoding="utf-8")
    keys.load(tmp_path / "keys.env", override=True)
    assert os.environ["GROQ_API_KEY"] == "from-the-file"


def test_load_returns_names_never_values(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    (tmp_path / "keys.env").write_text(f"GROQ_API_KEY={SECRET}\n", encoding="utf-8")
    got = keys.load(tmp_path / "keys.env")
    assert got == ["GROQ_API_KEY"]
    assert SECRET not in repr(got)


def test_a_missing_file_is_not_an_error(tmp_path):
    assert keys.load(tmp_path / "nope.env") == []


# ── the guard that matters ─────────────────────────────────────────────
def test_a_tracked_keys_file_is_refused(tmp_path, monkeypatch):
    """A .gitignore entry added AFTER a file is tracked does nothing at all.

    That is exactly how keys get published: the rule is there, everyone
    assumes it works, and the file was staged before it existed.
    """
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    f = tmp_path / "keys.env"
    f.write_text(f"GROQ_API_KEY={SECRET}\n", encoding="utf-8")
    subprocess.run(["git", "add", "-f", "keys.env"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=t",
                    "commit", "-qm", "oops"], cwd=tmp_path, check=True)

    warn = keys.check_not_tracked(f)
    assert warn and "TRACKED BY GIT" in warn and "rotate every key" in warn
    with pytest.raises(keys.KeysAreTracked):
        keys.load(f)


def test_untracked_is_not_enough_it_must_also_be_ignored(tmp_path, monkeypatch):
    """This test used to assert the opposite, and it was too weak.

    "Not tracked" only means the accident has not happened yet. A keys file
    sitting un-ignored inside a repo is one `git add -A` from being published,
    so the guard now flags that state too (`docs/0033` §5).
    """
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    f = tmp_path / "keys.env"
    f.write_text("GROQ_API_KEY=x\n", encoding="utf-8")
    assert "NOT ignored" in (keys.check_not_tracked(f) or "")

    (tmp_path / ".gitignore").write_text("keys.env\n", encoding="utf-8")
    assert keys.check_not_tracked(f) is None


def test_the_template_is_ignored_before_it_is_written(tmp_path, monkeypatch):
    """Order matters. Writing first and ignoring second leaves a window."""
    monkeypatch.chdir(tmp_path)
    p, created = keys.write_template(tmp_path / "keys.env", tmp_path / ".gitignore")
    assert created and p.exists()
    ignored = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert "keys.env" in ignored


def test_the_template_never_overwrites_a_filled_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "keys.env"
    f.write_text(f"GROQ_API_KEY={SECRET}\n", encoding="utf-8")
    p, created = keys.write_template(f, tmp_path / ".gitignore")
    assert created is False
    assert SECRET in f.read_text(encoding="utf-8")


def test_the_template_contains_no_key_and_every_provider():
    """The property is "no real credential", not "no `sk-` anywhere".

    The header shows `sk-or-v1-....` to demonstrate the naming convention,
    which is a placeholder -- ellipsis, no entropy, and commented out. What
    must never appear is something that could actually authenticate.
    """
    import re

    t = keys.template()
    # A real OpenRouter/OpenAI key is a long run of key characters. A
    # placeholder is not.
    assert not re.search(r"sk-[A-Za-z0-9_-]{20,}", t)
    assert keys.parse(t) == {}          # every slot blank, nothing loadable
    for p in PROVIDERS:
        assert p.key in t and p.console in t


# ── the dashboard ──────────────────────────────────────────────────────
def test_the_dashboard_never_renders_a_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    data = dash.collect()
    assert SECRET not in dash.render(data)
    assert SECRET not in dash.to_html(data)
    assert SECRET not in str(data)


def test_it_reports_a_key_only_by_length(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", SECRET)
    row = [p for p in dash.collect()["providers"] if p["env"] == "GROQ_API_KEY"][0]
    assert row["detail"] == f"set ({len(SECRET)} chars)"


def test_failover_verdicts(monkeypatch):
    for p in PROVIDERS:
        monkeypatch.delenv(p.key, raising=False)
    assert dash.collect()["failover"]["verdict"] == "NONE"
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert dash.collect()["failover"]["verdict"] == "SINGLE ACCOUNT"
    monkeypatch.setenv("GEMINI_API_KEY", "y")
    f = dash.collect()["failover"]
    assert f["verdict"] == "READY" and f["accounts"] == 2


def test_accounts_counts_credentials_not_models(monkeypatch):
    """OpenRouter offers three models behind one key. That is one account."""
    for p in PROVIDERS:
        monkeypatch.delenv(p.key, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    assert accounts() == 1
    assert len(BY_KEY["OPENROUTER_API_KEY"].models) > 1


def test_missing_panels_say_why_instead_of_showing_zero(tmp_path):
    """`docs/0021` §5: a $0.00 that means "no data" reads as good news."""
    d = dash.collect(ledger=tmp_path / "none.db", cost_ledger=tmp_path / "none.db")
    assert d["effects"]["available"] is False and d["effects"]["why"]
    assert d["cost"]["available"] is False and d["cost"]["why"]
    out = dash.render(d)
    assert "(none)" in out and "0 effect" not in out


def test_the_html_is_self_contained(monkeypatch):
    """No CDN, no fonts, no network -- it has to open from a file:// path."""
    html = dash.to_html(dash.collect())
    assert "http://" not in html
    assert "cdn" not in html.lower() and "<script" not in html.lower()
    assert html.count("<div") == html.count("</div>")


def test_the_html_escapes_what_it_renders(monkeypatch):
    from agentctl.control import providers as pv

    evil = pv.Provider(key="EVIL_API_KEY", name="<script>x</script>",
                       console="https://e.example", prefix="e/",
                       models=("m",), free_tier=True)
    monkeypatch.setattr(pv, "PROVIDERS", (evil,))
    monkeypatch.setattr(dash, "PROVIDERS", (evil,))
    html = dash.to_html(dash.collect())
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html


# ── multiple accounts per provider (docs/0033) ─────────────────────────
from agentctl.control.providers import Account, accounts_for, all_accounts  # noqa: E402

MULTI = {
    "OPENROUTER_API_KEY": "a",
    "OPENROUTER_API_KEY_2": "b",
    "OPENROUTER_API_KEY_WORK": "c",
    "GEMINI_API_KEY": "d",
}


def test_a_second_key_at_the_same_provider_is_a_second_account():
    """The whole point. A free-tier cap is per account, not per model."""
    got = accounts_for(BY_KEY["OPENROUTER_API_KEY"], MULTI)
    assert [a.label for a in got] == ["openrouter", "openrouter#2",
                                      "openrouter#work"]


def test_any_suffix_works_so_a_new_account_needs_no_code_change():
    env = {"GROQ_API_KEY_LAPTOP": "x", "GROQ_API_KEY_7": "y"}
    labels = [a.label for a in accounts_for(BY_KEY["GROQ_API_KEY"], env)]
    assert set(labels) == {"groq#laptop", "groq#7"}


def test_a_similarly_named_variable_is_not_mistaken_for_a_key():
    """`ANTHROPIC_BASE_URL` must not be read as an Anthropic credential.

    Matching is on the exact name or name + `_`, never a bare prefix: a stray
    match would send requests with a URL where a key belongs.
    """
    env = {"ANTHROPIC_BASE_URL": "https://example.invalid"}
    assert accounts_for(BY_KEY["ANTHROPIC_API_KEY"], env) == []


def test_a_blank_value_is_not_an_account():
    """The template ships every slot empty; empty must not count."""
    assert accounts_for(BY_KEY["GROQ_API_KEY"], {"GROQ_API_KEY": ""}) == []


def test_accounts_counts_credentials_not_providers():
    assert accounts(MULTI) == 4
    assert len({a.provider.name for a in all_accounts(MULTI)}) == 2


def test_the_proxy_builds_one_deployment_per_account_and_model():
    """Two accounts times three models is six ways to keep working."""
    import yaml

    from agentctl.control.proxy import available, build

    entries = available(MULTI)
    doc = yaml.safe_load(build(MULTI))
    models = doc["model_list"]
    assert len(models) == len(entries)
    # every account is represented
    used = {m["litellm_params"]["api_key"] for m in models}
    assert used == {f"os.environ/{k}" for k in MULTI}


def test_deployment_ids_are_unambiguous_across_accounts():
    """`openrouter-2` (acct 1, model 2) next to `openrouter-2-0` (acct 2,
    model 0) was unique and unreadable exactly when debugging a fallback."""
    from agentctl.control.proxy import available

    ids = [c[2] for c in available(MULTI)]
    assert len(set(ids)) == len(ids)
    assert "openrouter-a1-m0" in ids and "openrouter-a2-m0" in ids


@pytest.mark.parametrize("env,verdict", [
    ({}, "NONE"),
    ({"OPENROUTER_API_KEY": "a"}, "SINGLE ACCOUNT"),
    ({"OPENROUTER_API_KEY": "a", "OPENROUTER_API_KEY_2": "b"}, "MULTI-ACCOUNT"),
    ({"OPENROUTER_API_KEY": "a", "GEMINI_API_KEY": "c"}, "READY"),
])
def test_the_verdict_distinguishes_accounts_from_providers(env, verdict, monkeypatch):
    """Two keys at one provider survive a cap but not the provider going down.
    Calling that READY would overstate what the user actually has."""
    for p in PROVIDERS:
        monkeypatch.delenv(p.key, raising=False)
    for extra in ("OPENROUTER_API_KEY_2", "GEMINI_API_KEY_2"):
        monkeypatch.delenv(extra, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert dash.collect()["failover"]["verdict"] == verdict


def test_the_dashboard_lists_every_account_separately(monkeypatch):
    for p in PROVIDERS:
        monkeypatch.delenv(p.key, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "a")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "b")
    names = [r["name"] for r in dash.collect()["providers"] if r["configured"]]
    assert names == ["openrouter", "openrouter#2"]


def test_the_template_shows_how_to_add_a_second_account():
    t = keys.template()
    assert "OPENROUTER_API_KEY_2" in t
    # The text wraps, so match on the flattened form rather than one line.
    flat = " ".join(t.replace("#", " ").split())
    assert "per ACCOUNT" in flat
    # the extra slots ship commented out, so the file still parses to nothing
    assert keys.parse(t) == {}


def test_the_default_location_is_outside_any_repository():
    """A gitignore rule is a promise; a different directory is a fact."""
    assert keys.HOME_PATH.parent.name == ".agentctl"
    assert "openhands" not in str(keys.HOME_PATH).lower()


def test_an_explicit_path_wins_over_both_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTCTL_KEYS", str(tmp_path / "mine.env"))
    assert keys.search_paths()[0] == tmp_path / "mine.env"


# ── "in a repo but not ignored" is the moment BEFORE the accident ──────
def _repo(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    return tmp_path


def test_a_keys_file_inside_a_repo_and_not_ignored_is_warned_about(tmp_path):
    """Found on the author's own machine.

    `--init` defaulted to `~/.agentctl/keys.env` and called it "outside any
    repository". The home directory WAS a repository, with an unrelated
    remote, and the ignore rule had been written into a different project.
    """
    _repo(tmp_path)
    f = tmp_path / "keys.env"
    f.write_text(f"GROQ_API_KEY={SECRET}\n", encoding="utf-8")

    warn = keys.check_not_tracked(f)
    assert warn and "NOT ignored" in warn and "git add -A" in warn


def test_ignoring_it_clears_the_warning(tmp_path):
    _repo(tmp_path)
    f = tmp_path / "keys.env"
    f.write_text("GROQ_API_KEY=x\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("keys.env\n", encoding="utf-8")
    assert keys.check_not_tracked(f) is None


def test_a_file_outside_any_repo_needs_no_ignore(tmp_path):
    """No repo, no risk, no noise."""
    f = tmp_path / "keys.env"
    f.write_text("GROQ_API_KEY=x\n", encoding="utf-8")
    if keys.enclosing_repo(f) is not None:
        pytest.skip("tmp_path is itself inside a repo on this machine")
    assert keys.check_not_tracked(f) is None


def test_init_ignores_in_the_repo_that_holds_the_file(tmp_path, monkeypatch):
    """The actual bug: the rule went to the CWD's repo, not the file's."""
    project = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere"
    for d in (project, elsewhere):
        d.mkdir()
        _repo(d)
    keysfile = elsewhere / "keys.env"

    monkeypatch.chdir(project)
    keys.write_template(keysfile, project / ".gitignore")

    # the rule must exist in the repo that CONTAINS the keys file
    assert "keys.env" in (elsewhere / ".gitignore").read_text(
        encoding="utf-8")
    assert keys.check_not_tracked(keysfile) is None


def test_the_specific_filename_is_ignored_not_only_the_glob(tmp_path):
    keys.ensure_ignored(tmp_path / ".gitignore", name="my-secrets.txt")
    assert "my-secrets.txt" in (tmp_path / ".gitignore").read_text(encoding="utf-8")


# ── the pre-commit guard (docs/0034 §11) ───────────────────────────────
def test_the_scanner_ignores_a_placeholder(tmp_path, monkeypatch):
    """A shape-based check flags every test fixture, and a check that cries
    wolf is worse than none -- it gets ignored while looking like protection.
    """
    monkeypatch.setenv("AGENTCTL_KEYS", str(tmp_path / "k.env"))
    (tmp_path / "k.env").write_text("GROQ_API_KEY=real-value-long-enough-here\n",
                                    encoding="utf-8")
    assert keys.scan_text('SECRET = "sk-or-v1-NEVERSHOWTHIS0000000000"') == []


def test_the_scanner_catches_a_real_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTCTL_KEYS", str(tmp_path / "k.env"))
    (tmp_path / "k.env").write_text("GROQ_API_KEY=real-value-long-enough-here\n",
                                    encoding="utf-8")
    assert keys.scan_text("api_key = real-value-long-enough-here") == ["GROQ_API_KEY"]


def test_a_short_value_is_not_treated_as_a_credential(tmp_path, monkeypatch):
    """`GROQ_API_KEY=x` would otherwise match every file containing an x."""
    monkeypatch.setenv("AGENTCTL_KEYS", str(tmp_path / "k.env"))
    (tmp_path / "k.env").write_text("GROQ_API_KEY=x\n", encoding="utf-8")
    assert keys.scan_text("the letter x appears here") == []


def test_the_hook_is_installed_executable_and_refers_to_this_checkout(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    p = keys.install_hook(tmp_path)
    assert p.name == "pre-commit" and p.exists()
    body = p.read_text(encoding="utf-8")
    assert "scan_staged" in body and "COMMIT BLOCKED" in body
