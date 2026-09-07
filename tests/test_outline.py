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


def test_detect_slides_rejects_dense_prose_pages():
    """Prose whose first lines happen to be short is still not a slide deck.

    Without a density check this misclassifies: the lines below are distinct,
    non-empty, and under the title-word limit, so only page density rejects them.
    """
    pages = [
        "The quick brown fox jumps over the lazy dog and\n" + "filler words here " * 60,
        "then runs far away into the deep green forest\n" + "more filler words " * 60,
    ]
    assert detect_slides(pages) is None


def test_detect_slides_accepts_deck_with_repeated_and_dense_slides():
    """A real lecture deck repeats titles across consecutive slides.

    Modelled on the MITx 18.6501x deck this harness was designed against, where
    "Probability" and "The kiss" each title several slides in a row and two of
    47 pages run long. Rejecting on any repeat or any dense page sent that deck
    to the bare-page fallback, which is what these thresholds exist to prevent.
    """
    pages = [f"Slide {n}\nbullet text" for n in range(20)]
    pages += ["The kiss\nbullet text"] * 3
    pages += ["Probability\nbullet text"] * 2
    pages += ["Dense slide\n" + "word " * 150]
    assert detect_slides(pages) is not None


def test_detect_slides_rejects_running_header_prose():
    """Near-total title repetition is a running header, not a deck."""
    assert detect_slides(["Chapter 1\nbody text"] * 10) is None


def test_detect_slides_rejects_empty_page_list():
    assert detect_slides([]) is None


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
