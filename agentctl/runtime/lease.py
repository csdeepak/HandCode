"""Who holds a conversation's lease, and whether they are still alive.

`docs/0042` I-02. `--resume` used to pass `takeover=True` unconditionally, so a
second terminal could steal the lease from a run that was still working, and
two processes drove one conversation: one event history, two writers.

The fix keeps "crash, then resume" frictionless and refuses the dangerous
case. Holders are named `run@<host>:<pid>`, so a resume can ask whether the
holder is alive:

    holder dead (same host)      take over -- a crashed process cannot
                                 release its own lease, and waiting out the
                                 TTL helps nobody
    holder alive, or unknowable  refuse and name it; `--takeover` overrides
    lease expired or released    nothing to steal

"Unknowable" counts as alive: a holder on another host, or a name not in this
format. Taking over from a live process is the failure; waiting is only slow.
"""
from __future__ import annotations

import os
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PREFIX = "run@"


def holder_id(pid: int | None = None) -> str:
    """This process's lease holder name."""
    return f"{PREFIX}{socket.gethostname()}:{pid or os.getpid()}"


def _parse(holder: str) -> tuple[str, int] | None:
    if not holder.startswith(PREFIX) or ":" not in holder:
        return None
    host, _, pid = holder[len(PREFIX):].rpartition(":")
    try:
        return host, int(pid)
    except ValueError:
        return None


def pid_alive(pid: int) -> bool:
    """Is a process with this pid running on this machine?

    Never `os.kill(pid, 0)` on Windows: there, `os.kill` with any signal other
    than the two console events calls TerminateProcess. A liveness check that
    kills what it checks would be a remarkable way to fail.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE,
                                           ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
        handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # ERROR_ACCESS_DENIED means it exists and is someone else's.
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            if not k32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True                     # cannot tell: assume alive
            return code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                             # exists, not ours
    return True


def holder_alive(holder: str) -> bool | None:
    """True / False when this machine can tell; None when it cannot."""
    parsed = _parse(holder)
    if parsed is None:
        return None
    host, pid = parsed
    if host != socket.gethostname():
        return None
    return pid_alive(pid)


@dataclass(frozen=True)
class Claim:
    """What a resume should do about the lease."""
    takeover: bool
    note: str = ""


class StillRunning(SystemExit):
    """The conversation's holder is alive. Refuse, and say who and how."""


def claim(ledger: str | Path, conversation_id: str, *,
          force: bool = False) -> Claim:
    """Decide whether resuming `conversation_id` may take its lease.

    Reads the lease and nothing else; `protect()` then acquires with the
    answer. Between the two, another process could still take it -- in which
    case `acquire` raises `LeaseHeld`, which is the same refusal.
    """
    from agentctl.kernel.ledger.store import LedgerStore

    p = Path(ledger)
    if not p.exists():
        return Claim(False)
    with LedgerStore(p, holder="claim") as s:
        row = s.lease(conversation_id)
    if row is None or row["expires_at"] <= time.time():
        return Claim(False)

    holder, left = row["holder"], row["expires_at"] - time.time()
    alive = holder_alive(holder)
    if alive is False:
        return Claim(True, f"the run that held it ({holder}) is gone; "
                           f"taking over")
    if force:
        return Claim(True, f"--takeover: stealing the lease from {holder}, "
                           f"which {'is ALIVE' if alive else 'may be alive'}. "
                           f"Its next write will be refused.")
    raise StillRunning(
        f"conversation {conversation_id} is being driven by {holder}"
        f"{'' if alive else ' (cannot tell from here whether it is alive)'}; "
        f"its lease has {left:.0f}s left and renews while it runs.\n"
        f"  Two processes driving one conversation is the thing the ledger's\n"
        f"  single-writer guarantee forbids (docs/0042 I-02).\n"
        f"  If that run is still working: let it finish, or stop it first.\n"
        f"  If it is gone:  add --takeover")
