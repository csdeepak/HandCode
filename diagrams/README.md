# Diagrams

Editable diagram sources. Named by the `docs/` document they belong to.

| File | Doc | Tool |
|---|---|---|
| `0011-request-flow.drawio` | `docs/0011` | draw.io / diagrams.net |

## 0011-request-flow.drawio

Five pages, one per figure in `docs/0011`:

1. **Planes & Ownership** — the static architecture. Harness, enforcement
   kernel, data plane, providers, MCP fleet, control plane.
2. **One Full Turn** — thirteen numbered steps from user message to observation.
3. **Effect Gate Decision** — the ledger state machine and effect-class table.
4. **Crash & Resume** — the double-execution scenario and its reconciliation.
5. **Failover Hazard** — 429 failover, and the mid-turn switch that would
   defeat the effect ledger.

### Colour is semantic, not decorative

| Colour | Meaning |
|---|---|
| Rust `#B4432C` | In-band — must not fail |
| Blue `#2F5FE0` | Out-of-band control plane — may fail. Always dashed. |
| Green `#3F7A4A` | Agent harness — not ours, do not rebuild |
| Grey `#6B7689` | Data plane and third-party services |
| Green `#15803D` / Amber `#B45309` / Red `#B02A2A` | Ledger outcome: safe · ambiguous · blocked |

Keep this mapping when editing. A dashed blue edge asserts that the system
keeps working when that edge is cut — do not draw one that the request path
actually depends on.

### Opening

Open at [app.diagrams.net](https://app.diagrams.net) (File → Open From → Device),
in the VS Code *Draw.io Integration* extension, or in the desktop app. The
Mermaid source in `docs/0011` stays canonical for review; this file is for
editing and export.
