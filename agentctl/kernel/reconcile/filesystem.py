"""Filesystem reconciliation probe.

Covers the second common non-idempotent effect: appending to a file.

Method:

    capture()   the file's size and content hash, plus the bytes to be appended
    probe()     unchanged                    -> DID_NOT_LAND
                prefix intact + our bytes    -> LANDED  (proof, not inference)
                anything else                -> INCONCLUSIVE

The middle case is the good one. Because the tool's arguments carry the content
being appended, we can verify *our* bytes are present rather than merely
noticing the file changed. That is stronger than the git probe, which can only
infer from "HEAD moved".
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import DID_NOT_LAND, INCONCLUSIVE, LANDED

_PATH_KEYS = ("path", "file_path", "filename", "file", "target")
_CONTENT_KEYS = ("content", "text", "data", "payload", "new_str", "append")
_MAX_BYTES = 32 * 1024 * 1024        # do not hash a huge file on the hot path


class FileAppendProbe:
    name = "filesystem"

    def __init__(self, max_bytes: int = _MAX_BYTES):
        self.max_bytes = max_bytes

    # ── selection ──────────────────────────────────────────────────────
    def handles(self, call) -> bool:
        return self._path(call) is not None

    # ── before ─────────────────────────────────────────────────────────
    def capture(self, call) -> dict | None:
        try:
            path = self._path(call)
            if path is None:
                return None
            pre = self._fingerprint(path)
            if pre is None:
                return None

            out = {"probe": self.name, "path": str(path), **pre}

            # If we can see what will be appended, record it so the probe can
            # verify prefix + suffix rather than guessing.
            content = self._content(call)
            if content is not None:
                out["appended"] = content.decode("utf-8", "replace")
            return out
        except Exception:                               # noqa: BLE001
            return None

    # ── after a crash ──────────────────────────────────────────────────
    def probe(self, call, record) -> str:
        try:
            pre = _pre(record)
            if not pre or pre.get("probe") != self.name:
                return INCONCLUSIVE

            path = Path(pre["path"])
            now = self._fingerprint(path)
            if now is None:
                return INCONCLUSIVE

            if now["sha256"] == pre.get("sha256") and now["size"] == pre.get("size"):
                return DID_NOT_LAND

            appended = pre.get("appended")
            if appended is not None:
                return self._verify_append(path, pre, appended)

            # Changed, and we could not predict the post-state. Under the
            # single-writer assumption this was our effect, but it is inference.
            return LANDED
        except Exception:                               # noqa: BLE001
            return INCONCLUSIVE

    # ── internals ──────────────────────────────────────────────────────
    @staticmethod
    def _path(call) -> Path | None:
        for k in _PATH_KEYS:
            if (v := call.args.get(k)):
                try:
                    p = Path(str(v))
                except Exception:                       # noqa: BLE001
                    continue
                if p.parent.exists():
                    return p
        return None

    @staticmethod
    def _content(call) -> bytes | None:
        for k in _CONTENT_KEYS:
            v = call.args.get(k)
            if isinstance(v, (str, bytes)):
                return v.encode() if isinstance(v, str) else v
        return None

    def _verify_append(self, path: Path, pre: dict, appended: str) -> str:
        """Prefix intact + our content at the tail means it landed.

        Deliberately not a whole-file hash. Text-mode writers translate LF to
        CRLF on Windows, so a predicted hash of the exact bytes almost never
        matches and every append would fail closed. Comparing the unchanged
        prefix against a newline-normalised tail is both more robust and a
        stronger claim: it verifies *our* bytes are there, not merely that the
        file changed.
        """
        pre_size = int(pre.get("size") or 0)
        try:
            data = path.read_bytes()
        except OSError:
            return INCONCLUSIVE

        if len(data) < pre_size:
            return INCONCLUSIVE                     # truncated: not our doing
        if _sha(data[:pre_size]) != pre.get("sha256"):
            return INCONCLUSIVE                     # prefix rewritten

        tail = _norm(data[pre_size:])
        ours = _norm(appended.encode())
        if tail == ours or ours in tail:
            return LANDED
        return INCONCLUSIVE                         # someone else wrote

    def _fingerprint(self, path: Path) -> dict | None:
        try:
            if not path.exists():
                return {"exists": False, "size": 0, "sha256": _sha(b"")}
            size = path.stat().st_size
            if size > self.max_bytes:
                return {"exists": True, "size": size, "sha256": None}
            return {"exists": True, "size": size, "sha256": _sha(path.read_bytes())}
        except OSError:
            return None


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _norm(b: bytes) -> bytes:
    """Normalise line endings so CRLF and LF compare equal."""
    return b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _pre(record) -> dict | None:
    raw = getattr(record, "pre_state", None)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:                                   # noqa: BLE001
        return None
