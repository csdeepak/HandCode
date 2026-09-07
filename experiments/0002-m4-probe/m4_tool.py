"""Git-committing tool for the M4 probe experiment.

Module level, not nested inside a function: on resume the SDK must resolve
these classes to deserialize the persisted ActionEvent. Locally-defined classes
are not importable, and the replay silently does nothing.

Learned the hard way — the M4 chaos run reported no resume decision at all
until this moved out of `child()`.
"""
from __future__ import annotations

import os
import subprocess
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

TOOL_NAME = "commit"          # the SDK normalises names; use the final form
MARKER_ENV = "M4_MARKER"
REPO_ENV = "M4_REPO"
SLEEP_ENV = "M4_SLEEP"


class CommitAction(Action):
    message: str = Field(default="agent work", description="Commit message.")
    cwd: str = Field(default="", description="Repo root; the probe reads this.")


class CommitObservation(Observation):
    status: str = Field(default="ok")

    @property
    def agent_observation(self):
        from openhands.sdk.llm import TextContent
        return [TextContent(text=f"commit {self.status}")]


class CommitExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        repo = Path(action.cwd or os.environ.get(REPO_ENV, "."))
        subprocess.run(
            ["git", "commit", "--allow-empty", "-m", action.message],
            cwd=str(repo), capture_output=True, text=True,
        )
        # Signal only AFTER the effect has landed, so the kill lands in the
        # genuinely ambiguous window.
        if (marker := os.environ.get(MARKER_ENV)):
            Path(marker).write_text(str(time.time()), encoding="utf-8")
        time.sleep(float(os.environ.get(SLEEP_ENV, "6")))
        return CommitObservation(status="ok")


class CommitTool(ToolDefinition[CommitAction, CommitObservation]):
    @classmethod
    def create(cls, conv_state=None, **params) -> Sequence["CommitTool"]:
        repo = str(params.get("repo") or os.environ.get(REPO_ENV, "."))
        return [cls(
            name=TOOL_NAME,
            description="Make an empty git commit in the workspace repo.",
            action_type=CommitAction,
            observation_type=CommitObservation,
            executor=CommitExecutor(),
            meta={"repo": repo},
        )]


def register() -> None:
    register_tool(TOOL_NAME, CommitTool)
