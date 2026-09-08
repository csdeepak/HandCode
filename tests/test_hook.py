"""Seam A. docs/0012 §3.4, docs/0021.

The logic is tested here without the proxy; docs/0021 proves the hook actually
fires inside one, which is the part LiteLLM can silently skip.
"""
import pytest

from agentctl.kernel.hook import (
    RequestHook, TurnAffinity, ends_with_unresolved_tool_calls, turn_signature,
)


def assistant(*ids):
    return {"role": "assistant",
            "tool_calls": [{"id": i, "type": "function",
                            "function": {"name": "f", "arguments": "{}"}} for i in ids]}


def tool_result(i):
    return {"role": "tool", "tool_call_id": i, "content": "ok"}


# ── mid-turn detection: the hazard in docs/0010 §7.3 ──────────────────
def test_unresolved_tool_calls_are_mid_turn():
    assert ends_with_unresolved_tool_calls(
        [{"role": "user", "content": "hi"}, assistant("call_1")])


def test_resolved_tool_calls_are_not_mid_turn():
    assert not ends_with_unresolved_tool_calls(
        [{"role": "user", "content": "hi"}, assistant("call_1"), tool_result("call_1")])


def test_partially_resolved_is_still_mid_turn():
    """Two calls, one answered: the turn is not finished."""
    assert ends_with_unresolved_tool_calls(
        [assistant("call_1", "call_2"), tool_result("call_1")])


def test_a_new_assistant_turn_supersedes_dangling_calls():
    assert not ends_with_unresolved_tool_calls(
        [assistant("call_1"), tool_result("call_1"),
         {"role": "assistant", "content": "done"}])


def test_a_user_message_abandons_the_turn():
    """The user interrupted; there is nothing to pin to."""
    assert not ends_with_unresolved_tool_calls(
        [assistant("call_1"), {"role": "user", "content": "stop"}])


def test_no_messages_is_not_mid_turn():
    assert not ends_with_unresolved_tool_calls(None)
    assert not ends_with_unresolved_tool_calls([])


def test_turn_signature_is_the_first_outstanding_call():
    assert turn_signature([assistant("call_b", "call_a")]) == "call_a"


# ── the rule: the turn is the atomic unit of routing ──────────────────
def test_a_mid_turn_request_is_pinned_to_the_opening_deployment():
    hook = RequestHook()
    opening = {"model": "pool/acct-a", "messages": [{"role": "user", "content": "go"}],
               "metadata": {}}
    hook.apply(opening)

    # The router would now be free to pick acct-b. It must not.
    mid = {"model": "pool/acct-b",
           "messages": [{"role": "user", "content": "go"}, assistant("call_1")],
           "metadata": {}}
    # The opening request had no tool calls, so pin under that turn signature.
    hook.affinity.remember(turn_signature(mid["messages"]), "pool/acct-a")
    out = hook.apply(mid)
    assert out["model"] == "pool/acct-a"
    assert out["metadata"]["agentctl_pinned"] == "pool/acct-a"


def test_between_turns_the_router_is_left_alone():
    """Failover between turns is cheap and must not be blocked."""
    hook = RequestHook()
    data = {"model": "pool/acct-b",
            "messages": [assistant("call_1"), tool_result("call_1")],
            "metadata": {}}
    assert hook.apply(data)["model"] == "pool/acct-b"
    assert data["metadata"]["agentctl_mid_turn"] is False


def test_an_unknown_turn_is_not_pinned_to_anything():
    hook = RequestHook()
    data = {"model": "pool/acct-b", "messages": [assistant("call_9")], "metadata": {}}
    out = hook.apply(data)
    assert out["model"] == "pool/acct-b", "no pin recorded, so do not invent one"
    assert "agentctl_pinned" not in out["metadata"]


# ── attribution ───────────────────────────────────────────────────────
def test_trace_id_carries_conversation_and_turn():
    hook = RequestHook()
    data = {"model": "m", "messages": [assistant("call_7")],
            "metadata": {"conversation_id": "conv_1"}}
    hook.apply(data)
    assert data["metadata"]["agentctl_trace_id"] == "conv_1:call_7"


