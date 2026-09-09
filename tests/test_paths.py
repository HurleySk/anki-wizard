import pytest

from anki_wizard.paths import Paths


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
