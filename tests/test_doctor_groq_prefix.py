r"""Tripwire for the two facts `doctor.py` prices Groq's turn-2 ceiling
against.

`agentctl/runtime/doctor.py` pins `_FIXED_PREFIX_TOKENS` and
`_RUNNER_MAX_OUTPUT_TOKENS` as dated constants rather than re-deriving them on
every `agentctl doctor` run -- importing the SDK and instantiating the real
agent costs ~10s, which is fine once in CI and wrong to pay on every preflight.

This file is what keeps those constants honest. It re-measures the real
prefix live (same method that produced `research/phase-10-2` V5) and reads
`runner.py`'s own source for its `max_output_tokens` literal, and fails
loudly if either has drifted from what `doctor.py` assumes -- the update-the-
constant-not-the-test discipline `docs/0021` §7 and `providers.py`'s own
docstring both ask for elsewhere in this project.

Kept separate from `test_doctor.py` deliberately: slow (SDK import dominates)
and needs the `openhands` extra, unlike the rest of the preflight suite.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytest.importorskip("tiktoken")
pytest.importorskip("openhands.sdk")


def _measure_fixed_prefix() -> int:
    """The static system prompt plus this runner's tool schemas -- exactly
    what `agentctl run` pays on every request before a single turn of
    conversation happens. Same method as `measure_prompt.py` used for V5.
    """
    import tiktoken
    from openhands.sdk import LLM, Agent
    from openhands.sdk.tool import Tool, register_tool

    from agentctl.runtime import tools as rt

    enc = tiktoken.get_encoding("cl100k_base")
    for name, cls in rt.TOOLS.items():
        try:
            register_tool(name, cls)
        except Exception:
            pass  # already registered by an earlier test in this process

    llm = LLM(model="openrouter/x", api_key="x", service_id="m", usage_id="m")
    agent = Agent(llm=llm, tools=[Tool(name=n) for n in rt.TOOLS],
                  include_default_tools=[])

    sysmsg = agent.static_system_message
    assert isinstance(sysmsg, str) and sysmsg, (
        "Agent.static_system_message changed shape -- re-check how doctor.py "
        "should measure the prefix, not just the number")
    sys_tokens = len(enc.encode(sysmsg))

    tools = getattr(agent, "_tools", None) or {}
    if not tools:
        from openhands.sdk.tool.registry import resolve_tool
        for n in rt.TOOLS:
            for t in resolve_tool(Tool(name=n), conv_state=None):
                tools[t.name] = t
    assert tools, "could not resolve any tool schema -- SDK shape changed"
    schemas = [t.to_openai_tool() for t in tools.values()]
    schema_tokens = len(enc.encode(json.dumps(schemas)))

    return sys_tokens + schema_tokens


def test_measured_prefix_matches_the_constant_doctor_prices_groq_against():
    """If this fails, `runner.py`'s tool set or the SDK's system prompt has
    moved since 2026-09-20. Update `doctor._FIXED_PREFIX_TOKENS` and its
    `_PREFIX_MEASURED` date to match -- do not widen this test instead.
    """
    from agentctl.runtime import doctor as d

    measured = _measure_fixed_prefix()
    assert measured == d._FIXED_PREFIX_TOKENS, (
        f"measured {measured} tokens live, doctor.py still says "
        f"{d._FIXED_PREFIX_TOKENS} -- the Groq headroom arithmetic is stale")


def test_runner_still_requests_the_max_output_tokens_doctor_assumes():
    """`doctor.py` cannot import this value -- `runner.py` has no module-level
    constant for it, only a literal inside the `LLM(...)` call at line 189.
    This test is the sync mechanism: if `runner.py` (owned by another agent)
    changes the literal, this fails here rather than `doctor` silently
    quoting a headroom number nobody meant any more.
    """
    import agentctl.runtime.runner as runner_mod
    from agentctl.runtime import doctor as d

    src = Path(runner_mod.__file__).read_text(encoding="utf-8")
    m = re.search(r"max_output_tokens=(\d+)", src)
    assert m, "runner.py no longer sets max_output_tokens by that name"
    assert int(m.group(1)) == d._RUNNER_MAX_OUTPUT_TOKENS, (
        f"runner.py now requests max_output_tokens={m.group(1)}, doctor.py "
        f"still assumes {d._RUNNER_MAX_OUTPUT_TOKENS} -- update the constant")
