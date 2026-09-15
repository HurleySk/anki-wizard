"""A fake Open edX LMS for tests, served over a real loopback socket.

Speaks enough of the site to exercise the capture: the sequence API, the
xblock page of each unit (the fixture markup), and the login wall. A real
server rather than Playwright route interception because a fulfilled redirect
is followed by the browser outside interception -- it goes to real DNS -- and
the login wall is a redirect. No test contacts a real course site.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

FIXTURES = Path(__file__).parent / "fixtures"
UNIT_HTML = (FIXTURES / "edx_unit.html").read_text()

COURSE = "course-v1:T+X+1"
SEQUENTIAL = "block-v1:T+X+1+type@sequential+block@ps1"
LOGIN_HTML = "<html><body><form>Sign in</form></body></html>"


def unit_id(name: str) -> str:
    return f"block-v1:T+X+1+type@vertical+block@{name}"


class FakeLms:
    """Serves the set `units`, a list of (name, title), on 127.0.0.1.

    `unit_status` maps a unit name to the HTTP status its page answers with.
    With `logged_in=False` every page redirects to a sign-in page on another
    origin, which is what the LMS does for an expired session. The real
    sequence API answers without a login; the fake walls it too so the
    tab-list path is covered, and the unit-page check is what matters.
    """

    def __init__(self, units, unit_status=None, logged_in=True):
        self.units = list(units)
        self.unit_status = dict(unit_status or {})
        self.logged_in = logged_in
        self.requests: list[str] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_port}"

    @property
    def course_url(self) -> str:
        return f"{self.url}/learn/course/{COURSE}/{SEQUENTIAL}/{unit_id('ps1-tab1')}"

    def __enter__(self) -> "FakeLms":
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                path = unquote(urlsplit(self.path).path)
                outer.requests.append(path)
                if path.startswith("/sso/"):
                    return self._reply(200, "text/html", LOGIN_HTML)
                if not outer.logged_in:
                    # The real site sends an unauthenticated browser to an SSO
                    # host: a different origin, and no "login" in the path.
                    # "localhost" reaches this same server as another origin.
                    port = outer._server.server_port
                    self.send_response(302)
                    self.send_header("Location", f"http://localhost:{port}/sso/auth?next={self.path}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                if path == f"/api/courseware/sequence/{SEQUENTIAL}":
                    items = [{"id": unit_id(n), "page_title": t} for n, t in outer.units]
                    return self._reply(200, "application/json", json.dumps({"items": items}))
                if path.startswith("/xblock/"):
                    name = path.rsplit("@", 1)[-1]
                    status = outer.unit_status.get(name, 200)
                    body = UNIT_HTML if status == 200 else "<html><body>Not found</body></html>"
                    return self._reply(status, "text/html", body)
                return self._reply(404, "text/html", "<html><body>Not found</body></html>")

            def _reply(self, status, content_type, body):
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", f"{content_type}; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
