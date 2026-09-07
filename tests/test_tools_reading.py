from pathlib import Path

import pytest

from anki_wizard.paths import Paths
from anki_wizard.tools import get_progress, ingest_source, read_section

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workspace(tmp_path):
    return Paths(root=tmp_path)


def test_ingest_reports_structure_and_pages(workspace):
    result = ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    assert result["slug"] == "slides"
    assert result["pages"] == 4
    assert result["structure"] == "slides"
    assert len(result["sections"]) == 4
    assert result["sections"][0]["title"] == "Introduction and probability"


def test_ingest_writes_state_files(workspace):
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    assert workspace.outline_file("slides").exists()
    assert workspace.cursor_file("slides").exists()
    assert workspace.source_pdf("slides").exists()
    assert workspace.page_image("slides", 1).exists()
    assert workspace.page_text("slides", 1).exists()


def test_ingest_is_resumable(workspace):
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    workspace.page_image("slides", 2).unlink()
    workspace.page_image("slides", 3).unlink()
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    assert workspace.page_image("slides", 2).exists()
    assert workspace.page_image("slides", 3).exists()


def test_ingest_skips_text_file_for_scanned_page(workspace):
    """Pages with no text layer get no text file rather than an empty one."""
    ingest_source(FIXTURES / "scanned.pdf", slug="scanned", paths=workspace, dpi=50)
    assert workspace.page_image("scanned", 1).exists()
    assert not workspace.page_text("scanned", 1).exists()


def test_progress_on_fresh_source(workspace):
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    p = get_progress("slides", paths=workspace)
    assert p["covered"] == []
    assert p["remaining"] == 4
    assert p["next"]["id"] == "1"
    assert p["next"]["title"] == "Introduction and probability"
    assert p["complete"] is False


def test_progress_unknown_source_raises(workspace):
    with pytest.raises(FileNotFoundError, match="not ingested"):
        get_progress("nope", paths=workspace)


def test_read_section_returns_images_and_text(workspace):
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    result = read_section("slides", "2", paths=workspace)
    assert result["section"]["title"] == "Statistics and modeling"
    assert len(result["pages"]) == 1
    page = result["pages"][0]
    assert page["number"] == 2
    assert page["image"].endswith("page-002.png")
    assert "Statistics and modeling" in page["text"]


def test_read_section_defaults_to_next_uncovered(workspace):
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    result = read_section("slides", None, paths=workspace)
    assert result["section"]["id"] == "1"


def test_read_section_honours_page_cap(workspace):
    ingest_source(FIXTURES / "outlined.pdf", slug="outlined", paths=workspace, dpi=50)
    result = read_section("outlined", "1.2", paths=workspace, max_pages=1)
    assert len(result["pages"]) == 1
    assert result["truncated"] is True


def test_read_section_unknown_id_raises(workspace):
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    with pytest.raises(ValueError, match="no section"):
        read_section("slides", "99", paths=workspace)


def test_read_section_warns_text_layer_is_unreliable(workspace):
    """Every read carries the warning, so a card is never built from text alone."""
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    result = read_section("slides", "1", paths=workspace)
    assert "image" in result["note"].lower()
