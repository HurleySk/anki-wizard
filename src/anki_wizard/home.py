"""The home page and the problem set reader.

Both are built on request from what is on disk and written to no file, so
they cannot go stale. Everything here is pure -- a Paths in, HTML out -- and
the pad server is what puts a URL in front of it.

A page must never fail to render because of one bad file under the root: a
broken cursor is listed with a note saying so, and the rest of the page
stands. The one exception is a problem page for a slug with no manifest,
which is the 404 the server sends.
"""

import re
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import quote

from anki_wizard.paths import Paths

# A kept note with an animation runs to a megabyte, and the title is in the
# head; reading the whole file to find it would make the home page as slow as
# its largest note.
TITLE_BYTES = 8192
_TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)


def page_title(path: Path, fallback: str) -> str:
    """A page's title tag as text, or the fallback when it has none."""
    try:
        with path.open("rb") as handle:
            head = handle.read(TITLE_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return fallback
    match = _TITLE.search(head)
    title = unescape(match.group(1)).strip() if match else ""
    return title or fallback


def _written(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def _listing(directory: Path) -> tuple[list[Path], str | None]:
    """A directory's entries by name, or why they could not be read.

    A missing directory is empty rather than an error: a fresh clone has none
    of them.
    """
    if not directory.exists():
        return [], None
    try:
        return sorted(directory.iterdir()), None
    except OSError as exc:
        return [], f"could not read {directory}: {exc}"


def current_pad(paths: Paths) -> dict | None:
    pad = paths.pad_file()
    if not pad.exists():
        return None
    return {
        "title": page_title(pad, "Study pad"),
        "href": "pad.html",
        "written": _written(pad),
    }


def kept_notes(paths: Paths) -> dict:
    entries, problem = _listing(paths.notes_dir())
    files = [p for p in entries if p.suffix == ".html" and p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    items = [
        {
            "name": p.stem,
            "title": page_title(p, p.stem),
            "href": f"notes/{quote(p.name)}",
            "written": _written(p),
        }
        for p in files
    ]
    return {"items": items, "problem": problem}
