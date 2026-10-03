"""The demo's scripted model: an OpenAI-compatible server on 127.0.0.1.

It does one thing: asks for the `commit` tool once, then says it is done. The
tool call id is FIXED, so a resumed run re-drives the very same action -- which
is the case under test. Adapted from `experiments/0000-falsification`'s mock,
reduced to what the demo needs.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALL_ID = "call_demo_commit_0001"


def _completion(model: str, message: dict, finish: str) -> dict:
    return {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                      "total_tokens": 110}}


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def _send(self, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):                                   # noqa: N802
        self._send({"object": "list", "data": [{"id": "demo-model",
                                                 "object": "model"}]})

    def do_POST(self):                                  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) if n else b"{}")
        except json.JSONDecodeError:
            body = {}
        model = body.get("model") or "demo-model"
        done = any(m.get("role") == "tool" for m in body.get("messages") or [])
        name = next(((t.get("function") or {}).get("name")
                     for t in body.get("tools") or [] if t.get("function")), "commit")
        if done:
            msg = {"role": "assistant", "content": "Committed. Done."}
            self._send(_completion(model, msg, "stop"))
        else:
            msg = {"role": "assistant", "content": None, "tool_calls": [{
                "id": CALL_ID, "type": "function",
                "function": {"name": name,
                             "arguments": json.dumps({"message": "fix the typo"})}}]}
            self._send(_completion(model, msg, "tool_calls"))


class MockModel:
    def __init__(self):
        self._srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._srv.server_address[1]}/v1"

    def __enter__(self) -> "MockModel":
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._srv.shutdown()
        self._srv.server_close()
