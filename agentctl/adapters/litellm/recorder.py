r"""Record real completions into a cassette (M6).

A `CustomLogger` registered in-process, not through the proxy. `docs/0021`
established Seam A as the proxy's callback; `agentctl run` talks to the
provider directly and never loads it, so a direct run currently produces no
telemetry at all. Recording therefore attaches to `litellm.callbacks` itself.

The request is rebuilt from the logging callback's `kwargs`, which is the only
place both the request and its response are visible together. `docs/0021` §4
is the warning that applies here: what a callback receives is *not* laid out
the way the call site wrote it.

**Nothing here can break a completion.** A recorder that raises would turn a
diagnostic into an outage, so every path is swallowed and counted. A cassette
missing a turn is a bad cassette; a cassette that kills the run is worse.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from litellm.integrations.custom_logger import CustomLogger

from agentctl.control.replay.cassette import SIGNIFICANT_FIELDS, Cassette

log = logging.getLogger("agentctl.recorder")

# Deliberately THE fingerprint's list, not a copy of it. When these were two
# lists they drifted, and every replay missed on turn 0 (`docs/0029` §4).
_REQUEST_KEYS = SIGNIFICANT_FIELDS


class CassetteRecorder(CustomLogger):
    """Writes every successful completion to a cassette."""

    def __init__(self, path: str | Path, flush_every: int = 1,
                 configured_model: str = ""):
        super().__init__()
        self.path = Path(path)
        # litellm strips the provider prefix before a callback sees `model`,
        # so the routable name has to come from the caller (`docs/0029` §3).
        self.configured_model = configured_model
        self.cassette = Cassette()
        self.flush_every = max(1, flush_every)
        self.errors = 0
        # A detached recorder must be inert even if litellm still holds it.
        # See `detach` -- removing it from the callback lists is not something
        # this package can guarantee, but refusing to write is.
        self.closed = False

    # litellm calls one or the other depending on the call path, so both are
    # implemented and both land in the same place.
    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._capture(kwargs, response_obj)

    async def async_log_success_event(self, kwargs, response_obj,
                                      start_time, end_time):
        self._capture(kwargs, response_obj)

    # ── internals ──────────────────────────────────────────────────────
    def _capture(self, kwargs: dict, response_obj: Any) -> None:
        if self.closed:
            return
        try:
            request = _request_from(kwargs)
            response = _as_dict(response_obj)
            if not request.get("messages") or not response:
                # Nothing worth recording, and nothing worth failing over.
                return
            turn = self.cassette.append(
                request, response,
                model=str(kwargs.get("model") or request.get("model") or ""),
                provider_model=self.configured_model,
                usage=_as_dict(_get(response_obj, "usage")) or {})
            if turn.index % self.flush_every == 0:
                self.flush()
        except Exception:                               # noqa: BLE001
            self.errors += 1
            log.exception("recorder failed on one turn; continuing")

    def flush(self) -> None:
        try:
            self.cassette.save(self.path)
        except Exception:                               # noqa: BLE001
            self.errors += 1
            log.exception("could not write the cassette")


def _request_from(kwargs: dict) -> dict:
    """Rebuild the outgoing request from what the callback was handed.

    `kwargs` carries the call's arguments at the top level for a direct
    completion, and under `additional_args`/`optional_params` for some proxy
    paths. Both are checked, nearest-first.
    """
    optional = kwargs.get("optional_params") or {}
    out: dict = {}
    for key in _REQUEST_KEYS:
        value = kwargs.get(key)
        if value is None:
            value = optional.get(key)
        if value is not None:
            out[key] = _as_plain(value)
    return out


def _as_dict(obj: Any) -> dict:
    """Pydantic model, dict, or something with __dict__ -> a plain dict."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    for attr in ("model_dump", "dict", "json"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                got = fn()
                if isinstance(got, dict):
                    return got
                if isinstance(got, str):
                    import json
                    return json.loads(got)
            except Exception:                           # noqa: BLE001
                continue
    return dict(getattr(obj, "__dict__", {}) or {})


def _as_plain(value: Any) -> Any:
    """Recursively strip pydantic models so the cassette is plain JSON."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {k: _as_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_plain(v) for v in value]
    d = _as_dict(value)
    return {k: _as_plain(v) for k, v in d.items()} if d else str(value)


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


# litellm copies whatever is in `callbacks` into its own per-kind lists the
# first time it initialises logging. Removing from `callbacks` alone leaves the
# recorder live in `success_callback`, still writing (`docs/0029` §5).
_CALLBACK_LISTS = (
    "callbacks", "success_callback", "_async_success_callback",
    "input_callback", "_async_input_callback",
    "failure_callback", "_async_failure_callback",
    "service_callback", "audit_log_callbacks",
)


def attach(path: str | Path, configured_model: str = "") -> CassetteRecorder:
    """Register a recorder on litellm's in-process callback list."""
    import litellm

    rec = CassetteRecorder(path, configured_model=configured_model)
    if not any(c is rec for c in litellm.callbacks):
        litellm.callbacks.append(rec)
    return rec


def detach(rec: CassetteRecorder) -> None:
    """Stop recording, and mean it.

    Two mechanisms, because the first one alone is not sufficient and cannot be
    made sufficient: litellm decides where to copy a callback, and a version
    that adds a tenth list would silently resurrect the recorder. Closing the
    recorder is what actually guarantees it stops, whoever still holds it.

    The bug this fixes: a replay run re-recorded itself into the cassette it
    was replaying, doubling the file (`docs/0029` §5).
    """
    import litellm

    rec.flush()
    rec.closed = True

    for name in _CALLBACK_LISTS:
        lst = getattr(litellm, name, None)
        if isinstance(lst, list):
            lst[:] = [c for c in lst if c is not rec]
