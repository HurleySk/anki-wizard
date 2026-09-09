import pytest

from anki_wizard.atomic import locked
from anki_wizard.cursor import advance, load_cursor, next_section, save_cursor
from anki_wizard.models import Cursor, Outline, Section


def outline_of(*ids: str) -> Outline:
    return Outline(
        slug="doc",
        pages=100,
        structure="sections",
        sections=[
            Section(id=i, title=f"Section {i}", pages=[n, n + 1])
            for n, i in enumerate(ids, start=1)
        ],
    )


def test_next_section_on_fresh_cursor_is_first():
    o = outline_of("1.1", "1.2", "2.1")
    assert next_section(o, Cursor()).id == "1.1"


def test_next_section_skips_covered():
    o = outline_of("1.1", "1.2", "2.1")
    c = Cursor(position="1.1", covered=["1.1"])
    assert next_section(o, c).id == "1.2"


def test_next_section_returns_first_uncovered_not_after_position():
    """A skipped section is returned before later ones, even though the
    cursor position has already moved past it."""
    o = outline_of("1.1", "1.2", "2.1")
    c = Cursor(position="2.1", covered=["1.1", "2.1"])
    assert next_section(o, c).id == "1.2"


def test_next_section_none_when_all_covered():
    o = outline_of("1.1", "1.2")
    c = Cursor(position="1.2", covered=["1.1", "1.2"])
    assert next_section(o, c) is None


def test_advance_marks_covered_and_sets_position():
    o = outline_of("1.1", "1.2")
    c = advance(o, Cursor(), "1.1")
    assert c.position == "1.1"
    assert c.covered == ["1.1"]
    assert c.updated is not None


def test_advance_is_idempotent():
    o = outline_of("1.1", "1.2")
    c = advance(o, Cursor(), "1.1")
    c = advance(o, c, "1.1")
    assert c.covered == ["1.1"]


def test_advance_rejects_unknown_section():
    o = outline_of("1.1")
    with pytest.raises(ValueError, match="not in outline"):
        advance(o, Cursor(), "9.9")


def test_cursor_round_trips_through_disk(tmp_path):
    p = tmp_path / "cursor.json"
    c = Cursor(position="1.2", covered=["1.1", "1.2"], updated="2026-09-07T00:00:00Z")
    save_cursor(p, c)
    assert load_cursor(p) == c


def test_load_cursor_missing_file_is_empty(tmp_path):
    assert load_cursor(tmp_path / "nope.json") == Cursor()


def test_malformed_cursor_names_the_file(tmp_path):
    """cursor.json is meant to be inspectable, so it gets hand-edited."""
    path = tmp_path / "cursor.json"
    path.write_text('{"position": "1", "bogus_key": 3}')
    with pytest.raises(ValueError, match="not a readable cursor file"):
        load_cursor(path)


def test_cursor_file_that_is_not_json_names_the_file(tmp_path):
    path = tmp_path / "cursor.json"
    path.write_text("not json at all")
    with pytest.raises(ValueError, match="not a readable cursor file"):
        load_cursor(path)


def test_concurrent_covers_do_not_lose_each_other(tmp_path):
    """The cursor loses updates the same way the ledger does.

    Two callers covering different sections each load the same cursor and write
    back their own view, so without a lock one section's coverage vanishes.
    """
    import threading

    path = tmp_path / "cursor.json"
    outline = outline_of("1.1", "1.2")
    save_cursor(path, Cursor())
    start = threading.Barrier(2)

    def cover(section_id: str) -> None:
        start.wait()
        with locked(path):
            save_cursor(path, advance(outline, load_cursor(path), section_id))

    workers = [threading.Thread(target=cover, args=(s,)) for s in ("1.1", "1.2")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)

    assert sorted(load_cursor(path).covered) == ["1.1", "1.2"]
