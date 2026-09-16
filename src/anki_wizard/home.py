"""The home page, the cheat sheet, and the problem set reader.

Each is built on request from what is on disk, so none of them can carry a
page shell older than the running code. Everything here is pure -- a Paths
in, HTML out -- and the pad server is what puts a URL in front of it.

A page must never fail to render because of one bad file under the root: a
broken cursor is listed with a note saying so, and the rest of the page
stands. The exceptions are the pages the server sends a 404 for instead: a
problem page for a slug with no manifest, and a sheet for a slug that is not
this directory's course.
"""

import json
import re
from datetime import datetime
from html import escape, unescape
from pathlib import Path
from urllib.parse import quote

import yaml

from anki_wizard.cheatsheet import load_sheet, render_sheet_page
from anki_wizard.config import load_config
from anki_wizard.cursor import load_cursor
from anki_wizard.outline import load_outline
from anki_wizard.paths import Paths, deck_slug
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
        # The page is built on request from this YAML, so every sheet has
        # one; there is no "not built yet" state to represent.
        item = {
            "slug": slug,
            "title": sheet_title(slug, paths),
            "href": f"cheatsheets/{quote(slug)}.html",
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


def configured_deck(paths: Paths) -> str | None:
    """The deck this state directory is for, or None if it cannot be read.

    A config that will not parse is a bad reason to lose the whole home
    page, so it reads as "no deck" and each caller falls back.
    """
    try:
        return load_config(paths.config_file()).deck
    except (OSError, ValueError, yaml.YAMLError):
        return None


def sheet_title(slug: str, paths: Paths) -> str:
    """The deck name a sheet's slug stands for, or the slug itself.

    The name is Anki's, and the slug is lossy -- it cannot be turned back
    into "Unit I: ..." or a deck whose name has a colon in it. So the name
    comes from the config that produced the slug, and a slug from some other
    course names itself.
    """
    deck = configured_deck(paths)
    if deck is not None and deck_slug(deck) == slug:
        return deck
    return slug


def sheet_page(slug: str, paths: Paths) -> str:
    """A course's printable sheet, built from its YAML.

    Built on request rather than read from the file the reviews write, so
    the page carries the running shell: a stored page keeps whatever markup
    was current when it was last written, and nothing rebuilds it when the
    shell around it changes.

    Raises KeyError for a slug that is not this directory's course or has no
    sheet, and ValueError for a sheet that will not load -- the two the
    server turns into a 404.
    """
    deck = configured_deck(paths)
    if deck is None or deck_slug(deck) != slug:
        raise KeyError(slug)
    path = paths.cheatsheet_file(slug)
    if not path.exists():
        raise KeyError(slug)
    try:
        formulas = load_sheet(path)
    except (OSError, yaml.YAMLError) as exc:
        # load_sheet raises ValueError itself for a bad row; a parse or read
        # failure is the same kind of answer to the same question.
        raise ValueError(f"{path} is not a readable cheat sheet: {exc}") from exc
    return render_sheet_page(deck, formulas)[0]


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
            # Read inside the try: both loaders validate on construction, so a
            # hand-edited file of the wrong shape survives loading and fails
            # only here, where a raise would take the whole page down.
            total = len(outline.sections)
            covered = sum(1 for s in outline.sections if s.id in cursor.covered)
        except (OSError, ValueError, TypeError) as exc:
            # Both loaders name the file; a missing outline is the OSError.
            item["problem"] = str(exc)
        else:
            item["total"] = total
            item["covered"] = covered
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
    name = f'<a href="{sheet["href"]}">{escape(sheet["title"])}</a>'
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


def problems_page(slug: str, paths: Paths) -> str:
    """A captured problem set: each tab as a section, each block image in order.

    A reader, not a practice surface. Show Answer was clicked at capture, so
    every image already carries its solution. The text hint beside each image
    is left out: the image is the source. Raises KeyError for a slug with no
    manifest, which is the one case that is a 404 rather than a page.
    """
    manifest_path = paths.source_manifest(slug)
    if not manifest_path.exists():
        raise KeyError(slug)

    parts = [f"<h1>{escape(slug)}</h1>"]
    try:
        manifest = json.loads(manifest_path.read_text())
        units = [
            (str(u["title"]), int(u["pages"][0]), int(u["pages"][1]), u.get("reason"))
            for u in manifest["units"]
        ]
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        # Hand-inspectable and so hand-edited, like the outline; the page
        # says so in the same words existing_manifest would.
        reason = f"{manifest_path} is not a readable source manifest: {exc}"
        parts.append(f'<p class="problem">{escape(reason)}</p>')
        return render_page("\n".join(parts), title=slug, body_class="reader")

    for title, start, end, reason in units:
        parts.append(f"<h2>{escape(title)}</h2>")
        if reason:
            # A tab the site would not serve, recorded rather than captured.
            parts.append(f'<p class="muted">{escape(str(reason))}</p>')
        for page in range(start, end):
            src = f"/sources/{quote(slug)}/pages/page-{page:03d}.png"
            parts.append(f'<img src="{src}" alt="page {page}">')
    return render_page("\n".join(parts), title=slug, body_class="reader")
