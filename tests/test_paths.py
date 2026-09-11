from pathlib import Path

import pytest

from anki_wizard.paths import Paths, deck_slug


def test_paths_resolve_from_root(tmp_path):
    p = Paths(root=tmp_path)
    assert p.source_dir("folland") == tmp_path / "sources" / "folland"
    assert p.pages_dir("folland") == tmp_path / "sources" / "folland" / "pages"
    assert p.text_dir("folland") == tmp_path / "sources" / "folland" / "text"
    assert p.outline_file("folland") == tmp_path / "sources" / "folland" / "outline.json"
    assert p.cursor_file("folland") == tmp_path / "sources" / "folland" / "cursor.json"
    assert p.ledger_file("folland") == tmp_path / "cards" / "folland.yaml"
    assert p.config_file() == tmp_path / "config.yaml"


def test_page_image_is_zero_padded(tmp_path):
    p = Paths(root=tmp_path)
    assert p.page_image("folland", 7).name == "page-007.png"
    assert p.page_text("folland", 7).name == "page-007.txt"


def test_page_image_handles_four_digit_pages(tmp_path):
    p = Paths(root=tmp_path)
    assert p.page_image("folland", 1234).name == "page-1234.png"


def test_ensure_source_dirs_creates_tree(tmp_path):
    p = Paths(root=tmp_path)
    p.ensure_source_dirs("folland")
    assert p.pages_dir("folland").is_dir()
    assert p.text_dir("folland").is_dir()
    assert p.ledger_file("folland").parent.is_dir()


def test_pad_and_note_paths(tmp_path):
    p = Paths(root=tmp_path)
    assert p.pad_file() == tmp_path / "pad" / "pad.html"
    assert p.notes_dir() == tmp_path / "pad" / "notes"
    assert p.note_file("bernoulli-moments") == (
        tmp_path / "pad" / "notes" / "bernoulli-moments.html"
    )


def test_note_file_rejects_a_path_separator(tmp_path):
    """A note name is one path segment, never a traversal.

    The name reaches this from a conversation, so "../../etc/passwd" must not
    resolve outside the notes directory.
    """
    p = Paths(root=tmp_path)
    for bad in ("../escape", "nested/name", "/absolute", ".", ".."):
        with pytest.raises(ValueError, match="note name"):
            p.note_file(bad)


def test_deck_slug_uses_the_top_level_deck():
    """Adopted notes group by course, the way document cards group by document."""
    assert deck_slug("Intro to Probability") == "intro-to-probability"
    assert deck_slug("Intro to Probability::Unit I::L3 Independence") == (
        "intro-to-probability"
    )


def test_deck_slug_strips_punctuation_and_collapses_separators():
    assert deck_slug("6.041 Probabilistic Systems!") == "6-041-probabilistic-systems"
    assert deck_slug("A  --  B") == "a-b"


def test_deck_slug_rejects_a_name_with_nothing_usable():
    """A slug becomes a filename, so an empty one would write to cards/.yaml."""
    with pytest.raises(ValueError, match="usable"):
        deck_slug("::")


def test_cheatsheet_paths_are_per_course():
    """The sheet is course state, so it keys on the deck slug, not a source slug."""
    p = Paths(root=Path("/tmp/x"))
    assert p.cheatsheet_file("intro-to-probability") == Path(
        "/tmp/x/cheatsheets/intro-to-probability.yaml"
    )
    assert p.cheatsheet_page("intro-to-probability") == Path(
        "/tmp/x/pad/cheatsheets/intro-to-probability.html"
    )


def test_cheatsheet_page_lives_under_the_pad():
    """The pad server is rooted at pad/, so a page under it gets a stable URL."""
    p = Paths(root=Path("/tmp/x"))
    assert p.pad_dir() in p.cheatsheet_page("stats").parents
