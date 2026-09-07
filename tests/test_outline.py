import json
from pathlib import Path

from anki_wizard.models import Outline, Section
from anki_wizard.outline import (
    build_outline,
    detect_slides,
    load_outline,
    save_outline,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_embedded_outline_is_preferred():
    o = build_outline(FIXTURES / "outlined.pdf", slug="outlined")
    assert o.structure == "sections"
    assert [s.id for s in o.sections] == ["1.1", "1.2", "2.1"]
    assert o.sections[0].title == "First Section"


def test_embedded_outline_page_ranges_are_contiguous():
    o = build_outline(FIXTURES / "outlined.pdf", slug="outlined")
    assert o.sections[0].pages == [2, 3]
    assert o.sections[1].pages == [3, 5]
    assert o.sections[2].pages == [5, 6]


def test_slide_deck_detected_when_no_outline():
    o = build_outline(FIXTURES / "slides.pdf", slug="slides")
    assert o.structure == "slides"
    assert len(o.sections) == 4
    assert o.sections[0].id == "1"
    assert o.sections[0].title == "Introduction and probability"
    assert o.sections[0].pages == [1, 2]


def test_unstructured_falls_back_to_pages():
    o = build_outline(FIXTURES / "unstructured.pdf", slug="unstructured")
    assert o.structure == "pages"
    assert len(o.sections) == 2
    assert o.sections[0].id == "1"
    assert o.sections[0].title == "Page 1"


def test_scanned_falls_back_to_pages():
    """No text layer means no titles to detect, so pages is the only option."""
    o = build_outline(FIXTURES / "scanned.pdf", slug="scanned")
    assert o.structure == "pages"
    assert len(o.sections) == 2


def test_detect_slides_accepts_short_distinct_titles():
    pages = [
        "Introduction and probability\nbody\n1/3",
        "Statistics and modeling\nbody\n2/3",
        "Linear regression\nbody\n3/3",
    ]
    assert detect_slides(pages) == [
        "Introduction and probability",
        "Statistics and modeling",
        "Linear regression",
    ]


def test_detect_slides_rejects_long_first_lines():
    pages = ["x " * 60, "y " * 60]
    assert detect_slides(pages) is None


def test_detect_slides_rejects_repeated_titles():
    """A repeated running header is not a slide title."""
    pages = ["Chapter 1\nbody", "Chapter 1\nbody", "Chapter 1\nbody"]
    assert detect_slides(pages) is None


def test_detect_slides_rejects_empty_pages():
    assert detect_slides(["", ""]) is None


def test_outline_round_trips_through_disk(tmp_path):
    o = Outline(
        slug="doc",
        pages=2,
        structure="slides",
        sections=[Section(id="1", title="A", pages=[1, 2])],
    )
    p = tmp_path / "outline.json"
    save_outline(p, o)
    assert load_outline(p) == o
