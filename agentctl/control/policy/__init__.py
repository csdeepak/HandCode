"""Policy: compiled out-of-band, read in-band. M7.

    from agentctl.control.policy import compile_policy, compile_to, PolicyError

The kernel reads the compiled artifact via `agentctl.kernel.policy.Policy` and
never imports this module -- `docs/0008` R2.
"""
from .compile import EFFECT_RULES, PolicyError, compile_policy, compile_to

__all__ = ["compile_policy", "compile_to", "PolicyError", "EFFECT_RULES"]
