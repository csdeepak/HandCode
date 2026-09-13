r"""A local OpenAI-compatible endpoint that answers from a cassette.

Point `--base-url` at it and the agent runs normally: same SDK, same tools,
same gate, same ledger — but every completion comes from disk. No API key, no
network, no tokens, no sampling.

Stdlib only, deliberately. `docs/0021` §7 is what a casual dependency costs on
this project, and a test fixture is the last place to spend that.

**On a miss the server returns 502, and that is correct.** A miss means the
agent asked something the recording never contains, which is a real
divergence. Answering it with a plausible-looking completion would produce a
run that looks like a replay and is not one -- the same shape as the failures
in `docs/0024` and `docs/0028`, where a component returned something usable
instead of admitting it could not answer.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .cassette import Cassette


class ReplayServer:
    """Serves one cassette on localhost for the life of a `with` block."""

    def __init__(self, cassette: Cassette, port: int = 0,
                 on_miss: Any = None):
        self.cassette = cassette
        self.on_miss = on_miss
        self._srv = ThreadingHTTPServer(("127.0.0.1", port),
                                        _handler_for(self))
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._srv.server_address[1]

    @property
    def base_url(self) -> str:
        """What to pass as `--base-url`. The SDK appends `/chat/completions`."""
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> "ReplayServer":
        self._thread = threading.Thread(target=self._srv.serve_forever,
                                        daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()
        if self._thread:
            self._thread.join(timeout=5)

    def __enter__(self) -> "ReplayServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def _handler_for(server: ReplayServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):                              # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            try:
                request = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": {"message": "bad json"}})

            turn = server.cassette.match(request)
            if turn is None:
                miss = server.cassette.misses[-1]
                if server.on_miss:
                    server.on_miss(miss)
                # 502, not a fabricated completion: see the module docstring.
                return self._send(502, {"error": {
                    "type": "agentctl_replay_miss",
                    "message": f"cassette miss -- {miss.describe()}",
                }})
            return self._send(200, turn.response)

        def do_GET(self):                               # noqa: N802
            """`/v1/models` and health checks, so clients that probe are happy."""
            if self.path.rstrip("/").endswith("/models"):
                models = sorted({t.model for t in server.cassette if t.model})
                return self._send(200, {"object": "list", "data": [
                    {"id": m, "object": "model"} for m in models]})
            return self._send(200, {"status": "ok",
                                    "turns": len(server.cassette)})

        def _send(self, code: int, body: dict) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args) -> None:
            """Silence. The cassette records what happened, not stderr."""

    return Handler
