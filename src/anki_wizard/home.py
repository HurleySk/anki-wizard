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
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote

import yaml

from anki_wizard.cheatsheet import load_sheet
from anki_wizard.cursor import load_cursor
from anki_wizard.outline import load_outline
from anki_wizard.paths import Paths
from anki_wizard.render import render_page

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


def cheat_sheets(paths: Paths) -> dict:
    entries, problem = _listing(paths.cheatsheets_dir())
    items = []
    for path in entries:
        if path.suffix != ".yaml" or not path.is_file():
            continue
        slug = path.stem
        page = paths.cheatsheet_page(slug)
        # The page is derived from the YAML on every review, so a sheet with
        # nothing approved yet has no page; the YAML is still worth listing.
        item = {
            "slug": slug,
            "title": page_title(page, slug) if page.exists() else slug,
            "href": f"cheatsheets/{quote(page.name)}" if page.exists() else None,
            "approved": None,
            "problem": None,
        }
        try:
            formulas = load_sheet(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            # load_sheet names the file and entry for a bad row; malformed
            # YAML surfaces from the parser instead, and both belong on the
            # page rather than in a traceback nobody sees.
            item["problem"] = str(exc)
        else:
            item["approved"] = sum(1 for f in formulas if f.state == "approved")
        items.append(item)
    return {"items": items, "problem": problem}


def sources(paths: Paths) -> dict:
    entries, problem = _listing(paths.sources_dir())
    items = []
    for directory in entries:
        # .auth is the course-site login session, not a source.
        if not directory.is_dir() or directory.name.startswith("."):
            continue
        slug = directory.name
        if paths.source_manifest(slug).exists():
            kind = "problem set"
        elif paths.source_pdf(slug).exists():
            kind = "document"
        else:
            kind = "unknown"
        item = {
            "slug": slug,
            "kind": kind,
            # A document's page images are the agent's reading material, not
            # the user's, so only a problem set gets a page here.
            "href": f"/problems/{quote(slug)}" if kind == "problem set" else None,
            "covered": None,
            "total": None,
            "problem": None,
        }
        try:
            outline = load_outline(paths.outline_file(slug))
            cursor = load_cursor(paths.cursor_file(slug))
        except (OSError, ValueError) as exc:
            # Both loaders name the file; a missing outline is the OSError.
            item["problem"] = str(exc)
        else:
            item["total"] = len(outline.sections)
            item["covered"] = sum(1 for s in outline.sections if s.id in cursor.covered)
        items.append(item)
    return {"items": items, "problem": problem}


def home_page(paths: Paths) -> str:
    """The front door: everything under the root worth reading, as links."""
    parts = [f"<h1>{escape(paths.root.resolve().name)}</h1>", "<h2>Current pad</h2>"]
    pad = current_pad(paths)
    if pad is None:
        parts.append('<p class="muted">No pad has been rendered.</p>')
    else:
        parts.append(
            f'<p><a href="{pad["href"]}">{escape(pad["title"])}</a>'
            f'{_meta("written " + pad["written"])}</p>'
        )
    parts.append(_section("Kept notes", kept_notes(paths), _note_item, "No kept notes."))
    parts.append(
        _section("Cheat sheets", cheat_sheets(paths), _sheet_item, "No cheat sheets.")
    )
    parts.append(_section("Sources", sources(paths), _source_item, "No sources."))
    return render_page("\n".join(parts), title="Home", body_class="home", home_link=False)


def _section(heading: str, listing: dict, render_item, empty: str) -> str:
    parts = [f"<h2>{escape(heading)}</h2>"]
    if listing["problem"]:
        parts.append(f'<p class="problem">{escape(listing["problem"])}</p>')
    if listing["items"]:
        parts.append(
            '<ul class="index">'
            + "".join(f"<li>{render_item(item)}</li>" for item in listing["items"])
            + "</ul>"
        )
    elif not listing["problem"]:
        parts.append(f'<p class="muted">{escape(empty)}</p>')
    return "\n".join(parts)


def _meta(text: str) -> str:
    return f' <span class="meta">{escape(text)}</span>'


def _problem(text: str) -> str:
    return f' <span class="problem">{escape(text)}</span>'


def _note_item(note: dict) -> str:
    return (
        f'<a href="{note["href"]}">{escape(note["title"])}</a>'
        f'{_meta("written " + note["written"])}'
    )


def _sheet_item(sheet: dict) -> str:
    if sheet["href"]:
        name = f'<a href="{sheet["href"]}">{escape(sheet["title"])}</a>'
    else:
        name = escape(sheet["title"]) + _meta("page not built")
    if sheet["problem"]:
        return name + _problem(sheet["problem"])
    count = sheet["approved"]
    return name + _meta(f"{count} formula" if count == 1 else f"{count} formulas")


def _source_item(source: dict) -> str:
    if source["href"]:
        name = f'<a href="{source["href"]}">{escape(source["slug"])}</a>'
    else:
        name = escape(source["slug"])
    if source["problem"]:
        return name + _meta(source["kind"]) + _problem(source["problem"])
    progress = f'{source["kind"]} · {source["covered"]} of {source["total"]} sections'
    return name + _meta(progress)
