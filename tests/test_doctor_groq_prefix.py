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


#: How far the live measurement may sit from the recorded constant.
#:
#: Exact equality was the original rule, and CI falsified it within the hour:
#: 3,593 tokens on Windows, **3,591 on Linux**, same commit, same SDK, same
#: tiktoken encoding. No OS string and no path appears in either the system
#: prompt or the tool schemas, so the cause is not identified — and a constant
#: nobody can explain to two decimal places should not be asserted to two
#: decimal places.
#:
#: The tripwire's job is to catch the tool set changing or the SDK revising
#: its prompt. Either is **hundreds** of tokens: `runner.py` declares three
#: tools whose schemas total 385, so losing or gaining one moves this by ~130.
#: 32 is comfortably below that and far above the 2 observed, which is the
#: definition of a useful band.
PREFIX_TOLERANCE = 32


def test_measured_prefix_matches_the_constant_doctor_prices_groq_against():
    """If this fails, `runner.py`'s tool set or the SDK's system prompt has
    moved since 2026-09-20. Update `doctor._FIXED_PREFIX_TOKENS` and its
    `_PREFIX_MEASURED` date to match.

    An earlier version demanded exact equality and said *"do not widen this
    test instead"* — sound advice against drift over TIME, which is what it
    was written for. It did not anticipate variation across PLATFORM, where
    no single constant can satisfy both and updating it only moves the
    failure to the other OS.
    """
    from agentctl.runtime import doctor as d

    measured = _measure_fixed_prefix()
    drift = abs(measured - d._FIXED_PREFIX_TOKENS)
    assert drift <= PREFIX_TOLERANCE, (
        f"measured {measured} tokens live, doctor.py says "
        f"{d._FIXED_PREFIX_TOKENS} -- a drift of {drift}, past the {PREFIX_TOLERANCE}"
        f"-token band that separates environment noise from a real change. "
        f"The tool set or the SDK's system prompt has moved; update "
        f"_FIXED_PREFIX_TOKENS and _PREFIX_MEASURED.")


def test_the_headroom_conclusion_survives_the_measured_prefix():
    """The number the user is shown, not the constant behind it.

    A tolerance band is only honest if the thing it protects is insensitive
    across that band. Groq's ceiling leaves ~311 tokens of conversation; 32
    either way cannot turn "turn 2 of most real tasks will 413" into a
    different sentence, and this asserts that rather than assuming it.
    """
    from agentctl.runtime import doctor as d

    measured = _measure_fixed_prefix()
    live = d._GROQ_TPM_CEILING - d._RUNNER_MAX_OUTPUT_TOKENS - measured
    quoted = d._GROQ_TPM_CEILING - d._RUNNER_MAX_OUTPUT_TOKENS - d._FIXED_PREFIX_TOKENS

    assert 0 < live < 1000, (
        f"headroom measured {live} tokens -- outside the range in which "
        f"'turn 2 will 413' is the right thing to tell the user")
    assert abs(live - quoted) <= PREFIX_TOLERANCE


def test_runner_still_requests_the_max_output_tokens_doctor_assumes():
    """`doctor.py` cannot import this value -- `runner.py` has no module-level
    constant for it, only a literal inside the `LLM(...)` call at line 221.
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
