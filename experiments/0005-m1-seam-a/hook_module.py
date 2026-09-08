"""The callback module LiteLLM's proxy loads.

`litellm_settings.callbacks: hook_module.proxy_handler_instance` resolves to
the object below, so the proxy needs this importable on PYTHONPATH.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agentctl.adapters.litellm import AgentctlHook  # noqa: E402

TELEMETRY = os.environ.get("AGENTCTL_TELEMETRY", "hook_telemetry.json")

#: LiteLLM looks this name up by string.
proxy_handler_instance = AgentctlHook(telemetry_path=TELEMETRY)
