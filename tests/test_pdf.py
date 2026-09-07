from pathlib import Path

import pytest

from anki_wizard.pdf import extract_text, page_count, render_pages

FIXTURES = Path(__file__).parent / "fixtures"


def test_page_count():
    assert page_count(FIXTURES / "outlined.pdf") == 5
    assert page_count(FIXTURES / "slides.pdf") == 4


def test_extract_text_returns_page_text():
    text = extract_text(FIXTURES / "slides.pdf", 1)
    assert "Introduction and probability" in text


def test_extract_text_empty_for_scanned():
    assert extract_text(FIXTURES / "scanned.pdf", 1).strip() == ""


def test_render_pages_writes_images(tmp_path):
    written = render_pages(FIXTURES / "slides.pdf", tmp_path, dpi=50)
    assert len(written) == 4
    assert all(p.exists() and p.stat().st_size > 0 for p in written)
    assert written[0].name == "page-001.png"


def test_render_pages_skips_existing(tmp_path):
    render_pages(FIXTURES / "slides.pdf", tmp_path, dpi=50)
    first = tmp_path / "page-001.png"
    first.unlink()
    written = render_pages(FIXTURES / "slides.pdf", tmp_path, dpi=50)
    assert first.exists()
    assert len(written) == 4


def test_render_pages_rejects_missing_pdf(tmp_path):
    with pytest.raises(FileNotFoundError):
        render_pages(tmp_path / "nope.pdf", tmp_path)
