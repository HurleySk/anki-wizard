"""Builds a section map for a document.

Fallback chain, in order:
  1. The PDF's embedded outline (most typeset textbooks have one).
  2. Slide detection: one titled unit per page, for presentation decks.
  3. Bare page numbers, the degenerate case.
"""

import json
import re
from dataclasses import asdict
from pathlib import Path

from pypdf import PdfReader

from anki_wizard.models import Outline, Section
from anki_wizard.pdf import extract_text, page_count

# A section id like "1.1" or "2" leading the outline title, which we split off
# so the id and the human title are separate fields.
_ID_PREFIX = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+(.*)$")

MAX_SLIDE_TITLE_WORDS = 12

# A slide holds a title and a few bullets; a prose page is a wall of text. Page
# density separates the two far more reliably than title length alone, which a
# prose document can pass by chance when its lines happen to wrap short. Real
# decks do carry the occasional dense slide, so judge the deck by its typical
# page rather than rejecting on any single one.
MAX_SLIDE_PAGE_WORDS = 120

# A real lecture deck continues a topic over consecutive slides, so repeated
# titles are normal. A running header on a prose document is different in
# degree: nearly every page repeats. Only near-total repetition means prose.
MIN_DISTINCT_TITLE_RATIO = 0.5


def _embedded_sections(pdf: Path, total: int) -> list[Section] | None:
    """Read the PDF's own outline, if it has usable entries."""
    reader = PdfReader(str(pdf))
    try:
        raw = reader.outline
    except Exception:
        return None
    if not raw:
        return None

    found: list[tuple[str, int]] = []

    def walk(items) -> None:
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            try:
                page = reader.get_destination_page_number(item) + 1
            except Exception:
                continue
            found.append((str(item.title), page))

    walk(raw)
    if not found:
        return None

    found.sort(key=lambda pair: pair[1])
    sections: list[Section] = []
    for index, (title, start) in enumerate(found):
        end = found[index + 1][1] if index + 1 < len(found) else total + 1
        match = _ID_PREFIX.match(title)
        if match:
            section_id, clean_title = match.group(1), match.group(2).strip()
        else:
            section_id, clean_title = str(index + 1), title.strip()
        sections.append(Section(id=section_id, title=clean_title, pages=[start, end]))
    return sections


def detect_slides(page_texts: list[str]) -> list[str] | None:
    """Return per-page slide titles, or None if this is not a slide deck.

    A slide deck has a short, distinct title as the first line of every page,
    and pages that are sparse rather than dense. Repeated first lines mean a
    running header on a prose document, not slides; a page dense with text means
    prose even when its first line happens to be short.
    """
    if not page_texts:
        return None
    titles: list[str] = []
    dense_pages = 0
    for text in page_texts:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return None
        if len(text.split()) > MAX_SLIDE_PAGE_WORDS:
            dense_pages += 1
        title = lines[0]
        if len(title.split()) > MAX_SLIDE_TITLE_WORDS:
            return None
        titles.append(title)
    if dense_pages * 2 > len(page_texts):
        return None
    if len(set(titles)) < len(titles) * MIN_DISTINCT_TITLE_RATIO:
        return None
    return titles


def build_outline(pdf: Path, slug: str) -> Outline:
    total = page_count(pdf)

    sections = _embedded_sections(pdf, total)
    if sections:
        return Outline(slug=slug, pages=total, structure="sections", sections=sections)

    page_texts = [extract_text(pdf, page) for page in range(1, total + 1)]
    titles = detect_slides(page_texts)
    if titles:
        return Outline(
            slug=slug,
            pages=total,
            structure="slides",
            sections=[
                Section(id=str(n), title=title, pages=[n, n + 1])
                for n, title in enumerate(titles, start=1)
            ],
        )

    return Outline(
        slug=slug,
        pages=total,
        structure="pages",
        sections=[
            Section(id=str(n), title=f"Page {n}", pages=[n, n + 1])
            for n in range(1, total + 1)
        ],
    )


def load_outline(path: Path) -> Outline:
    raw = json.loads(path.read_text())
    return Outline(
        slug=raw["slug"],
        pages=raw["pages"],
        structure=raw["structure"],
        sections=[Section(**s) for s in raw["sections"]],
    )


def save_outline(path: Path, outline: Outline) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(outline), indent=2))
