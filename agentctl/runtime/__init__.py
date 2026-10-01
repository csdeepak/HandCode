"""Runtime: real tools and a runner, for doing actual work.

`experiments/` proves the system; this uses it.

The names below load on first use. Importing them eagerly meant that any
`agentctl.runtime.*` import -- `lease`, `config`, `init` -- pulled in the tools
and with them pydantic and the OpenHands SDK. So the control plane's `proxy
down` could not even check a pid without the agent framework (`docs/0047`).
"""
__all__ = ["run", "TOOLS", "register_all"]


def __getattr__(name: str):
    if name == "run":
        from .runner import run
        return run
    if name in ("TOOLS", "register_all"):
        from . import tools
        return getattr(tools, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
