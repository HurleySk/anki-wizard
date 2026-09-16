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
from anki_wizard.models import Cursor, Formula, Outline, Section
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


# --- cheat sheets ------------------------------------------------------------


def test_a_sheet_shows_its_approved_count_and_page(workspace):
    write_sheet(
        workspace,
        "stats",
        [
            Formula(id="f-0001", tex="x", label="One", state="approved"),
            Formula(id="f-0002", tex="y", label="Two", state="proposed"),
            Formula(id="f-0003", tex="z", label="Three", state="rejected"),
        ],
        page_title="Fundamentals of Statistics",
    )
    assert home.cheat_sheets(workspace)["items"] == [
        {
            "slug": "stats",
            "title": "Fundamentals of Statistics",
            "href": "cheatsheets/stats.html",
            "approved": 1,
            "problem": None,
        }
    ]


def test_a_sheet_without_a_page_is_listed_unlinked(workspace):
    """The page is built on the first review; until then the YAML is the
    only thing there, and a link to a missing page is worse than none."""
    write_sheet(workspace, "stats", [])
    item = home.cheat_sheets(workspace)["items"][0]
    assert item["href"] is None
    assert item["title"] == "stats"
    assert item["approved"] == 0


def test_a_broken_sheet_is_listed_with_the_reason(workspace):
    workspace.cheatsheets_dir().mkdir()
    workspace.cheatsheet_file("stats").write_text("- id: f-0001\n")
    item = home.cheat_sheets(workspace)["items"][0]
    assert item["approved"] is None
    assert "entry 0" in item["problem"]


def test_a_sheet_of_broken_yaml_is_listed_with_the_reason(workspace):
    workspace.cheatsheets_dir().mkdir()
    workspace.cheatsheet_file("stats").write_text("- [unclosed\n")
    item = home.cheat_sheets(workspace)["items"][0]
    assert item["approved"] is None
    assert item["problem"]


# --- sources -----------------------------------------------------------------


def test_a_document_shows_its_progress_and_has_no_page(workspace):
    write_document(workspace, "stats-ch1", sections=3, covered=[1, 2])
    assert home.sources(workspace)["items"] == [
        {
            "slug": "stats-ch1",
            "kind": "document",
            "href": None,
            "covered": 2,
            "total": 3,
            "problem": None,
        }
    ]


def test_a_problem_set_links_to_its_reader(workspace):
    write_problem_set(workspace, "pset-1", [("1. Setup", [1, 3], None)])
    item = home.sources(workspace)["items"][0]
    assert item["kind"] == "problem set"
    assert item["href"] == "/problems/pset-1"
    assert (item["covered"], item["total"]) == (0, 1)


def test_sources_are_sorted_by_slug(workspace):
    write_document(workspace, "b-doc", sections=1, covered=[])
    write_document(workspace, "a-doc", sections=1, covered=[])
    assert [s["slug"] for s in home.sources(workspace)["items"]] == ["a-doc", "b-doc"]


def test_the_login_session_is_not_a_source(workspace):
    auth = workspace.edx_auth_state()
    auth.parent.mkdir(parents=True)
    auth.write_text("{}")
    assert home.sources(workspace)["items"] == []


def test_a_source_with_nothing_recognisable_is_unknown(workspace):
    workspace.source_dir("stray").mkdir(parents=True)
    item = home.sources(workspace)["items"][0]
    assert item["kind"] == "unknown"
    assert "outline.json" in item["problem"]


def test_a_broken_cursor_names_the_file(workspace):
    write_document(workspace, "stats-ch1", sections=3, covered=[1])
    workspace.cursor_file("stats-ch1").write_text("not json")
    item = home.sources(workspace)["items"][0]
    assert item["covered"] is None
    assert "cursor.json" in item["problem"]


def test_covered_counts_only_sections_the_outline_has(workspace):
    """Cursors are hand-editable; a stale id must not push coverage past
    the total."""
    write_document(workspace, "doc", sections=2, covered=[1, 2])
    save_cursor(workspace.cursor_file("doc"), Cursor(covered=["1", "2", "9"]))
    item = home.sources(workspace)["items"][0]
    assert (item["covered"], item["total"]) == (2, 2)


def test_an_unreadable_sources_directory_is_reported_not_raised(workspace):
    workspace.sources_dir().write_text("a file, not a directory")
    listing = home.sources(workspace)
    assert listing["items"] == []
    assert "sources" in listing["problem"]
