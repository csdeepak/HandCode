"""
Local OpenAI-compatible mock provider.

Serves scripted responses so the whole spike runs with no API key, no network,
and no tokens. Also records every request path, which is how H4 (Q13) is
answered: we simply look at which URL the SDK actually called.

Run standalone for debugging:
    python mock_provider.py --port 8999
"""
from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Every request the server has seen. Read by probe_02_endpoint.
REQUEST_LOG: list[dict] = []
_LOCK = threading.Lock()

TOOL_NAME = "side_effect_tool"


def _tool_call_response(call_id: str, model: str) -> dict:
    """Turn 1: the model asks for our side-effecting tool."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": "tool_calls",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": TOOL_NAME,
                        "arguments": json.dumps({"payload": "m0-spike"}),
                    },
                }],
            },
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
    }


def _final_response(model: str) -> dict:
    """Turn 2+: the model is satisfied and stops."""
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": "Done."},
        }],
        "usage": {"prompt_tokens": 120, "completion_tokens": 5, "total_tokens": 125},
    }


class Handler(BaseHTTPRequestHandler):
    # Stable across the whole run so H2 can compare pre- and post-crash ids.
    fixed_call_id = "call_m0_fixed_0001"

    def log_message(self, *_):        # silence stderr spam
        pass

    def _json(self, code: int, body: dict) -> None:
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self, body: dict) -> None:
        """Minimal streaming form of a non-streaming completion."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        choice = body["choices"][0]
        chunk = {
            "id": body["id"], "object": "chat.completion.chunk",
            "created": body["created"], "model": body["model"],
            "choices": [{
                "index": 0,
                "delta": choice["message"],
                "finish_reason": choice["finish_reason"],
            }],
        }
        for payload in (chunk, "[DONE]"):
            line = payload if isinstance(payload, str) else json.dumps(payload)
            self.wfile.write(f"data: {line}\n\n".encode())
            self.wfile.flush()

    def do_GET(self):                                   # noqa: N802
        with _LOCK:
            REQUEST_LOG.append({"path": self.path, "method": "GET", "ts": time.time()})
        if "models" in self.path:
            self._json(200, {"object": "list", "data": [
                {"id": "mock-model", "object": "model", "owned_by": "m0"}]})
        else:
            self._json(200, {"ok": True})

    def do_POST(self):                                  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {}

        messages = body.get("messages") or []
        with _LOCK:
            REQUEST_LOG.append({
                "path": self.path,
                "method": "POST",
                "ts": time.time(),
                "n_messages": len(messages),
                "has_tools": bool(body.get("tools")),
                "stream": bool(body.get("stream")),
                # H4 evidence: an Anthropic-format call carries a top-level
                # "system" key and no "messages[0].role == system".
                "anthropic_shaped": "system" in body and "max_tokens" in body,
            })

        model = body.get("model") or "mock-model"

        # Script: ask for the tool once, then stop. "Once" is decided by
        # whether a tool result is already present in the history.
        already_ran = any(
            (m.get("role") == "tool") or
            (isinstance(m.get("content"), list) and
             any(isinstance(c, dict) and c.get("type") == "tool_result"
                 for c in m["content"]))
            for m in messages
        )
        resp = (_final_response(model) if already_ran
                else _tool_call_response(self.fixed_call_id, model))

        if body.get("stream"):
            self._sse(resp)
        else:
            self._json(200, resp)


class MockProvider:
    """Context manager wrapping the server thread."""

    def __init__(self, port: int = 0):
        self._srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self._srv.server_address[1]
        self._thread = threading.Thread(target=self._srv.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    @property
    def requests(self) -> list[dict]:
        with _LOCK:
            return list(REQUEST_LOG)

    def clear(self) -> None:
        with _LOCK:
            REQUEST_LOG.clear()

    def __enter__(self) -> "MockProvider":
        self._thread.start()
        return self

    def __exit__(self, *_) -> None:
        self._srv.shutdown()
        self._srv.server_close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8999)
    args = ap.parse_args()
    with MockProvider(args.port) as m:
        print(f"mock provider on {m.base_url}  (ctrl-c to stop)")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print(f"\n{len(m.requests)} requests seen")
            for r in m.requests:
                print(" ", r["method"], r["path"])
