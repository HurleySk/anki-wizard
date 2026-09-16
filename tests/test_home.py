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


def write_sheet(paths, slug, formulas):
    save_sheet(paths.cheatsheet_file(slug), formulas)


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
    workspace.config_file().write_text("deck: Fundamentals of Statistics\n")
    write_sheet(
        workspace,
        "fundamentals-of-statistics",
        [
            Formula(id="f-0001", tex="x", label="One", state="approved"),
            Formula(id="f-0002", tex="y", label="Two", state="proposed"),
            Formula(id="f-0003", tex="z", label="Three", state="rejected"),
        ],
    )
    assert home.cheat_sheets(workspace)["items"] == [
        {
            "slug": "fundamentals-of-statistics",
            "title": "Fundamentals of Statistics",
            "href": "cheatsheets/fundamentals-of-statistics.html",
            "approved": 1,
            "problem": None,
        }
    ]


def test_a_sheet_with_nothing_approved_is_still_linked(workspace):
    """The page is built on request from the YAML, so every sheet has one --
    an empty sheet renders as an empty page, which is honest."""
    write_sheet(workspace, "stats", [])
    item = home.cheat_sheets(workspace)["items"][0]
    assert item["href"] == "cheatsheets/stats.html"
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


def test_a_sheet_is_titled_from_the_configured_deck(workspace):
    workspace.config_file().write_text("deck: Fundamentals of Statistics\n")
    assert home.sheet_title("fundamentals-of-statistics", workspace) == (
        "Fundamentals of Statistics"
    )


def test_a_sheet_that_is_not_the_configured_course_keeps_its_slug(workspace):
    workspace.config_file().write_text("deck: Fundamentals of Statistics\n")
    assert home.sheet_title("linear-algebra", workspace) == "linear-algebra"


def test_a_sheet_title_falls_back_when_the_config_is_unreadable(workspace):
    """A broken config must not take the home page down; the slug still names
    the sheet."""
    workspace.config_file().write_text("deck: [unclosed\n")
    assert home.sheet_title("stats", workspace) == "stats"


def test_sheet_page_renders_the_approved_formulas(workspace):
    workspace.config_file().write_text("deck: Fundamentals of Statistics\n")
    write_sheet(
        workspace,
        "fundamentals-of-statistics",
        [
            Formula(id="f-0001", tex="a=b", label="Kept", state="approved"),
            Formula(id="f-0002", tex="c=d", label="Pending", state="proposed"),
        ],
    )
    html = home.sheet_page("fundamentals-of-statistics", workspace)

    assert "Kept" in html
    assert "a=b" in html
    # Only the approved entries reach the printable page.
    assert "Pending" not in html
    assert "<title>Fundamentals of Statistics</title>" in html


def test_sheet_page_links_home(workspace):
    workspace.config_file().write_text("deck: Fundamentals of Statistics\n")
    write_sheet(workspace, "fundamentals-of-statistics", [])
    assert '<nav class="home"><a href="/">Home</a></nav>' in home.sheet_page(
        "fundamentals-of-statistics", workspace
    )


def test_sheet_page_for_a_slug_that_is_not_the_course_raises(workspace):
    workspace.config_file().write_text("deck: Fundamentals of Statistics\n")
    write_sheet(workspace, "linear-algebra", [])
    with pytest.raises(KeyError):
        home.sheet_page("linear-algebra", workspace)


def test_sheet_page_for_a_missing_sheet_raises(workspace):
    workspace.config_file().write_text("deck: Fundamentals of Statistics\n")
    with pytest.raises(KeyError):
        home.sheet_page("fundamentals-of-statistics", workspace)


def test_sheet_page_of_broken_yaml_raises_the_reason(workspace):
    """A bad sheet is a 404 naming the reason, not a traceback out of the
    server thread."""
    workspace.config_file().write_text("deck: Fundamentals of Statistics\n")
    workspace.cheatsheets_dir().mkdir()
    workspace.cheatsheet_file("fundamentals-of-statistics").write_text("- [unclosed\n")
    with pytest.raises(ValueError):
        home.sheet_page("fundamentals-of-statistics", workspace)


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


def test_a_cursor_holding_the_wrong_type_is_reported_not_raised(workspace):
    """A hand-edited cursor can be valid JSON of the wrong shape, which
    constructs without complaint and only fails when it is read from."""
    write_document(workspace, "doc", sections=2, covered=[1])
    workspace.cursor_file("doc").write_text(json.dumps({"covered": 5}))
    item = home.sources(workspace)["items"][0]
    assert item["covered"] is None
    assert "cursor.json" in item["problem"]


def test_an_unreadable_sources_directory_is_reported_not_raised(workspace):
    workspace.sources_dir().write_text("a file, not a directory")
    listing = home.sources(workspace)
    assert listing["items"] == []
    assert "sources" in listing["problem"]


