"""Making a rendered page reachable, and not leaving a server behind.

The servers here are real -- these tests fetch over a socket and start actual
detached processes rather than mock them, the same choice tests/fake_anki.py
makes. Only webbrowser.open is replaced, since launching a browser is what must
not happen during a test run.
"""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from anki_wizard import viewer


@pytest.fixture
def pad(tmp_path):
    directory = tmp_path / "pad"
    directory.mkdir()
    (directory / "pad.html").write_text("<p>hi</p>")
    return directory


@pytest.fixture(autouse=True)
def no_servers_left_running(pad):
    yield
    viewer.stop(pad)


@pytest.fixture
def browser(monkeypatch):
    """Records URIs handed to the browser instead of opening one."""
    opened = []
    monkeypatch.setattr(
        viewer.webbrowser, "open", lambda uri: opened.append(uri) or True
    )
    return opened


def fetch(url: str) -> tuple[int, str]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, response.read().decode()


def test_the_served_url_returns_the_page(pad, browser):
    result = viewer.open_page(pad / "pad.html", viewer="vscode")

    assert result["viewer"] == "vscode"
    assert fetch(result["url"]) == (200, "<p>hi</p>")
    assert browser == []


def test_the_url_outlives_the_process_that_rendered_it(pad):
    """The point of detaching: a one-shot script must not hand out a dead link."""
    record = viewer.start_detached(pad, port=viewer.free_port())

    # start_detached returns once the child owns the socket, so the child is
    # already serving independently of this process.
    assert record["pid"] != __import__("os").getpid()
    assert fetch(f"http://{record['host']}:{record['port']}/pad.html")[0] == 200


def test_the_url_is_loopback_only(pad):
    """The pad is local scratch; nothing off this machine should reach it."""
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    assert url.startswith("http://127.0.0.1:")


def test_only_the_pad_directory_is_served(pad):
    """A server rooted higher would expose the whole repository."""
    (pad.parent / "secret.txt").write_text("not yours")
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]

    with pytest.raises(urllib.error.HTTPError) as excinfo:
        fetch(url.replace("pad.html", "../secret.txt"))
    assert excinfo.value.code == 404


def test_kept_notes_are_reachable(pad):
    """Notes live under the pad directory, so promoting one keeps it viewable."""
    (pad / "notes").mkdir()
    (pad / "notes" / "clt.html").write_text("<p>kept</p>")
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]

    assert fetch(url.replace("pad.html", "notes/clt.html")) == (200, "<p>kept</p>")


def test_a_second_render_reuses_the_running_server(pad):
    """A server per render would stack up processes and change the URL."""
    first = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    second = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    assert first == second


def test_the_url_serves_the_current_pad(pad):
    """The URL is stable across renders, so it must not serve a stale page."""
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    (pad / "pad.html").write_text("<p>rerendered</p>")

    assert fetch(url) == (200, "<p>rerendered</p>")


def test_an_idle_server_stops_itself(pad, monkeypatch):
    """The whole answer to "left running forever": it expires on its own."""
    monkeypatch.setattr(viewer, "WATCHDOG_INTERVAL_SECONDS", 0.05)
    record = viewer.start_detached(
        pad, port=viewer.free_port(), idle_timeout_minutes=0.02
    )
    url = f"http://{record['host']}:{record['port']}/pad.html"
    assert fetch(url)[0] == 200

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if viewer.probe(record["host"], record["port"]) is None:
            break
        time.sleep(0.1)
    else:
        pytest.fail("idle server never stopped")

    assert not viewer.pidfile(pad).exists()


def test_use_keeps_a_server_alive(pad, monkeypatch):
    """An expiring server must not vanish out from under an active reader."""
    monkeypatch.setattr(viewer, "WATCHDOG_INTERVAL_SECONDS", 0.05)
    record = viewer.start_detached(
        pad, port=viewer.free_port(), idle_timeout_minutes=0.05
    )
    url = f"http://{record['host']}:{record['port']}/pad.html"

    for _ in range(8):
        time.sleep(0.5)
        assert fetch(url)[0] == 200


def test_a_stale_pidfile_is_replaced(pad):
    """A killed server leaves its pidfile behind; the next render must recover."""
    viewer.pidfile(pad).write_text(
        json.dumps({"pid": 999999, "host": "127.0.0.1", "port": viewer.free_port()})
    )
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    assert fetch(url)[0] == 200


def test_a_pidfile_of_junk_is_replaced(pad):
    viewer.pidfile(pad).write_text("not json")
    assert fetch(viewer.open_page(pad / "pad.html", viewer="vscode")["url"])[0] == 200


def test_a_taken_port_falls_back_to_a_free_one(pad):
    """A second project on the default port must not leave the pad unreachable."""
    import socket

    with socket.socket() as blocker:
        blocker.bind((viewer.DEFAULT_HOST, 0))
        blocker.listen(1)
        taken = blocker.getsockname()[1]

        record = viewer.start_detached(pad, port=taken)
        assert record["port"] != taken
        assert fetch(f"http://{record['host']}:{record['port']}/pad.html")[0] == 200


def test_stop_kills_the_server_and_clears_the_pidfile(pad):
    record = viewer.start_detached(pad, port=viewer.free_port())

    assert viewer.stop(pad) is True
    assert viewer.probe(record["host"], record["port"]) is None
    assert not viewer.pidfile(pad).exists()


def test_stopping_nothing_is_not_an_error(pad):
    assert viewer.stop(pad) is False


def test_sigterm_stops_the_server(pad):
    """scripts/stop_pad.py relies on this, and shutdown() from a handler hangs."""
    import os
    import signal as signal_module

    record = viewer.start_detached(pad, port=viewer.free_port())
    os.kill(record["pid"], signal_module.SIGTERM)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if viewer.probe(record["host"], record["port"]) is None:
            break
        time.sleep(0.05)
    else:
        pytest.fail("server ignored SIGTERM")

    assert not viewer.pidfile(pad).exists()


def test_browser_viewer_opens_the_file_directly(pad, browser):
    """No server needed when a browser can read the file itself."""
    result = viewer.open_page(pad / "pad.html", viewer="browser")

    assert result == {"viewer": "browser", "opened": True}
    assert browser == [(pad / "pad.html").as_uri()]
    assert not viewer.pidfile(pad).exists()


def test_a_relative_path_still_resolves(tmp_path, monkeypatch, browser):
    """Paths(root=Path(".")) is the normal case; a relative path has no file URI."""
    monkeypatch.chdir(tmp_path)
    page = Path("pad.html")
    page.write_text("x")

    viewer.open_page(page, viewer="browser")

    assert browser == [page.resolve().as_uri()]


def test_none_opens_and_serves_nothing(pad, browser):
    result = viewer.open_page(pad / "pad.html", viewer="none")

    assert result == {"viewer": "none", "opened": False}
    assert browser == []
    assert not viewer.pidfile(pad).exists()


def test_an_unknown_viewer_is_refused(pad, browser):
    """A typo in config.yaml must say so, not silently pick a default."""
    with pytest.raises(ValueError, match="unknown viewer"):
        viewer.open_page(pad / "pad.html", viewer="chrome")
    assert browser == []
    assert not viewer.pidfile(pad).exists()