def test_trace_id_falls_back_to_the_sdk_session_header():
    """docs/0015 §5: the SDK already sends x-litellm-session-id."""
    hook = RequestHook()
    data = {"model": "m", "messages": [assistant("call_7")], "metadata": {},
            "extra_headers": {"x-litellm-session-id": "conv_from_header"}}
    hook.apply(data)
    assert data["metadata"]["agentctl_trace_id"] == "conv_from_header:call_7"


# ── telemetry the cost ledger will need ───────────────────────────────
def test_record_extracts_cost_and_cache_tokens():
    hook = RequestHook()
    rec = hook.record(
        {"model": "m", "response_cost": 0.0042,
         "metadata": {"agentctl_trace_id": "conv:turn"},
         "litellm_params": {"model_info": {"id": "acct-a"}}},
        {"usage": {"prompt_tokens": 100, "completion_tokens": 20,
                   "prompt_tokens_details": {"cached_tokens": 80}}},
        start=1.0, end=2.5)
    assert rec["cost"] == 0.0042
    assert rec["cached_tokens"] == 80
    assert rec["deployment"] == "acct-a"
    assert rec["latency_s"] == 1.5
    assert rec["trace_id"] == "conv:turn"


def test_record_survives_a_response_with_no_usage():
    assert RequestHook().record({"model": "m"}, {})["prompt_tokens"] is None


# ── affinity map hygiene ──────────────────────────────────────────────
def test_pins_expire():
    a = TurnAffinity(ttl_s=-1)
    a.remember("call_1", "acct-a")
    assert a.pinned("call_1") is None


def test_losing_the_map_costs_pinning_not_correctness():
    """docs/0008 R2: the hot path must not depend on shared state."""
    a = TurnAffinity()
    a.remember("call_1", "acct-a")
    assert a.pinned("call_1") == "acct-a"
    assert TurnAffinity().pinned("call_1") is None      # a fresh process: no pin


def test_telemetry_is_written_to_disk(tmp_path):
    import json
    p = tmp_path / "telemetry.json"
    hook = RequestHook(telemetry_path=p)
    hook.apply({"model": "m", "messages": [{"role": "user", "content": "hi"}],
                "metadata": {}})
    assert json.loads(p.read_text(encoding="utf-8"))["calls"][0]["model"] == "m"


# ── where LiteLLM actually puts the metadata (docs/0021 §4) ───────────
def test_trace_id_is_read_from_litellm_params_metadata():
    """The non-obvious one, and M5 depends on it.

    Anything the pre-call hook writes into data["metadata"] arrives on the
    logging callback under litellm_params.metadata. kwargs["metadata"] is
    empty. Reading only the obvious place yields trace_id=None and silently
    breaks cost attribution.
    """
    rec = RequestHook().record(
        {"model": "m",
         "metadata": {},                                  # empty, as observed
         "litellm_params": {"metadata": {"agentctl_trace_id": "conv:turn"},
                            "model_info": {"id": "acct-b"}}},
        {"usage": {"prompt_tokens": 10}})
    assert rec["trace_id"] == "conv:turn"
    assert rec["deployment"] == "acct-b"


def test_top_level_metadata_still_wins_when_present():
    rec = RequestHook().record(
        {"model": "m",
         "metadata": {"agentctl_trace_id": "top"},
         "litellm_params": {"metadata": {"agentctl_trace_id": "nested"}}},
        {})
    assert rec["trace_id"] == "top"


def test_an_unpriced_endpoint_reports_zero_not_none(tmp_path):
    """Q18: litellm reports 0.0 for a model it cannot price.

    Worse than None -- a real zero and an unknown cost look identical, so a
    budget guard silently under-counts exactly where it matters.
    """
    rec = RequestHook().record({"model": "mock-model", "response_cost": 0.0}, {})
    assert rec["cost"] == 0.0
    assert not rec["cost"], "an unpriced call is indistinguishable from a free one"
