"""A scripted model for testing with no key: an OpenAI-compatible server on
127.0.0.1 (the demo's mock, `agentctl/demo/mock.py`, generalised).

By default it writes `hello.txt` once, then says it is done. `serve(script)`
takes a list of tool calls instead, made one per turn; `bash("...")` builds
one. The GitHub Action's self-test and `tests/test_policy_rules.py` use the
default.

    python tests/scripted_model.py 8765        # serves the default until killed
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HELLO = [("write_file", {"path": "hello.txt", "content": "hello\n"})]


def bash(command: str) -> tuple[str, dict]:
    return ("execute_bash", {"command": command})


def _completion(model: str, message: dict, finish: str) -> dict:
    return {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": finish, "message": message}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}


def _handler(script: list[tuple[str, dict]]):
    class Handler(BaseHTTPRequestHandler):
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
            # One tool call per turn: the number of tool results so far says
            # which step of the script comes next.
            done = sum(1 for m in body.get("messages") or [] if m.get("role") == "tool")
            if done >= len(script):
                self._send(_completion(model, {"role": "assistant",
                                               "content": "Done."}, "stop"))
                return
            name, args = script[done]
            self._send(_completion(model, {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"call_scripted_{done:04d}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)}}]}, "tool_calls"))
    return Handler


def serve(script: list[tuple[str, dict]] | None = None,
          port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Start in a thread. Returns the server and its base URL."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), _handler(script or HELLO))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), _handler(HELLO)).serve_forever()
