"""A minimal real toolset: bash, read, write.

Deliberately not `openhands-tools`. That package pulls ~55 dependencies
(browser-use, google APIs, three model SDKs) and downgrades `mcp` below what
the SDK needs — the hazard in `docs/0021` §7. These three tools need nothing
new, and they are exactly the names `control/matrix/data/tools.yaml` already
classifies, so the gate is meaningful the moment they run.

    execute_bash   EXTERNAL by default, reclassified per-command by the matrix
                   (`ls` -> PURE_READ, `git commit` -> NON_IDEMPOTENT_WRITE,
                   `rm -rf` -> DESTRUCTIVE)
    read_file      PURE_READ
    write_file     IDEMPOTENT_WRITE

**The gate prevents duplicates, not danger.** A first-time `rm -rf` is not a
replay, so the ledger admits it. Authorization is a separate concern — see
`confirm_destructive` in `runner.py`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
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

WORKSPACE_ENV = "AGENTCTL_WORKSPACE"
TIMEOUT_ENV = "AGENTCTL_BASH_TIMEOUT"
MAX_OUTPUT = 30_000


def _workspace() -> Path:
    """Where work happens. Configuration, never model input (`docs/0023` §3)."""
    return Path(os.environ.get(WORKSPACE_ENV, ".")).resolve()


def _text(s: str):
    """Wrap a string as the SDK's content blocks.

    The model sees `Observation.content` via `to_llm_content`. An observation
    that stores its text anywhere else renders as "[no text content]" and the
    agent concludes the tool returned nothing (`docs/0025`).
    """
    from openhands.sdk.llm import TextContent
    return [TextContent(text=s)]


def _clip(s: str) -> str:
    return s if len(s) <= MAX_OUTPUT else s[:MAX_OUTPUT] + "\n<TRUNCATED>"


# ── execute_bash ───────────────────────────────────────────────────────
class BashAction(Action):
    command: str = Field(description="The shell command to run.")


class BashObservation(Observation):
    exit_code: int = Field(default=0)
    output: str = Field(default="")

    @classmethod
    def make(cls, exit_code: int, output: str) -> "BashObservation":
        return cls(exit_code=exit_code, output=output,
                   content=_text(f"exit={exit_code}\n{output}"),
                   is_error=exit_code != 0)


def _shell() -> list[str] | None:
    r"""The argv prefix for running a bash command, or None if bash is absent.

    `shell=True` uses `COMSPEC` on Windows — **cmd.exe** — and this tool is
    called `execute_bash`. The gap is not cosmetic:

    * the model writes bash, and cmd.exe rejects it. A real run produced
      `<< was unexpected at this time.` five times from heredocs, wrote
      nothing, and still reported success (`docs/0031` §9).
    * the capability matrix splits commands on `&&`, `||`, `;`, `|` and matches
      `rm -rf`, `git reset --hard`, `>` redirects. Those are **bash** rules.
      Under cmd.exe the classifier would be guarding a shell nobody is running,
      and `del /s /q` — the thing that actually deletes — matches nothing.

    So bash is used explicitly when present. Git for Windows ships one, so this
    is usually satisfied even on Windows.
    """
    exe = shutil.which("bash") or shutil.which("sh")
    return [exe, "-c"] if exe else None


class BashExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        argv = _shell()
        try:
            r = subprocess.run(
                (argv + [action.command]) if argv else action.command,
                shell=argv is None, cwd=str(_workspace()),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace",
                timeout=float(os.environ.get(TIMEOUT_ENV, "120")))
            out = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
            return BashObservation.make(r.returncode, _clip(out.strip()))
        except subprocess.TimeoutExpired:
            return BashObservation.make(124, "timed out")
        except Exception as e:                          # noqa: BLE001
            return BashObservation.make(1, f"{type(e).__name__}: {e}")


class BashTool(ToolDefinition[BashAction, BashObservation]):
    @classmethod
    def create(cls, conv_state=None, **params) -> Sequence["BashTool"]:
        return [cls(name="execute_bash",
                    description="Run a shell command in the workspace and "
                                "return its exit code and output.",
                    action_type=BashAction, observation_type=BashObservation,
                    executor=BashExecutor())]


# ── read_file ──────────────────────────────────────────────────────────
class ReadAction(Action):
    path: str = Field(description="File to read, relative to the workspace.")


class ReadObservation(Observation):
    # NOT `content`: Observation.content is list[TextContent | ImageContent],
    # and shadowing it with a str validates here then explodes when the message
    # is assembled -- the same trap as docs/0018 §4 C1. `content` is reserved.
    file_text: str = Field(default="")

    @classmethod
    def make(cls, text: str, is_error: bool = False) -> "ReadObservation":
        return cls(file_text=text, content=_text(text), is_error=is_error)


class ReadExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        p = _workspace() / action.path
        try:
            return ReadObservation.make(
                _clip(p.read_text(encoding="utf-8", errors="replace")))
        except Exception as e:                          # noqa: BLE001
            return ReadObservation.make(f"error: {type(e).__name__}: {e}",
                                        is_error=True)


class ReadFileTool(ToolDefinition[ReadAction, ReadObservation]):
    @classmethod
    def create(cls, conv_state=None, **params) -> Sequence["ReadFileTool"]:
        return [cls(name="read_file", description="Read a file's contents.",
                    action_type=ReadAction, observation_type=ReadObservation,
                    executor=ReadExecutor())]


# ── write_file ─────────────────────────────────────────────────────────
class WriteAction(Action):
    path: str = Field(description="File to write, relative to the workspace.")
    content: str = Field(description="Full new contents of the file.")


class WriteObservation(Observation):
    status: str = Field(default="ok")
    bytes_written: int = Field(default=0)

    @classmethod
    def make(cls, status: str, n: int = 0) -> "WriteObservation":
        return cls(status=status, bytes_written=n,
                   content=_text(f"{status} ({n} bytes)"),
                   is_error=status.startswith("error"))


def _existing_newline(path: Path) -> str | None:
    r"""The line ending a file already uses, or None if it is new.

    A model sends content with `\n`. Writing that over a CRLF file rewrites
    every line, so an eight-line change arrives as a 149-line diff: unreviewable,
    and it pollutes the history of any repository checked out on Windows. That
    happened on the first real edit this tool made to its own repo
    (`docs/0035`).

    The dominant ending wins rather than the first one found, because a file
    with a couple of stray endings should not flip the whole file to match its
    own typo.
    """
    try:
        raw = path.read_bytes()
    except Exception:                                   # noqa: BLE001
        return None
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    if crlf == 0 and lf == 0:
        return None
    return "\r\n" if crlf > lf else "\n"


class WriteExecutor(ToolExecutor):
    """Writes the WHOLE file, which is what makes it IDEMPOTENT_WRITE.

    An append would be non-idempotent and would need a probe; replacing the
    entire contents can be repeated safely, so a crash mid-write costs nothing.

    The file's existing line endings are preserved, so editing one rule in a
    CRLF file produces a one-rule diff.
    """

    def __call__(self, action, conversation=None):
        p = _workspace() / action.path
        try:
            existing = _existing_newline(p) if p.exists() else None
            p.parent.mkdir(parents=True, exist_ok=True)
            # Normalise to `\n` FIRST, always. The model may send either, so
            # replacing `\n` without stripping `\r` turns `\r\n` into `\r\r\n`
            # -- and only converting toward CRLF leaves an LF file holding the
            # CRLF the model happened to send.
            text = action.content.replace("\r\n", "\n")
            if existing == "\r\n":
                text = text.replace("\n", "\r\n")
            data = text.encode("utf-8")
            p.write_bytes(data)
            return WriteObservation.make("written", len(data))
        except Exception as e:                          # noqa: BLE001
            return WriteObservation.make(f"error: {type(e).__name__}: {e}")


class WriteFileTool(ToolDefinition[WriteAction, WriteObservation]):
    @classmethod
    def create(cls, conv_state=None, **params) -> Sequence["WriteFileTool"]:
        return [cls(name="write_file",
                    description="Replace a file's entire contents.",
                    action_type=WriteAction, observation_type=WriteObservation,
                    executor=WriteExecutor())]


TOOLS: dict[str, type] = {
    "execute_bash": BashTool,
    "read_file": ReadFileTool,
    "write_file": WriteFileTool,
}


def register_all() -> list[str]:
    for name, cls in TOOLS.items():
        register_tool(name, cls)
    return list(TOOLS)
