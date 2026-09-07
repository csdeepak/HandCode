"""
Shared tool definition for the M0 spike, built against the REAL SDK API
discovered by probe_00.

Corrections to what `docs/0012` assumed:

  * `register_tool(name, factory)` takes a `ToolDefinition` (or subclass),
    NOT a `ToolExecutor`.
  * `ToolExecutor.__call__(action, conversation=None)` — two positional args.
  * `ToolDefinition` carries the executor in an `executor` FIELD, which means
    Seam C can wrap the executor on a definition rather than subclassing
    anything. That is cleaner than the design in `docs/0012` §4.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Sequence

from pydantic import Field

from openhands.sdk.tool import (
    Action,
    Observation,
    ToolDefinition,
    ToolExecutor,
    register_tool,
)

TOOL_NAME = "side_effect"   # SDK strips a "_tool" suffix; avoid it


class SideEffectAction(Action):
    payload: str = Field(default="m0", description="Marker written to the log.")


class SideEffectObservation(Observation):
    status: str = Field(default="ok")

    @property
    def agent_observation(self):                      # rendered back to the model
        from openhands.sdk.llm import TextContent
        return [TextContent(text=f"side effect status={self.status}")]


class SideEffectExecutor(ToolExecutor):
    """Appends a line, fsyncs, signals the parent, then sleeps.

    Non-idempotent by construction: two calls produce two lines.
    """

    def __init__(self, log_path: Path, marker: Path, sleep_s: float):
        self.log_path, self.marker, self.sleep_s = log_path, marker, sleep_s

    def __call__(self, action, conversation=None):
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"EFFECT ts={time.time():.3f} pid={os.getpid()}\n")
            fh.flush()
            os.fsync(fh.fileno())
        # Signal ONLY after the effect is durable, so the parent's kill lands
        # in the genuinely ambiguous window (docs/0008 §6.5).
        self.marker.write_text(str(time.time()), encoding="utf-8")
        time.sleep(self.sleep_s)
        return SideEffectObservation(status="ok")


class SideEffectTool(ToolDefinition[SideEffectAction, SideEffectObservation]):
    @classmethod
    def create(cls, conv_state=None, **params) -> Sequence["SideEffectTool"]:
        log_path = Path(params.get("log_path", "side_effect.log"))
        marker = Path(params.get("marker", "tool_entered.marker"))
        sleep_s = float(params.get("sleep_s", 6.0))
        return [cls(
            name=TOOL_NAME,
            description="Append a line to a log file, then sleep. Call it once.",
            action_type=SideEffectAction,
            observation_type=SideEffectObservation,
            executor=SideEffectExecutor(log_path, marker, sleep_s),
        )]


def register() -> None:
    register_tool(TOOL_NAME, SideEffectTool)
