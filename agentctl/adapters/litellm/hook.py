"""Seam A bound to the LiteLLM proxy. Logic lives in `agentctl.kernel.hook`.

Split out of the kernel because `tests/test_boundaries.py` rightly refuses to
let the kernel import a data plane (`docs/0008` R6). The kernel keeps the
decision logic; this file is the ~40 lines that know about LiteLLM.
"""
from __future__ import annotations

import logging
from pathlib import Path

from litellm.integrations.custom_logger import CustomLogger

from agentctl.kernel.hook import RequestHook

log = logging.getLogger("agentctl.hook")


class AgentctlHook(CustomLogger, RequestHook):
    """The class the proxy loads via `litellm_settings.callbacks`."""

    def __init__(self, telemetry_path: str | Path | None = None):
        CustomLogger.__init__(self)
        RequestHook.__init__(self, telemetry_path)

    async def async_pre_call_hook(self, user_api_key_dict, cache, data,
                                  call_type, **kwargs):
        try:
            return self.apply(data)
        except Exception:                               # noqa: BLE001
            # Seam A must never break a request. Losing the hook costs
            # attribution and pinning, not correctness -- the gate at Seams B
            # and C is what protects effects.
            log.exception("Seam A pre-call hook failed; passing through")
            return data

    async def async_log_success_event(self, kwargs, response_obj,
                                      start_time, end_time):
        try:
            self.record(kwargs, response_obj, _epoch(start_time), _epoch(end_time))
        except Exception:                               # noqa: BLE001
            log.exception("Seam A telemetry failed")


def _epoch(t) -> float | None:
    try:
        return t.timestamp()
    except Exception:                                   # noqa: BLE001
        return None
