"""Making a rendered page reachable, and not leaving a server behind.

The servers here are real -- these tests fetch over a socket and start actual
detached processes rather than mock them, the same choice tests/fake_anki.py
makes. Only webbrowser.open is replaced, since launching a browser is what must
not happen during a test run.
"""

import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from anki_wizard import viewer
from anki_wizard.paths import Paths


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


def fetch_response(url: str) -> tuple[int, dict, bytes]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, dict(response.headers), response.read()


@pytest.fixture
def problem_set(pad):
    """A captured set under the state root, beside a file that must stay
    unreachable."""
    paths = Paths(root=pad.parent)
    paths.ensure_source_dirs("ps")
    paths.source_manifest("ps").write_text(
        json.dumps(
            {
                "url": "u",
                "lms": "l",
                "sequential": "s",
                "units": [{"id": "u1", "title": "1. Setup", "pages": [1, 2]}],
            }
        )
    )
    paths.page_image("ps", 1).write_bytes(b"\x89PNG stub")
    paths.page_text("ps", 1).write_text("a hint")
    paths.config_file().write_text("deck: secret")
    return paths


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


def test_a_page_below_the_root_is_served_by_the_one_server(pad):
    """A cheat sheet lives in a subdirectory of the pad but must not get its
    own server: one process per directory would stack up, and the URL host
    and port would differ from the pad's."""
    (pad / "cheatsheets").mkdir()
    sheet = pad / "cheatsheets" / "stats.html"
    sheet.write_text("<p>sheet</p>")
    pad_url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    result = viewer.open_page(sheet, viewer="vscode", root=pad)

    assert result["url"] == pad_url.replace("pad.html", "cheatsheets/stats.html")
    assert fetch(result["url"]) == (200, "<p>sheet</p>")
    assert viewer.running_server(pad / "cheatsheets") is None


def test_a_page_outside_the_root_is_refused(pad, tmp_path):
    elsewhere = tmp_path / "other.html"
    elsewhere.write_text("x")
    with pytest.raises(ValueError, match="not under"):
        viewer.open_page(elsewhere, viewer="vscode", root=pad)


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


def test_an_idle_server_stops_itself(pad):
    """The whole answer to "left running forever": it expires on its own."""
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


def test_use_keeps_a_server_alive(pad):
    """An expiring server must not vanish out from under an active reader."""
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


# --- the home page and the problem reader ------------------------------------


def test_the_root_is_the_home_page(pad):
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    status, headers, body = fetch_response(url.replace("pad.html", ""))

    assert status == 200
    assert "Current pad" in body.decode()
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    # Built on every request, so a tab must reload to the current state.
    assert headers["Cache-Control"] == "no-store"


def test_index_html_is_the_home_page_too(pad):
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    assert "Current pad" in fetch(url.replace("pad.html", "index.html"))[1]


def test_the_home_page_reads_the_state_root(pad):
    """The server serves pad/; the page reads the directory above it, which
    paths.py fixes as the root."""
    (pad / "notes").mkdir()
    (pad / "notes" / "clt.html").write_text("<title>The CLT</title>")
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]

    assert "The CLT" in fetch(url.replace("pad.html", ""))[1]


def test_the_home_page_reflects_a_change_without_a_restart(pad):
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"].replace(
        "pad.html", ""
    )
    assert "No kept notes." in fetch(url)[1]
    (pad / "notes").mkdir()
    (pad / "notes" / "clt.html").write_text("<title>The CLT</title>")
    assert "The CLT" in fetch(url)[1]


def test_a_problem_set_has_a_page(pad, problem_set):
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    status, headers, body = fetch_response(url.replace("pad.html", "problems/ps"))

    assert status == 200
    assert "1. Setup" in body.decode()
    assert "/sources/ps/pages/page-001.png" in body.decode()
    assert headers["Cache-Control"] == "no-store"


def test_a_page_image_is_served_out_of_sources(pad, problem_set):
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"]
    status, headers, body = fetch_response(
        url.replace("pad.html", "sources/ps/pages/page-001.png")
    )

    assert (status, headers["Content-Type"], body) == (200, "image/png", b"\x89PNG stub")


@pytest.mark.parametrize(
    "path",
    [
        "problems/nope",
        "problems/..",
        "problems/ps/",
        "sources/ps/source.json",
        "sources/ps/text/page-001.txt",
        "sources/ps/pages/page-1.png",
        "sources/ps/pages/page-002.png",
        "sources/ps/pages/../source.json",
        "sources/../config.yaml",
        "sources/./config.yaml",
        "../config.yaml",
    ],
)
def test_everything_else_outside_the_pad_is_refused(pad, problem_set, path):
    """One route reaches into sources/, for page images only. The manifest,
    the text layer, the config, and anything reached through a dot segment
    stay unreachable."""
    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"].replace(
        "pad.html", path
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        fetch(url)
    assert excinfo.value.code == 404


def test_a_symlinked_page_image_is_refused(pad, problem_set):
    """The route's guard is on the URL, and a well-named symlink passes it.
    What is served must be contained by the pages directory itself, or the
    one route that reaches outside the pad becomes a way to read the root."""
    problem_set.page_image("ps", 9).symlink_to(problem_set.config_file())

    url = viewer.open_page(pad / "pad.html", viewer="vscode")["url"].replace(
        "pad.html", "sources/ps/pages/page-009.png"
    )
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        fetch(url)
    assert excinfo.value.code == 404


def test_the_health_check_does_not_count_as_use(pad):
    """Liveness probes are the harness talking to itself; counting them would
    keep an unread pad alive forever. A real page does count."""
    from anki_wizard.pad_server import HEALTH_PATH, PadServer

    server = PadServer(pad, port=0)
    try:
        server._last_request = time.monotonic() - 1000
        base = f"http://{server.host}:{server.port}"

        worker = threading.Thread(target=server.handle_request)
        worker.start()
        fetch(base + HEALTH_PATH)
        worker.join(5)
        assert server.idle_seconds > 900

        worker = threading.Thread(target=server.handle_request)
        worker.start()
        fetch(base + "/")
        worker.join(5)
        assert server.idle_seconds < 60
    finally:
        server.server_close()


# --- open_root ---------------------------------------------------------------


def test_open_root_returns_the_home_url(pad, browser):
    result = viewer.open_root(pad, viewer="vscode")

    assert result["viewer"] == "vscode"
    assert result["opened"] is False
    assert result["url"].endswith("/")
    assert fetch(result["url"])[0] == 200
    assert browser == []


def test_open_root_in_a_browser_still_needs_the_server(pad, browser):
    """The home page has no file for a browser to open, so unlike open_page
    the browser viewer serves it too."""
    result = viewer.open_root(pad, viewer="browser")

    assert result["viewer"] == "browser"
    assert result["opened"] is True
    assert browser == [result["url"]]
    assert fetch(result["url"])[0] == 200


def test_open_root_none_starts_nothing(pad, browser):
    assert viewer.open_root(pad, viewer="none") == {"viewer": "none", "opened": False}
    assert browser == []
    assert not viewer.pidfile(pad).exists()


def test_open_root_refuses_an_unknown_viewer(pad):
    with pytest.raises(ValueError, match="unknown viewer"):
        viewer.open_root(pad, viewer="chrome")
