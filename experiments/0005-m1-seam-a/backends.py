"""Two independently controllable mock provider backends.

Each is a separate OpenAI-compatible server, so the LiteLLM proxy sees a pool
of two real "accounts". Either can be told to return 429, which is how failover
is provoked without touching a real provider or spending anything.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Backend:
    """One mock account. Records what it served; can be made to fail."""

    def __init__(self, name: str, port: int = 0):
        self.name = name
        self.failing = False
        self.requests: list[dict] = []
        self._lock = threading.Lock()

        backend = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def _json(self, code: int, body: dict):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):                            # noqa: N802
                self._json(200, {"object": "list", "data": [
                    {"id": "mock-model", "object": "model"}]})

            def do_POST(self):                           # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except json.JSONDecodeError:
                    body = {}
                messages = body.get("messages") or []

                with backend._lock:
                    backend.requests.append({
                        "path": self.path,
                        "n_messages": len(messages),
                        "failing": backend.failing,
                        "ts": time.time(),
                    })

                if backend.failing:
                    self._json(429, {"error": {
                        "message": f"{backend.name}: rate limit exceeded",
                        "type": "rate_limit_error", "code": "429"}})
                    return

                # Script: ask for the offered tool once, then stop.
                already = any(m.get("role") == "tool" for m in messages
                              if isinstance(m, dict))
                if already:
                    msg = {"role": "assistant",
                           "content": f"Done (served by {backend.name})."}
                    finish = "stop"
                else:
                    offered, schema = None, None
                    for t in (body.get("tools") or []):
                        fn = t.get("function") or {}
                        if fn.get("name"):
                            offered, schema = fn["name"], fn.get("parameters")
                            break
                    if not offered:
                        msg = {"role": "assistant",
                               "content": f"Hello from {backend.name}."}
                        finish = "stop"
                    else:
                        msg = {"role": "assistant", "content": None,
                               "tool_calls": [{
                                   "id": "call_m1_fixed_0001",
                                   "type": "function",
                                   "function": {"name": offered,
                                                "arguments": json.dumps(
                                                    _args_for(schema))},
                               }]}
                        finish = "tool_calls"

                self._json(200, {
                    "id": f"chatcmpl-{uuid.uuid4().hex[:10]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": body.get("model") or "mock-model",
                    "choices": [{"index": 0, "finish_reason": finish,
                                 "message": msg}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                              "total_tokens": 120},
                })

        self._srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def served(self) -> int:
        with self._lock:
            return sum(1 for r in self.requests if not r["failing"])

    @property
    def refused(self) -> int:
        with self._lock:
            return sum(1 for r in self.requests if r["failing"])

    def start(self) -> "Backend":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()


def _args_for(schema: dict | None) -> dict:
    if not isinstance(schema, dict):
        return {}
    props = schema.get("properties") or {}
    out = {}
    for name in (schema.get("required") or []):
        t = (props.get(name) or {}).get("type")
        out[name] = {"string": "mock", "integer": 1, "number": 1.0,
                     "boolean": True, "array": [], "object": {}}.get(t, "mock")
    return out
