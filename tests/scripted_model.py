"""A scripted model for testing the GitHub Action with no key: an
OpenAI-compatible server on 127.0.0.1 (the demo's mock, `agentctl/demo/mock.py`,
asked for `write_file` instead of `commit`).

It writes `hello.txt` once, then says it is done.

    python tests/scripted_model.py 8765        # serves until killed
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _completion(model: str, message: dict, finish: str) -> dict:
    return {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}


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
        self._send({"object": "list", "data": [{"id": "scripted", "object": "model"}]})

    def do_POST(self):                                  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) if n else b"{}")
        except json.JSONDecodeError:
            body = {}
        model = body.get("model") or "scripted"
        if any(m.get("role") == "tool" for m in body.get("messages") or []):
            self._send(_completion(model, {"role": "assistant",
                                           "content": "Wrote hello.txt. Done."}, "stop"))
            return
        self._send(_completion(model, {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_scripted_write_0001", "type": "function",
            "function": {"name": "write_file", "arguments": json.dumps(
                {"path": "hello.txt", "content": "hello\n"})}}]}, "tool_calls"))


def serve(port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Start in a thread. Returns the server and its base URL."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), _Handler).serve_forever()
