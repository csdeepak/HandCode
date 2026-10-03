"""Every run, in one place, so no follow-up command needs a path. `docs/0042` I-17.

Phase 0 (`docs/0044` F4): runs wrote `<workspace>/.agentctl/ledger.db`, and
`status`, `blocked`, `resolve` and `dash` read `./ledger.db` -- "no ledger at
ledger.db" from inside the very workspace that had one. Resume meant copying a
UUID out of scrollback (F5).

`~/.agentctl/runs.db` has one row per run ATTEMPT (a resume is another row of
the same conversation):

    started    written before the agent's first step
    ended      written when the run returns, however it returns

A row still `running` whose process is gone is a run that DIED -- a crash, a
killed terminal, a closed laptop -- and is shown as such. That is the point of
writing the start first: absence of an end is evidence.

Local only. It holds task text and paths, so it lives under `~/.agentctl`,
outside every repository.
"""
from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS run (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id  TEXT NOT NULL,
    workspace        TEXT NOT NULL,
    ledger           TEXT NOT NULL,
    model            TEXT,
    base_url         TEXT,
    task             TEXT,
    pid              INTEGER,
    started          REAL NOT NULL,
    ended            REAL,
    -- running | done | needs_you | failed | interrupted | rate_limited | error
    status           TEXT NOT NULL,
    outcome          TEXT,
    requests         INTEGER,
    detail           TEXT
);
CREATE INDEX IF NOT EXISTS ix_run_ws ON run(workspace, started);
CREATE INDEX IF NOT EXISTS ix_run_conv ON run(conversation_id);
"""


def path() -> Path:
    base = os.environ.get("AGENTCTL_HOME") or str(Path.home() / ".agentctl")
    return Path(base) / "runs.db"


@contextmanager
def _db():
    """A connection that is CLOSED afterwards. `with sqlite3.connect()` only
    commits, and on Windows an open handle keeps the file locked."""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(p), isolation_level=None, timeout=10)
    try:
        db.row_factory = sqlite3.Row
        db.executescript(SCHEMA)
        yield db
    finally:
        db.close()


@dataclass(frozen=True)
class Run:
    id: int
    conversation_id: str
    workspace: str
    ledger: str
    model: str | None
    base_url: str | None
    task: str | None
    pid: int | None
    started: float
    ended: float | None
    status: str
    outcome: str | None
    requests: int | None
    detail: str | None

    @property
    def state(self) -> str:
        """`status`, except that a `running` row whose process is gone DIED."""
        if self.status == "running" and self.pid:
            from agentctl.runtime.lease import pid_alive
            if not pid_alive(self.pid):
                return "died"
        return self.status


def _row(r: sqlite3.Row) -> Run:
    return Run(**{k: r[k] for k in r.keys()})


def start(conversation_id: str, workspace: str | Path, ledger: str | Path,
          model: str | None, base_url: str | None, task: str | None) -> int | None:
    """Record a run beginning. Never raises: the index is a convenience, and a
    run must not fail because the convenience could not be written."""
    try:
        with _db() as db:
            cur = db.execute(
                "INSERT INTO run(conversation_id, workspace, ledger, model, "
                "base_url, task, pid, started, status) VALUES(?,?,?,?,?,?,?,?,?)",
                (conversation_id, str(Path(workspace).resolve()), str(ledger),
                 model, base_url, (task or "")[:300] or None, os.getpid(),
                 time.time(), "running"))
            return cur.lastrowid
    except Exception:                                   # noqa: BLE001
        return None


def end(run_id: int | None, status: str, outcome: str | None = None,
        requests: int | None = None, detail: str | None = None) -> None:
    if run_id is None:
        return
    try:
        with _db() as db:
            db.execute("UPDATE run SET ended=?, status=?, outcome=?, requests=?, "
                       "detail=? WHERE id=?",
                       (time.time(), status, outcome, requests,
                        (detail or "")[:500] or None, run_id))
    except Exception:                                   # noqa: BLE001
        pass


def recent(limit: int = 20, workspace: str | Path | None = None) -> list[Run]:
    if not path().exists():
        return []
    with _db() as db:
        if workspace is not None:
            rows = db.execute("SELECT * FROM run WHERE workspace=? ORDER BY "
                              "started DESC LIMIT ?",
                              (str(Path(workspace).resolve()), limit)).fetchall()
        else:
            rows = db.execute("SELECT * FROM run ORDER BY started DESC LIMIT ?",
                              (limit,)).fetchall()
    return [_row(r) for r in rows]


def find(given: str | None = None, workspace: str | Path | None = None) -> Run:
    """The run `agentctl resume` means.

    No argument: the latest run in this workspace, or else the latest
    anywhere. Otherwise a conversation id or an unambiguous prefix of one.
    Raises SystemExit with the reason, never guesses.
    """
    if not path().exists():
        raise SystemExit("no runs recorded yet. Start one:  agentctl run \"<task>\"")
    with _db() as db:
        if given:
            rows = db.execute("SELECT * FROM run WHERE replace(conversation_id,'-','') "
                              "LIKE ? ORDER BY started DESC",
                              (given.replace("-", "") + "%",)).fetchall()
            convs = {r["conversation_id"] for r in rows}
            if not rows:
                raise SystemExit(f"no run with an id starting {given!r}. "
                                 f"`agentctl status` lists them.")
            if len(convs) > 1:
                raise SystemExit(f"{given!r} matches {len(convs)} conversations: "
                                 + ", ".join(sorted(c[:13] for c in convs))
                                 + ". Give more characters.")
            return _row(rows[0])
        if workspace is not None:
            r = db.execute("SELECT * FROM run WHERE workspace=? ORDER BY started "
                           "DESC LIMIT 1", (str(Path(workspace).resolve()),)).fetchone()
            if r is not None:
                return _row(r)
        r = db.execute("SELECT * FROM run ORDER BY started DESC LIMIT 1").fetchone()
        if r is None:
            raise SystemExit("no runs recorded yet.")
        return _row(r)


def ledgers() -> list[Path]:
    """Every ledger a recorded run wrote, newest first, that still exists."""
    if not path().exists():
        return []
    with _db() as db:
        rows = db.execute("SELECT ledger, MAX(started) s FROM run GROUP BY ledger "
                          "ORDER BY s DESC").fetchall()
    return [Path(r["ledger"]) for r in rows if Path(r["ledger"]).exists()]
