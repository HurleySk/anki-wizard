from pathlib import Path

import pytest

from anki_wizard.pdf import extract_text, page_count, render_page

FIXTURES = Path(__file__).parent / "fixtures"


def test_page_count():
    assert page_count(FIXTURES / "outlined.pdf") == 5
    assert page_count(FIXTURES / "slides.pdf") == 4


def test_extract_text_returns_page_text():
    text = extract_text(FIXTURES / "slides.pdf", 1)
    assert "Introduction and probability" in text


def test_extract_text_empty_for_scanned():
    assert extract_text(FIXTURES / "scanned.pdf", 1).strip() == ""


def test_render_page_writes_an_image(tmp_path):
    target = tmp_path / "page-001.png"
    written = render_page(FIXTURES / "slides.pdf", 1, target, dpi=50)
    assert written == target
    assert target.exists() and target.stat().st_size > 0


def test_render_page_creates_missing_parents(tmp_path):
    target = tmp_path / "pages" / "page-002.png"
    render_page(FIXTURES / "slides.pdf", 2, target, dpi=50)
    assert target.exists()


def test_render_page_skips_existing(tmp_path):
    target = tmp_path / "page-001.png"
    target.write_bytes(b"already here")
    render_page(FIXTURES / "slides.pdf", 1, target, dpi=50)
    assert target.read_bytes() == b"already here"


def test_render_page_rejects_missing_pdf(tmp_path):
    with pytest.raises(FileNotFoundError):
        render_page(tmp_path / "nope.pdf", 1, tmp_path / "page-001.png")