# --- the home page -----------------------------------------------------------


def test_a_bare_root_renders_every_list_empty(workspace):
    html = home.home_page(workspace)
    for line in (
        "No pad has been rendered.",
        "No kept notes.",
        "No cheat sheets.",
        "No sources.",
    ):
        assert line in html


def test_the_home_page_links_each_kind(workspace):
    workspace.pad_dir().mkdir()
    workspace.pad_file().write_text(render_html([], title="Scratch"))
    write_note(workspace, "clt", title="The CLT")
    workspace.config_file().write_text("deck: Fundamentals of Statistics\n")
    write_sheet(
        workspace,
        "fundamentals-of-statistics",
        [Formula(id="f-0001", tex="x", label="One", state="approved")],
    )
    write_document(workspace, "stats-ch1", sections=3, covered=[1, 2])
    write_problem_set(workspace, "pset-1", [("1. Setup", [1, 3], None)])

    html = home.home_page(workspace)

    assert '<a href="pad.html">Scratch</a>' in html
    assert '<a href="notes/clt.html">The CLT</a>' in html
    assert (
        '<a href="cheatsheets/fundamentals-of-statistics.html">'
        "Fundamentals of Statistics</a>"
    ) in html
    assert "1 formula</span>" in html
    assert "document · 2 of 3 sections" in html
    assert '<a href="/problems/pset-1">pset-1</a>' in html
    assert "problem set · 0 of 1 sections" in html


def test_the_home_page_orders_its_sections(workspace):
    html = home.home_page(workspace)
    positions = [
        html.index(h) for h in ("Current pad", "Kept notes", "Cheat sheets", "Sources")
    ]
    assert positions == sorted(positions)


def test_a_problem_shows_on_the_page(workspace):
    write_document(workspace, "stats-ch1", sections=3, covered=[1])
    workspace.cursor_file("stats-ch1").write_text("not json")
    html = home.home_page(workspace)
    assert 'class="problem"' in html
    assert "cursor.json" in html


def test_a_title_is_escaped_on_the_page(workspace):
    write_note(workspace, "b", title="<b>bold</b>")
    html = home.home_page(workspace)
    assert "&lt;b&gt;bold&lt;/b&gt;" in html
    assert "<b>bold</b>" not in html


def test_the_home_page_does_not_link_to_itself(workspace):
    assert '<a href="/">' not in home.home_page(workspace)


def test_the_home_page_is_named_after_the_root(workspace):
    assert f"<h1>{workspace.root.name}</h1>" in home.home_page(workspace)


# --- the problem reader ------------------------------------------------------


def test_problems_page_shows_each_tab_in_order(workspace):
    write_problem_set(
        workspace,
        "pset-1",
        [
            ("1. Setup", [1, 3], None),
            ("2. Gone", [3, 3], "unit page answered 404"),
            ("3. More", [3, 4], None),
        ],
    )
    html = home.problems_page("pset-1", workspace)

    assert html.index("1. Setup") < html.index("2. Gone") < html.index("3. More")
    assert '<img src="/sources/pset-1/pages/page-001.png" alt="page 1">' in html
    assert "page-002.png" in html
    assert "page-003.png" in html
    assert "page-004.png" not in html
    assert "unit page answered 404" in html
    assert 'class="reader"' in html
    assert "<title>pset-1</title>" in html


def test_problems_page_links_home(workspace):
    write_problem_set(workspace, "pset-1", [("1. Setup", [1, 2], None)])
    assert '<a href="/">' in home.problems_page("pset-1", workspace)


def test_problems_page_for_an_unknown_slug_raises(workspace):
    with pytest.raises(KeyError):
        home.problems_page("nope", workspace)


def test_a_document_is_not_a_problem_set(workspace):
    write_document(workspace, "doc", sections=1, covered=[])
    with pytest.raises(KeyError):
        home.problems_page("doc", workspace)


def test_an_unreadable_manifest_renders_the_reason(workspace):
    workspace.ensure_source_dirs("bad")
    workspace.source_manifest("bad").write_text("not json")
    html = home.problems_page("bad", workspace)
    assert "not a readable source manifest" in html
    assert "<img" not in html


def test_a_manifest_missing_its_units_renders_the_reason(workspace):
    workspace.ensure_source_dirs("bad")
    workspace.source_manifest("bad").write_text(json.dumps({"url": "u"}))
    html = home.problems_page("bad", workspace)
    assert "not a readable source manifest" in html


def test_a_tab_title_is_escaped(workspace):
    write_problem_set(workspace, "p", [("<script>x</script>", [1, 2], None)])
    html = home.problems_page("p", workspace)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html
