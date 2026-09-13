r"""Record and replay, M6. `docs/0029`.

Two properties, and the second is the one people forget:

* a recorded session replays **identically** — same responses, no network
* a **changed** session is reported as diverged, loudly and with a position

A replayer that silently serves something plausible on a miss would produce
runs that look like replays and are not. That is the failure shape of
`docs/0024` (a crash that looked like a decision) and `docs/0028` (a guard
that could not fail), so it gets a test of its own.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from agentctl.control.replay import Cassette, ReplayServer, fingerprint, summarise
from agentctl.control.replay.cassette import canonical


def req(*contents: str, model: str = "gpt-x", tools=None) -> dict:
    return {"model": model,
            "messages": [{"role": "user", "content": c} for c in contents],
            "tools": tools or []}


def resp(text: str) -> dict:
    return {"id": "chatcmpl-1", "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2}}


# ── the fingerprint decides everything ─────────────────────────────────
def test_sampling_knobs_do_not_change_the_fingerprint():
    """Or a cassette would never hit twice."""
    base = req("hello")
    noisy = dict(base, temperature=0.7, max_tokens=512, api_key="sk-secret",
                 stream=False, litellm_call_id="abc-123")
    assert fingerprint(base) == fingerprint(noisy)


def test_a_different_message_is_a_different_fingerprint():
    assert fingerprint(req("hello")) != fingerprint(req("goodbye"))


def test_a_different_tool_schema_is_a_different_fingerprint():
    """Changing the tools changes what the model can answer."""
    a = req("hi", tools=[{"function": {"name": "read_file"}}])
    b = req("hi", tools=[{"function": {"name": "execute_bash"}}])
    assert fingerprint(a) != fingerprint(b)


def test_credentials_never_reach_the_canonical_form():
    c = canonical(dict(req("hi"), api_key="sk-or-v1-SECRET", base_url="http://x"))
    assert "SECRET" not in c and "sk-or" not in c


# ── replaying ──────────────────────────────────────────────────────────
def test_a_recorded_session_replays_identically():
    c = Cassette()
    c.append(req("one"), resp("first"))
    c.append(req("one", "two"), resp("second"))

    play = Cassette(c.turns)
    assert play.match(req("one")).response == resp("first")
    assert play.match(req("one", "two")).response == resp("second")
    assert not play.misses
    assert summarise(play)["diverged"] is False


def test_the_same_question_twice_gets_both_answers():
    """Not the first answer twice -- an agent may genuinely repeat itself."""
    c = Cassette()
    c.append(req("same"), resp("A"))
    c.append(req("same"), resp("B"))

    play = Cassette(c.turns)
    assert play.match(req("same")).response == resp("A")
    assert play.match(req("same")).response == resp("B")
    assert play.match(req("same")) is None      # only two were recorded


def test_a_divergence_is_reported_with_a_position():
    c = Cassette()
    c.append(req("one"), resp("first"))
    c.append(req("one", "two"), resp("second"))

    play = Cassette(c.turns)
    play.match(req("one"))
    assert play.match(req("one", "SOMETHING ELSE")) is None

    s = summarise(play)
    assert s["diverged"] is True and s["misses"] == 1
    assert "turn 1" in s["first_divergence"]
    assert "message 1" in s["first_divergence"]


def test_a_short_run_is_a_divergence_too():
    """Stopping early is a behaviour change, even with no miss."""
    c = Cassette()
    c.append(req("one"), resp("first"))
    c.append(req("one", "two"), resp("second"))

    play = Cassette(c.turns)
    play.match(req("one"))
    s = summarise(play)
    assert s["misses"] == 0
    assert s["unplayed"] == 1 and s["diverged"] is True


def test_running_past_the_end_says_so():
    c = Cassette()
    c.append(req("one"), resp("first"))
    play = Cassette(c.turns)
    play.match(req("one"))
    play.match(req("one", "more"))
    assert "recording ended" in play.misses[0].describe()


# ── round trip ─────────────────────────────────────────────────────────
def test_a_cassette_survives_disk(tmp_path):
    c = Cassette()
    c.append(req("one"), resp("first"), model="gpt-x", usage={"t": 1})
    c.append(req("one", "two"), resp("second"), model="gpt-x")
    path = c.save(tmp_path / "c.jsonl")

    back = Cassette.load(path)
    assert len(back) == 2
    assert back.turns[0].model == "gpt-x"
    assert back.match(req("one")).response == resp("first")


def test_loading_a_missing_cassette_says_which_one(tmp_path):
    with pytest.raises(FileNotFoundError, match="nope.jsonl"):
        Cassette.load(tmp_path / "nope.jsonl")


# ── the server ─────────────────────────────────────────────────────────
def _post(url: str, body: dict):
    r = urllib.request.Request(url, data=json.dumps(body).encode(),
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=10) as fh:
        return fh.status, json.loads(fh.read())


def test_the_server_answers_from_the_cassette():
    c = Cassette()
    c.append(req("one"), resp("first"))
    with ReplayServer(c) as s:
        code, body = _post(f"{s.base_url}/chat/completions", req("one"))
    assert code == 200
    assert body["choices"][0]["message"]["content"] == "first"


def test_the_server_refuses_to_invent_an_answer():
    """502, not a plausible completion. A miss must not look like a hit."""
    c = Cassette()
    c.append(req("one"), resp("first"))
    seen = []
    with ReplayServer(c, on_miss=seen.append) as s:
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(f"{s.base_url}/chat/completions", req("UNRECORDED"))
    assert e.value.code == 502
    err = json.loads(e.value.read())["error"]
    assert err["type"] == "agentctl_replay_miss"
    # the body must say WHERE it diverged, not merely that it did
    assert "cassette miss" in err["message"] and "turn 0" in err["message"]
    assert len(seen) == 1


def test_the_base_url_is_what_a_client_expects():
    with ReplayServer(Cassette()) as s:
        assert s.base_url.startswith("http://127.0.0.1:")
        assert s.base_url.endswith("/v1")


def test_models_endpoint_lists_what_was_recorded():
    c = Cassette()
    c.append(req("one"), resp("first"), model="openrouter/some-model")
    with ReplayServer(c) as s:
        with urllib.request.urlopen(f"{s.base_url}/models", timeout=10) as fh:
            body = json.loads(fh.read())
    assert body["data"][0]["id"] == "openrouter/some-model"


# ── the wire form carries fields the callback never saw (docs/0029 §4) ──
def test_wire_only_fields_do_not_break_a_cassette():
    """The bug that made every replay miss on turn 0.

    A cassette is recorded from a Python callback and matched against an HTTP
    body. The wire carries `prompt_cache_key` -- the conversation id, which is
    different on every run by definition -- and OpenRouter's
    `usage: {include: true}`. Neither was in the recorded form, and a deny-list
    fingerprint folded both in, so nothing could ever match.
    """
    recorded = req("hi")
    on_the_wire = dict(recorded,
                       prompt_cache_key="9e666cf5-0336-42ff-877d-5e95631872fb",
                       usage={"include": True},
                       temperature=0.0, stream=False)
    c = Cassette()
    c.append(recorded, resp("answer"))
    assert c.match(on_the_wire) is not None


def test_the_recorder_and_the_fingerprint_share_one_list():
    """Not equal lists -- the same object.

    These started as two lists, an allow-list in the recorder and a deny-list
    in the fingerprint. They drifted, and drift here means no cassette ever
    replays. Identity is what stops that recurring.
    """
    from agentctl.adapters.litellm import recorder
    from agentctl.control.replay.cassette import SIGNIFICANT_FIELDS

    assert recorder._REQUEST_KEYS is SIGNIFICANT_FIELDS


def test_a_field_that_does_decide_the_response_still_counts():
    """The allow-list is closed, so what IS on it must matter."""
    a = req("hi")
    b = dict(req("hi"), tool_choice="required")
    assert fingerprint(a) != fingerprint(b)


# ── a detached recorder must actually stop (docs/0029 §5) ──────────────
def test_a_detached_recorder_writes_nothing(tmp_path):
    """A replay run re-recorded itself into the cassette it was replaying.

    `detach` removed the recorder from `litellm.callbacks`, but litellm copies
    callbacks into its own per-kind lists on first use, so it stayed live in
    `success_callback` and kept writing -- doubling the file.
    """
    import litellm
    from agentctl.adapters.litellm.recorder import attach, detach

    path = tmp_path / "c.jsonl"
    rec = attach(path)
    litellm.success_callback.append(rec)        # what litellm does internally
    detach(rec)

    lists = [n for n in dir(litellm) if isinstance(getattr(litellm, n, None), list)]
    held = [n for n in lists if any(x is rec for x in getattr(litellm, n))]
    assert not held, f"litellm still holds the recorder in {held}"

    # And the guarantee that does not depend on litellm's internals: even a
    # leaked reference records nothing.
    rec.closed = True
    rec.log_success_event(
        {"model": "m", "messages": [{"role": "user", "content": "x"}]},
        {"choices": [{"message": {"content": "y"}}]}, 0, 1)
    assert len(rec.cassette) == 0


def test_a_closed_recorder_is_inert_even_if_still_registered(tmp_path):
    from agentctl.adapters.litellm.recorder import CassetteRecorder

    rec = CassetteRecorder(tmp_path / "c.jsonl")
    rec.closed = True
    rec.log_success_event(
        {"model": "m", "messages": [{"role": "user", "content": "x"}]},
        {"choices": [{"message": {"content": "y"}}]}, 0, 1)
    assert len(rec.cassette) == 0 and rec.errors == 0


# ── a cassette is bound to its environment (docs/0029 §6) ──────────────
def test_a_cassette_records_where_it_was_made():
    from agentctl.control.replay import current_env

    c = Cassette()
    t = c.append(req("hi"), resp("yo"))
    assert t.env["platform"] and t.env["openhands_sdk"]
    assert t.env == current_env()


def test_a_foreign_platform_is_refused_not_replayed():
    """The CI failure: a Windows recording missed on turn 0 under Linux.

    The SDK writes the shell name into the system prompt, so message 0 differs
    and nothing can match. Reporting that as a divergence would be wrong --
    the code did not change, the machine did.
    """
    from agentctl.control.replay import incompatible

    c = Cassette()
    c.append(req("hi"), resp("yo"))
    c.turns[0].env = {"platform": "some-other-os", "openhands_sdk": "1.45.0"}
    why = incompatible(c)
    assert why and "some-other-os" in why and "system prompt" in why


def test_the_same_platform_is_allowed():
    from agentctl.control.replay import incompatible

    c = Cassette()
    c.append(req("hi"), resp("yo"))
    assert incompatible(c) is None


def test_an_empty_cassette_is_refused():
    from agentctl.control.replay import incompatible

    assert incompatible(Cassette()) == "the cassette is empty"
