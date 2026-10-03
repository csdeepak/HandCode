"""The demo's side-effecting tool: a real `git commit`, with a crash window.

Module level on purpose: on resume the SDK resolves these classes to
deserialize the persisted ActionEvent, and a class defined inside a function
is not importable -- the resume then silently does nothing (`docs/0017`).
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Sequence

from pydantic import Field

from openhands.sdk.tool import (Action, Observation, ToolDefinition, ToolExecutor,
                                register_tool)

NAME = "commit"
REPO_ENV, MARKER_ENV, SLEEP_ENV = ("AGENTCTL_DEMO_REPO", "AGENTCTL_DEMO_MARKER",
                                   "AGENTCTL_DEMO_SLEEP")


class CommitAction(Action):
    # Only the message is the model's. WHERE a commit lands never is
    # (`docs/0023` §3: a real model filled a `cwd` field with ".").
    message: str = Field(default="agent work", description="Commit message.")


class CommitObservation(Observation):
    status: str = Field(default="ok")

    @property
    def agent_observation(self):
        from openhands.sdk.llm import TextContent
        return [TextContent(text=f"commit {self.status}")]


class CommitExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        repo = Path(os.environ[REPO_ENV])
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", action.message],
                       cwd=str(repo), capture_output=True, text=True)
        # Signal only AFTER the commit landed, so the kill falls in the window
        # where the effect happened and the record of it did not.
        if (marker := os.environ.get(MARKER_ENV)):
            Path(marker).write_text(str(time.time()), encoding="utf-8")
        time.sleep(float(os.environ.get(SLEEP_ENV, "8")))
        return CommitObservation(status="ok")


class CommitTool(ToolDefinition[CommitAction, CommitObservation]):
    @classmethod
    def create(cls, conv_state=None, **params) -> Sequence["CommitTool"]:
        return [cls(name=NAME, description="Make a git commit in the repo.",
                    action_type=CommitAction, observation_type=CommitObservation,
                    executor=CommitExecutor())]


def register() -> None:
    register_tool(NAME, CommitTool)
