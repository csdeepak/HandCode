"""One run of the demo, in its own process, so it can be killed for real.

    python -m agentctl.demo.child --arm bare|guarded --mode fresh|resume \\
        --ws DIR --base-url URL

`bare` is plain OpenHands. `guarded` adds agentctl through `protect()`, the
same public embed API the README documents -- not a demo-only path.
"""
from __future__ import annotations

import argparse
import os
import uuid
from pathlib import Path

from agentctl.demo import MARKER, SLEEP_S

#: The demo tool is a commit: not safe to repeat, and git can be asked whether
#: it landed.
MATRIX = {"version": 1, "defaults": {"unknown_tool": "EXTERNAL"},
          "tools": {"commit": {"class": "NON_IDEMPOTENT_WRITE", "probe": "git"}}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("bare", "guarded"), required=True)
    ap.add_argument("--mode", choices=("fresh", "resume"), required=True)
    ap.add_argument("--ws", type=Path, required=True)
    ap.add_argument("--base-url", required=True)
    a = ap.parse_args()

    from agentctl.demo import tool
    from agentctl.runtime.runner import _build_agent
    from openhands.sdk import LLM, Conversation

    ws, repo = a.ws, a.ws / "repo"
    os.environ[tool.REPO_ENV] = str(repo)
    os.environ[tool.MARKER_ENV] = str(ws / MARKER)
    os.environ[tool.SLEEP_ENV] = str(SLEEP_S)

    cid_file = ws / "conversation_id.txt"
    if a.mode == "fresh":
        cid = uuid.uuid4()
        cid_file.write_text(str(cid), encoding="utf-8")
    else:
        cid = uuid.UUID(cid_file.read_text(encoding="utf-8").strip())

    callbacks, guard = [], None
    if a.arm == "guarded":
        from agentctl.adapters.openhands import protect
        from agentctl.runtime.lease import claim

        ledger = ws / "ledger.db"
        # The crashed holder is dead, so the resume may take its lease without
        # being told to (`docs/0046`).
        steal = claim(ledger, str(cid)).takeover if a.mode == "resume" else False
        guard = protect(ledger=ledger, conversation_id=str(cid),
                        tools={tool.NAME: tool.CommitTool}, matrix=MATRIX,
                        repo_root=repo, takeover=steal)
        callbacks = [guard.seam_b]
    else:
        tool.register()

    llm = LLM(model="openai/demo-model", api_key="not-needed", base_url=a.base_url,
              service_id="agentctl-demo", temperature=0.0, num_retries=1)
    # Through the one place allowed to build an Agent, which pins
    # tool_concurrency_limit to 1 (`docs/0038` §4.3) -- the demo too.
    agent = _build_agent(llm, [tool.NAME])
    conv = Conversation(agent=agent, workspace=str(repo),
                        persistence_dir=str(ws / "state"), conversation_id=cid,
                        delete_on_close=False, stuck_detection=False,
                        visualizer=None, callbacks=callbacks)
    if guard is not None:
        guard.attach(conv)
    if a.mode == "fresh":
        conv.send_message("Commit the fix with the message 'fix the typo'.")
    conv.run()
    if guard is not None:
        guard.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
