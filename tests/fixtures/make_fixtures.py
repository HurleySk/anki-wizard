"""Generates the small PDF fixtures used by the ingest tests.

Run: uv run python tests/fixtures/make_fixtures.py
Requires: a LaTeX-free path -- these are built with reportlab, added as a dev dep.
"""

from pathlib import Path

from pypdf import PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

HERE = Path(__file__).parent


def _text_pdf(path: Path, pages: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    for body in pages:
        for i, line in enumerate(body.split("\n")):
            c.drawString(72, 720 - i * 18, line)
        c.showPage()
    c.save()


def make_outlined() -> None:
    """A PDF with an embedded outline: exercises the primary structure path."""
    path = HERE / "outlined.pdf"
    _text_pdf(
        path,
        [
            "Chapter 1\nIntroduction",
            "1.1 First Section\nBody text here.",
            "1.2 Second Section\nMore body text.",
            "Chapter 2\nAdvanced",
            "2.1 Third Section\nFinal body text.",
        ],
    )
    writer = PdfWriter(clone_from=str(path))
    writer.add_outline_item("1.1 First Section", 1)
    writer.add_outline_item("1.2 Second Section", 2)
    writer.add_outline_item("2.1 Third Section", 4)
    with open(path, "wb") as fh:
        writer.write(fh)


def make_slides() -> None:
    """A slide deck: no outline, one titled unit per page, page-number footers.

    Modelled on the MITx 18.6501x chapter 1 lecture slides, the first real
    document this harness was designed against.
    """
    _text_pdf(
        HERE / "slides.pdf",
        [
            "Introduction and probability\nWhat is statistics?\n\n1/4",
            "Statistics and modeling\nDice are a well known random process.\n\n2/4",
            "Probability vs statistics\nProbability deduces outcomes.\n\n3/4",
            "Linear regression\nEstimating parameters from data.\n\n4/4",
        ],
    )


def make_unstructured() -> None:
    """No outline and no per-page titles: falls back to structure=pages."""
    _text_pdf(
        HERE / "unstructured.pdf",
        ["continuous prose " * 30, "more continuous prose " * 30],
    )


def make_scanned() -> None:
    """No text layer at all: every page is an image."""
    path = HERE / "scanned.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    for _ in range(2):
        c.rect(72, 600, 400, 100, fill=0)
        c.showPage()
    c.save()


if __name__ == "__main__":
    make_outlined()
    make_slides()
    make_unstructured()
    make_scanned()
    print("fixtures written to", HERE)
