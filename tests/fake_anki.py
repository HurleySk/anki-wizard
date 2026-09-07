# tests/fake_anki.py
"""A fake AnkiConnect server for tests.

Speaks enough of the protocol to exercise the client's success and failure
paths without a running Anki.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class FakeAnki:
    def __init__(self):
        self.responses: dict[str, object] = {}
        self.errors: dict[str, str] = {}
        self.requests: list[dict] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def set_response(self, action: str, result) -> None:
        self.responses[action] = result

    def set_error(self, action: str, message: str) -> None:
        self.errors[action] = message

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}"

    def __enter__(self) -> "FakeAnki":
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                outer.requests.append(payload)
                action = payload.get("action")
                if action in outer.errors:
                    body = {"result": None, "error": outer.errors[action]}
                else:
                    body = {"result": outer.responses.get(action), "error": None}
                encoded = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
