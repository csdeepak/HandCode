"""LiteLLM adapter — the Seam A binding (`docs/0008` §3).

Harness-independent by nature: anything speaking the OpenAI-compatible format
passes through here (`docs/0013` §5). It lives in `adapters/` rather than the
kernel because the kernel may not import a data plane.
"""
from .hook import AgentctlHook

__all__ = ["AgentctlHook"]
