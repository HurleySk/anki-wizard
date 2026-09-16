"""The pad server, and the process that runs it.

Serves one directory over loopback and stops itself once nothing has fetched
for a while -- a crashed parent must not leak a server that runs forever.

Run as `python -m anki_wizard.pad_server <root>`: that is what viewer.py spawns
detached, so the URL outlives the process that rendered the pad. It writes a
pidfile the starting process polls for, then serves until left idle.
"""

import argparse
import functools
import http.server
import json
import os
import re
import signal
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from anki_wizard.paths import Paths

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8899
DEFAULT_IDLE_TIMEOUT_MINUTES = 30.0

# How often the watchdog checks, and so the worst-case overshoot past the idle
# timeout.
WATCHDOG_INTERVAL_SECONDS = 30.0

# How long the serving loop waits for a connection before rechecking whether it
# has been asked to stop.
STOP_POLL_SECONDS = 0.5

# Answers "is this my server, or something else on the port?". A pidfile alone
# cannot tell a live pad server from a recycled pid.
HEALTH_PATH = "/.anki-wizard-pad"

# The two routes built on request. A slug is one path segment; a dot segment
# is refused by _is_slug before any path is built from it.
_PROBLEMS = re.compile(r"/problems/(?P<slug>[A-Za-z0-9._-]+)")
_PAGE_IMAGE = re.compile(
    r"/sources/(?P<slug>[A-Za-z0-9._-]+)/pages/page-(?P<page>\d{3})\.png"
)


def _is_slug(segment: str) -> bool:
    return segment not in (".", "..")


def _pages():
    """The page builders, imported on request rather than at module load.

    home.py reads the sheet store, which imports viewer.py, which imports
    this module for the pidfile contract. Importing home here breaks that
    cycle without moving anything.
    """
    from anki_wizard import home

    return home


class _Handler(http.server.SimpleHTTPRequestHandler):
    server_version = "anki-wizard-pad"

    def do_GET(self):
        if self.path == HEALTH_PATH:
            # Deliberately not a touch: liveness checks are the harness talking
            # to itself, and counting them as use would keep an unread pad
            # alive forever.
            body = json.dumps({"root": str(self.server.root)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.server.touch()

        path = urllib.parse.urlsplit(self.path).path
        paths = self.server.paths
        if path in ("/", "/index.html"):
            self._send_html(_pages().home_page(paths))
            return
        if match := _PROBLEMS.fullmatch(path):
            if not _is_slug(match["slug"]):
                self.send_error(404, "no such problem set")
                return
            try:
                html = _pages().problems_page(match["slug"], paths)
            except KeyError:
                self.send_error(404, "no such problem set")
                return
            self._send_html(html)
            return
        if match := _PAGE_IMAGE.fullmatch(path):
            if not _is_slug(match["slug"]):
                self.send_error(404, "no such page image")
                return
            image = paths.served_page_image(match["slug"], int(match["page"]))
            if image is None:
                self.send_error(404, "no such page image")
                return
            self._send_png(image)
            return
        super().do_GET()

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        # Built fresh on every request; a tab must reload to the current
        # state rather than to what it saw last.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_png(self, path: Path) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404, "no such page image")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """Silence per-request logging; it would interleave with the agent."""


class PadServer(http.server.ThreadingHTTPServer):
    """A loopback server rooted at one directory, which stops when left idle."""

    daemon_threads = True

    def __init__(
        self,
        root: Path,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        idle_timeout: float | None = None,
    ):
        self.root = root.resolve()
        # The served directory is the pad; the pages built on request read
        # the state root above it, which paths.py fixes as the pad's parent.
        self.paths = Paths(root=self.root.parent)
        self.idle_timeout = idle_timeout
        self._last_request = time.monotonic()
        self._stopping = threading.Event()
        super().__init__(
            (host, port), functools.partial(_Handler, directory=str(self.root))
        )
        self.host, self.port = self.server_address[:2]

    def touch(self) -> None:
        self._last_request = time.monotonic()

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self._last_request

    def url_for(self, path: Path) -> str:
        relative = path.resolve().relative_to(self.root).as_posix()
        return f"http://{self.host}:{self.port}/{relative}"

    def request_stop(self) -> None:
        """Ask the serving loop to finish.

        Safe from a signal handler, unlike shutdown(), which blocks until the
        loop exits and so deadlocks when the handler runs on the serving thread.
        """
        self._stopping.set()

    def serve_until_idle(self) -> None:
        # handle_request blocks until a connection arrives, so without a poll
        # timeout a stop request would not be noticed until someone happened to
        # fetch the pad.
        self.timeout = STOP_POLL_SECONDS
        if self.idle_timeout is not None:
            threading.Thread(target=self._watchdog, daemon=True).start()
        while not self._stopping.is_set():
            self.handle_request()

    def _watchdog(self) -> None:
        while not self._stopping.wait(min(WATCHDOG_INTERVAL_SECONDS, self.idle_timeout)):
            if self.idle_seconds >= self.idle_timeout:
                self.request_stop()
                return


def pidfile(root: Path) -> Path:
    return root.resolve() / ".server.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--idle-timeout-minutes", type=float, default=DEFAULT_IDLE_TIMEOUT_MINUTES
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    timeout = args.idle_timeout_minutes
    server = PadServer(
        root, args.host, args.port, idle_timeout=timeout * 60 if timeout > 0 else None
    )

    path = pidfile(root)
    path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "host": server.host,
                "port": server.port,
                "root": str(root),
                "idle_timeout_minutes": timeout,
            }
        )
    )

    def stop_serving(signum, frame):
        server.request_stop()

    signal.signal(signal.SIGTERM, stop_serving)
    signal.signal(signal.SIGINT, stop_serving)

    try:
        server.serve_until_idle()
    finally:
        server.server_close()
        path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
