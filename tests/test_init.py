"""`agentctl init` and where `run` gets its defaults. `docs/0043` Phase 2.

Phase 0 (`docs/0044`): nine commands to a first task, and a built-in model
that only an OpenRouter key could use. The promise now is three commands with
one key, and every default traceable to where it came from.
"""
from __future__ import annotations

import io

import pytest

from agentctl.control import keys
from agentctl.control.probe import LIMITED, LIVE, UNREACHABLE, Result
from agentctl.control.providers import BY_NAME, PROVIDERS, Account
from agentctl.runtime import config
from agentctl.runtime.init import run_init


@pytest.fixture
def clean(tmp_path, monkeypatch):
    """No provider keys, no config, a private home for the keys file."""
    for p in PROVIDERS:
        monkeypatch.delenv(p.key, raising=False)
        for k in list(__import__("os").environ):
            if k.startswith(p.key + "_"):
                monkeypatch.delenv(k, raising=False)
    for v in config.ENV.values():
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("AGENTCTL_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setattr(keys, "HOME_PATH", tmp_path / "home" / "keys.env")
    return tmp_path


def _probe(monkeypatch, status, model="", detail="x"):
    calls = []

    def fake(name, allow_paid=False):
        calls.append((name, allow_paid))
        acct = Account(BY_NAME[name], BY_NAME[name].key, name)
        return Result(acct, status, detail, model=model)

    monkeypatch.setattr("agentctl.control.probe.check_inference", fake)
    return calls


# ══ precedence ═════════════════════════════════════════════════════════
def test_a_flag_beats_everything(clean, monkeypatch):
    monkeypatch.setenv("AGENTCTL_MODEL", "env/m")
    config.write({"model": "cfg/m"})
    s = config.resolve("model", "flag/m")
    assert (s.value, s.source) == ("flag/m", "flag")


def test_env_beats_config(clean, monkeypatch):
    monkeypatch.setenv("AGENTCTL_MODEL", "env/m")
    config.write({"model": "cfg/m"})
    assert config.resolve("model", None).value == "env/m"


def test_config_beats_derived(clean, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    config.write({"model": "cfg/m"})
    s = config.resolve("model", None)
    assert s.value == "cfg/m" and "config" in s.source


def test_derived_follows_the_key_you_hold(clean, monkeypatch):
    """Phase 0 F2: the built-in default was an OpenRouter id, whatever you held."""
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    s = config.resolve("model", None)
    assert s.value == BY_NAME["gemini"].default_model
    assert "unverified" in s.source


def test_free_tiers_come_before_paid(clean, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("MISTRAL_API_KEY", "m")
    assert config.resolve("model", None).value.startswith("mistral/")


def test_nothing_at_all_is_unset(clean):
    assert config.resolve("model", None).value is None


def test_a_broken_config_refuses_rather_than_falls_back(clean):
    config.path().write_text("model = \n", encoding="utf-8")
    with pytest.raises(SystemExit, match="not valid TOML"):
        config.load()


def test_write_then_load_round_trips_awkward_strings(clean):
    config.write({"model": 'a"b\\c', "base_url": "http://x:4000"})
    assert config.load() == {"model": 'a"b\\c', "base_url": "http://x:4000"}


def test_the_registry_default_for_openrouter_is_not_the_dead_model():
    """`docs/0044` §10: nex-agi stopped serving; it is no longer first."""
    assert "nex-agi" not in BY_NAME["openrouter"].default_model


# ══ init ═══════════════════════════════════════════════════════════════
def test_init_records_the_model_that_answered(clean, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    _probe(monkeypatch, LIVE, model="nvidia/some-model:free")
    assert run_init(interactive=False) == 0
    assert config.load()["model"] == "openrouter/nvidia/some-model:free"
    assert "answered a completion" in config.path().read_text(encoding="utf-8")


def test_init_keeps_an_existing_base_url(clean, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    config.write({"model": "old", "base_url": "http://localhost:4000"})
    _probe(monkeypatch, LIVE, model="m:free")
    run_init(interactive=False)
    assert config.load()["base_url"] == "http://localhost:4000"


def test_a_rate_limited_key_is_still_set_up(clean, monkeypatch):
    """The key is fine; the cap clears. Refusing here would be a false
    'it will not work', which Phase 0 counted twice (`docs/0044` N5, N6)."""
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    _probe(monkeypatch, LIMITED)
    assert run_init(interactive=False) == 0
    assert config.load()["model"] == BY_NAME["gemini"].default_model


def test_a_key_that_cannot_serve_changes_nothing(clean, monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    _probe(monkeypatch, UNREACHABLE, detail="HTTP 401 unauthorized")
    assert run_init(interactive=False) == 1
    assert not config.path().exists()
    assert "401" in capsys.readouterr().out


def test_a_paid_provider_is_not_called_unless_asked(clean, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    calls = _probe(monkeypatch, LIVE, model="x")
    assert run_init(interactive=False) == 0
    assert calls == [], "docs/0002 §5: never silently spend"
    assert config.load()["model"] == BY_NAME["anthropic"].default_model


def test_a_paid_provider_is_checked_with_check_paid(clean, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    calls = _probe(monkeypatch, LIVE, model="claude-x")
    run_init(interactive=False, check_paid=True)
    assert calls == [("anthropic", True)]


def test_no_key_and_no_terminal_says_how(clean, capsys):
    assert run_init(interactive=False) == 2
    out = capsys.readouterr().out
    assert "--key-stdin" in out and "export" in out


def test_a_key_from_stdin_is_saved_and_never_printed(clean, monkeypatch, capsys):
    secret = "sk-or-v1-THISMUSTNOTAPPEAR"
    monkeypatch.setattr("sys.stdin", io.StringIO(secret + "\n"))
    _probe(monkeypatch, LIVE, model="m:free")
    assert run_init(provider="openrouter", key_stdin=True, interactive=False) == 0
    assert secret not in capsys.readouterr().out
    assert keys.parse(keys.HOME_PATH.read_text(encoding="utf-8"))[
        "OPENROUTER_API_KEY"] == secret


def test_an_unknown_provider_is_named(clean, capsys):
    assert run_init(provider="nope", interactive=False) == 2
    assert "openrouter" in capsys.readouterr().out


# ══ writing one key ════════════════════════════════════════════════════
def test_set_value_replaces_rather_than_duplicates(tmp_path):
    f = tmp_path / "keys.env"
    keys.set_value(f, "GROQ_API_KEY", "one")
    keys.set_value(f, "GROQ_API_KEY", "two")
    text = f.read_text(encoding="utf-8")
    assert keys.parse(text)["GROQ_API_KEY"] == "two"
    assert sum(1 for l in text.splitlines() if l.startswith("GROQ_API_KEY=")) == 1


@pytest.mark.parametrize("bad", ["", "a\nINJECTED=1", "x\r"])
def test_set_value_refuses_anything_but_one_line(tmp_path, bad):
    with pytest.raises(ValueError):
        keys.set_value(tmp_path / "keys.env", "GROQ_API_KEY", bad)


# ══ run, with nothing configured ═══════════════════════════════════════
def test_run_with_no_model_anywhere_points_at_init(clean, capsys):
    from agentctl.cli import main
    assert main(["run", "do a thing", "--workspace", str(clean)]) == 2
    assert "agentctl init" in capsys.readouterr().out
