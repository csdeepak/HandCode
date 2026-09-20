r"""`tool_concurrency_limit` must be pinned to 1, not merely defaulted to it.

`docs/0038` §4.3: `ResourceLockManager` falls back to a per-*tool-name* mutex
when a tool does not implement `declared_resources()`
(`openhands/sdk/tool/tool.py::ToolDefinition.declared_resources`, base default
`DeclaredResources(keys=(), declared=False)` ->
`ParallelToolExecutor._resolve_lock_keys` maps that to `[f"tool:{name}"]`).
None of `agentctl/runtime/tools.py`'s three tools implement it. So `bash`
(which can `git commit`) and `write_file` take *different* lock keys and would
run concurrently the moment `tool_concurrency_limit` rises above the SDK's
default of 1 -- racing a single-writer ledger and a git probe that both assume
one writer, and racing it *silently*: every ledger write happens on the agent
thread (`_ActionBatch.prepare` collects worker results before `emit`), so
there is no `ProgrammingError` to notice. `agentctl` never set the limit
before this file existed, which is exactly the "would not fail loudly" shape
the decision record is closing.

Two guarantees, and they are different in kind:

* the pin actually takes (`test_build_agent_pins_tool_concurrency_limit_to_one`)
* the pin cannot silently stop taking, whether the SDK's own default changes
  or something in `_build_agent` stops enforcing it
  (`test_build_agent_raises_if_the_pin_does_not_take`)
* there is exactly one place in `agentctl/` allowed to construct an `Agent`,
  so a *second* call site -- a new CLI flag, an inlined refactor -- cannot
  bypass the check above by construction
  (`test_agent_is_constructed_only_through_build_agent`)
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import agentctl.runtime.runner as runner_mod
from agentctl.runtime import tools as rt


def _llm():
    """A real, network-free `LLM`. Construction is pydantic validation only;
    the network is touched at `conv.run()`, which nothing here calls."""
    from openhands.sdk import LLM

    return LLM(model="openrouter/test/test:free", api_key="test",
               service_id="agentctl-test", temperature=0.0,
               num_retries=2, max_output_tokens=4096)


def test_build_agent_pins_tool_concurrency_limit_to_one():
    agent = runner_mod._build_agent(_llm(), rt.TOOLS)
    assert agent.tool_concurrency_limit == 1


def test_build_agent_raises_if_the_pin_does_not_take(monkeypatch):
    """Route, not just result (`docs/0024`): the check must actually fire.

    Stands in for two real failure shapes: a future SDK release that ignores
    the kwarg, or a future edit to `_build_agent` that drops it. Either way,
    `_build_agent` must refuse to hand back an Agent whose limit is not 1 --
    silently returning it is exactly the hazard this item exists to close.
    """
    class _IgnoresThePin:
        def __init__(self, **kwargs):
            self.tool_concurrency_limit = 4  # simulates a bypassed pin

    monkeypatch.setattr("openhands.sdk.Agent", _IgnoresThePin)

    with pytest.raises(RuntimeError, match="tool_concurrency_limit"):
        runner_mod._build_agent(_llm(), rt.TOOLS)


def test_agent_is_constructed_only_through_build_agent():
    """A second `Agent(...)` call site anywhere in `agentctl/` would bypass
    the pin above entirely, and nothing else in this suite would notice.

    Scoped to `agentctl/` only. `experiments/*/run_*.py` also construct
    `Agent(...)` directly and are *not* covered here -- out of this item's
    ownership, and each registers a single tool, which is lower exposure than
    `agentctl run`'s three. Known, accepted gap (Phase 1 report to the
    integrator).
    """
    root = Path(__file__).resolve().parents[1] / "agentctl"
    pattern = re.compile(r"\bAgent\(")
    hits = [
        f"{f.relative_to(root.parent).as_posix()}:{i}"
        for f in sorted(root.rglob("*.py"))
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]

    assert hits == [h for h in hits if h.startswith("agentctl/runtime/runner.py:")], (
        f"an Agent(...) is constructed outside runner.py, bypassing the "
        f"tool_concurrency_limit pin: {hits}. Route it through "
        f"runner._build_agent instead."
    )
    assert len(hits) == 1, (
        f"expected exactly one Agent(...) construction in agentctl/, found "
        f"{hits}. A second call site inside runner.py also bypasses the "
        f"single-source-of-truth this pin depends on."
    )
    assert "Agent(" in inspect.getsource(runner_mod._build_agent), (
        "the one call site moved out of _build_agent -- the pin and its "
        "check must travel with the construction, not be left behind"
    )
