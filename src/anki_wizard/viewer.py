"""Makes a rendered page reachable, in VS Code or a browser.

VS Code opens a page in an editor tab only when handed an http:// URL it can
turn into a link: no CLI flag or vscode:// URI reaches Simple Browser, and both
built-in previewers declare no URI handler. Serving the pad is what buys the
in-editor view.

The server runs detached so the URL outlives the process that rendered the pad,
and stops itself once nothing has fetched for a while -- a crashed parent must
not leak a server that runs forever.
"""

import contextlib
import functools
import http.server
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

VIEWERS = ("vscode", "browser", "none")

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


def probe(host: str, port: int, timeout: float = 2.0) -> str | None:
    """The root a pad server on this port serves, or None if it is not one."""
    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}{HEALTH_PATH}", timeout=timeout
        ) as response:
            return json.load(response)["root"]
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        return None


def running_server(root: Path) -> dict | None:
    """Details of a live server for this directory, if one is already up."""
    root = root.resolve()
    path = pidfile(root)
    try:
        record = json.loads(path.read_text())
    except (ValueError, OSError):
        return None
    if probe(record.get("host", ""), record.get("port", 0)) != str(root):
        # Stale: the process died, or something else took the port.
        path.unlink(missing_ok=True)
        return None
    return record


def start_detached(
    root: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    idle_timeout_minutes: float = DEFAULT_IDLE_TIMEOUT_MINUTES,
) -> dict:
    """Start a server that outlives this process, or return the running one."""
    root = root.resolve()
    existing = running_server(root)
    if existing is not None:
        return existing

    if _port_taken(host, port):
        port = 0  # Something else is there; let the OS choose.

    # The child imports anki_wizard, and sys.executable is not guaranteed to
    # find it -- under `uv run` it is a bare interpreter with no project on its
    # path. Handing down the parent's sys.path is what makes the child runnable
    # from any launcher.
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [p for p in sys.path if p] + [environment.get("PYTHONPATH", "")]
    ).strip(os.pathsep)

    process = subprocess.Popen(
        [
            sys.executable, "-m", "anki_wizard.pad_server", str(root),
            "--host", host,
            "--port", str(port),
            "--idle-timeout-minutes", str(idle_timeout_minutes),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=environment,
    )

    record = _await_pidfile(root, process)
    if record is None:
        process.terminate()
        raise OSError(f"pad server for {root} did not start")
    return record


def _await_pidfile(root: Path, process, timeout: float = 10.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = running_server(root)
        if record is not None:
            return record
        if process.poll() is not None:
            return None
        time.sleep(0.05)
    return None


def _port_taken(host: str, port: int) -> bool:
    if port == 0:
        return False
    with socket.socket() as sock:
        # SO_REUSEADDR matches how the server itself binds, so a TIME_WAIT left
        # by a stopped server does not read as a port still in use.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def stop(root: Path, timeout: float = 10.0) -> bool:
    """Stop the server for this directory. True if one was running.

    Waits for the port to close, so a caller that stops a server and starts
    another does not race the old one still holding the socket.
    """
    root = root.resolve()
    record = running_server(root)
    if record is None:
        pidfile(root).unlink(missing_ok=True)
        return False

    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(record["pid"], signal.SIGTERM)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if probe(record["host"], record["port"], timeout=0.5) is None:
            break
        time.sleep(0.05)
    else:
        # It ignored SIGTERM; a pad server is not worth leaving behind.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(record["pid"], signal.SIGKILL)

    pidfile(root).unlink(missing_ok=True)
    return True


def open_page(
    path: Path,
    viewer: str = "vscode",
    idle_timeout_minutes: float = DEFAULT_IDLE_TIMEOUT_MINUTES,
) -> dict:
    """Make a page viewable, reporting where it can be reached."""
    if viewer not in VIEWERS:
        raise ValueError(
            f"unknown viewer {viewer!r}; expected one of {', '.join(VIEWERS)}"
        )
    # Callers routinely hold a relative path (Paths(root=Path("."))), which has
    # no file URI at all.
    path = path.resolve()

    if viewer == "none":
        return {"viewer": "none", "opened": False}

    if viewer == "browser":
        return {"viewer": "browser", "opened": bool(webbrowser.open(path.as_uri()))}

    try:
        record = start_detached(path.parent, idle_timeout_minutes=idle_timeout_minutes)
    except OSError as exc:
        # No server means no http:// URL and so no editor tab, but the file URI
        # still renders in a browser.
        return {
            "viewer": "browser",
            "opened": bool(webbrowser.open(path.as_uri())),
            "fell_back_from": "vscode",
            "reason": str(exc),
        }

    # Not opened: the agent hands the URL to the user, who clicks it. VS Code
    # renders it in Simple Browser.
    return {
        "viewer": "vscode",
        "opened": False,
        "url": f"http://{record['host']}:{record['port']}/{path.name}",
        "expires_after_idle_minutes": record["idle_timeout_minutes"],
    }


def free_port(host: str = DEFAULT_HOST) -> int:
    """An unused port, for tests that need one that is definitely free."""
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]
