"""The home page and the problem reader, built from a state tree on disk.

No server here: the builders are pure, a Paths in and HTML out, and
tests/test_viewer.py covers the routes that put them behind a URL.
"""

import json
import os

import pytest

from anki_wizard import home
from anki_wizard.cheatsheet import save_sheet
from anki_wizard.cursor import save_cursor
from anki_wizard.edx import outline_from_manifest
from anki_wizard.models import Cursor, Outline, Section
from anki_wizard.outline import save_outline
from anki_wizard.paths import Paths
from anki_wizard.render import render_html


@pytest.fixture
def workspace(tmp_path):
    return Paths(root=tmp_path)


def write_note(paths, name, title=None, mtime=None):
    path = paths.note_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html([], title=title) if title else "<p>untitled</p>")
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def write_document(paths, slug, sections, covered):
    paths.ensure_source_dirs(slug)
    paths.source_pdf(slug).write_bytes(b"%PDF-1.4 stub")
    save_outline(
        paths.outline_file(slug),
        Outline(
            slug=slug,
            pages=sections,
            structure="pages",
            sections=[
                Section(id=str(n), title=f"Page {n}", pages=[n, n + 1])
                for n in range(1, sections + 1)
            ],
        ),
    )
    save_cursor(paths.cursor_file(slug), Cursor(covered=[str(n) for n in covered]))


def write_problem_set(paths, slug, units):
    """`units` is a list of (title, [start, end], reason or None)."""
    paths.ensure_source_dirs(slug)
    manifest = {
        "url": "https://lms.example/x",
        "lms": "https://lms.example",
        "sequential": "seq",
        "units": [
            {
                "id": f"u{n}",
                "title": title,
                "pages": pages,
                **({"reason": reason} if reason else {}),
            }
            for n, (title, pages, reason) in enumerate(units, start=1)
        ],
    }
    paths.source_manifest(slug).write_text(json.dumps(manifest))
    save_outline(paths.outline_file(slug), outline_from_manifest(slug, manifest))
    save_cursor(paths.cursor_file(slug), Cursor())


def write_sheet(paths, slug, formulas, page_title=None):
    save_sheet(paths.cheatsheet_file(slug), formulas)
    if page_title is not None:
        page = paths.cheatsheet_page(slug)
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(render_html([], title=page_title, body_class="sheet"))


# --- the current pad ---------------------------------------------------------


def test_no_pad_is_none(workspace):
    assert home.current_pad(workspace) is None


def test_the_current_pad_is_titled_and_linked(workspace):
    workspace.pad_dir().mkdir()
    workspace.pad_file().write_text(render_html([], title="Bernoulli moments"))
    pad = home.current_pad(workspace)
    assert pad["title"] == "Bernoulli moments"
    assert pad["href"] == "pad.html"
    assert len(pad["written"]) == len("2026-09-15 10:00")


# --- kept notes --------------------------------------------------------------


def test_no_notes_directory_is_an_empty_list(workspace):
    assert home.kept_notes(workspace) == {"items": [], "problem": None}


def test_kept_notes_are_newest_first(workspace):
    write_note(workspace, "old", title="Old", mtime=1_700_000_000)
    write_note(workspace, "new", title="New", mtime=1_700_100_000)
    items = home.kept_notes(workspace)["items"]
    assert [n["title"] for n in items] == ["New", "Old"]
    assert items[0]["href"] == "notes/new.html"


def test_a_note_without_a_title_falls_back_to_its_name(workspace):
    write_note(workspace, "clt")
    assert home.kept_notes(workspace)["items"][0]["title"] == "clt"


def test_a_title_past_the_head_is_not_seen(workspace):
    """A kept note with an animation runs to a megabyte; only the head is
    read, so a title tag that somehow lands in the body is not found."""
    path = write_note(workspace, "big")
    path.write_text("<p>" + "x" * home.TITLE_BYTES + "</p><title>Late</title>")
    assert home.page_title(path, "big") == "big"


def test_a_title_is_text_even_when_it_looks_like_markup(workspace):
    """The title tag holds escaped text; it is unescaped to read and escaped
    again to show, so what the page displays is what the user typed."""
    write_note(workspace, "b", title="<b>bold</b>")
    assert home.kept_notes(workspace)["items"][0]["title"] == "<b>bold</b>"


def test_an_unreadable_notes_directory_is_reported_not_raised(workspace):
    workspace.pad_dir().mkdir()
    workspace.notes_dir().write_text("a file where the directory should be")
    listing = home.kept_notes(workspace)
    assert listing["items"] == []
    assert "notes" in listing["problem"]
