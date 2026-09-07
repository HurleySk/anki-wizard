# tests/fake_anki.py
"""A fake AnkiConnect server for tests.

Speaks enough of the protocol to exercise the client's success and failure
paths without a running Anki.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeAnki:
    def __init__(self):
        self.responses: dict[str, object] = {}
        self.errors: dict[str, str] = {}
        self.requests: list[dict] = []
        # Overridable so tests can exercise the client against a port that is
        # answering but is not AnkiConnect.
        self.status = 200
        self.raw_body: bytes | None = None
        self.delay_seconds = 0.0
        self._server: ThreadingHTTPServer | None = None
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
                if outer.delay_seconds:
                    time.sleep(outer.delay_seconds)
                if outer.raw_body is not None:
                    self.send_response(outer.status)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(outer.raw_body)))
                    self.end_headers()
                    self.wfile.write(outer.raw_body)
                    return
                action = payload.get("action")
                if action in outer.errors:
                    body = {"result": None, "error": outer.errors[action]}
                elif action in outer.responses:
                    body = {"result": outer.responses[action], "error": None}
                else:
                    # Real AnkiConnect errors on an unknown action. Mirroring
                    # that keeps a test that forgets set_response, or misspells
                    # an action, from passing on a silent None.
                    body = {
                        "result": None,
                        "error": f"unsupported action: {action!r}",
                    }
                encoded = json.dumps(body).encode()
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *args):
                pass

            def handle_one_request(self):
                # The timeout test disconnects mid-response by design, which
                # would otherwise dump a broken-pipe traceback into the run and
                # make real failures harder to spot.
                try:
                    super().handle_one_request()
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
