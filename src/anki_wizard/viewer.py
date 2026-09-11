"""Makes a rendered page reachable, in VS Code or a browser.

VS Code opens a page in an editor tab only when handed an http:// URL it can
turn into a link: no CLI flag or vscode:// URI reaches Simple Browser, and both
built-in previewers declare no URI handler. Serving the pad is what buys the
in-editor view.

This module is the process side of that: starting a detached server, finding
one that is already up, and stopping it. The server itself lives in
pad_server.py, which is also the module the detached child runs.
"""

import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# The pidfile is the contract between the two halves: pad_server writes it,
# this module polls and deletes it, so it is defined alongside the writer.
from anki_wizard.pad_server import (
    DEFAULT_HOST,
    DEFAULT_IDLE_TIMEOUT_MINUTES,
    DEFAULT_PORT,
    HEALTH_PATH,
    pidfile,
)

VIEWERS = ("vscode", "browser", "none")


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
    root: Path | None = None,
) -> dict:
    """Make a page viewable, reporting where it can be reached.

    `root` is the directory served, and defaults to the page's own. A page in
    a subdirectory of the pad passes the pad as root so it is reached through
    the one server already running there, at a URL carrying the subpath,
    rather than by a second server rooted at the subdirectory.
    """
    if viewer not in VIEWERS:
        raise ValueError(
            f"unknown viewer {viewer!r}; expected one of {', '.join(VIEWERS)}"
        )
    # Callers routinely hold a relative path (Paths(root=Path("."))), which has
    # no file URI at all.
    path = path.resolve()
    root = path.parent if root is None else root.resolve()
    try:
        subpath = path.relative_to(root).as_posix()
    except ValueError:
        raise ValueError(f"{path} is not under the served root {root}") from None

    if viewer == "none":
        return {"viewer": "none", "opened": False}

    if viewer == "browser":
        return {"viewer": "browser", "opened": bool(webbrowser.open(path.as_uri()))}

    try:
        record = start_detached(root, idle_timeout_minutes=idle_timeout_minutes)
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
        "url": f"http://{record['host']}:{record['port']}/{subpath}",
        "expires_after_idle_minutes": record["idle_timeout_minutes"],
    }


def free_port(host: str = DEFAULT_HOST) -> int:
    """An unused port, for tests that need one that is definitely free."""
    with socket.socket() as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]
