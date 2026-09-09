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
import signal
import sys
import threading
import time
from pathlib import Path

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
        super().do_GET()

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
