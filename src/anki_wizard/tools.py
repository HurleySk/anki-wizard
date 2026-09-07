"""The six tools a Claude agent calls.

Each returns a plain dict with no dependency on the calling conversation, so an
MCP server can wrap these functions unchanged.
"""

import shutil
from dataclasses import asdict
from pathlib import Path

from anki_wizard.cursor import load_cursor, next_section, save_cursor
from anki_wizard.outline import build_outline, load_outline, save_outline
from anki_wizard.paths import Paths
from anki_wizard.pdf import extract_text, render_pages

DEFAULT_MAX_PAGES_PER_READ = 10

TEXT_LAYER_WARNING = (
    "Read the page image for all mathematical content. The extracted text is a "
    "lossy hint only: it mangles LaTeX list markers and displayed equations."
)


def _require_outline(slug: str, paths: Paths):
    path = paths.outline_file(slug)
    if not path.exists():
        raise FileNotFoundError(f"source {slug!r} is not ingested; run ingest_source")
    return load_outline(path)


def ingest_source(pdf: Path, slug: str, paths: Paths, dpi: int = 150) -> dict:
    """Render pages, extract text, build the section map, initialise the cursor.

    Safe to re-run: pages already rendered are skipped, which is what makes an
    interrupted ingest resumable.
    """
    paths.ensure_source_dirs(slug)

    stored_pdf = paths.source_pdf(slug)
    if not stored_pdf.exists():
        shutil.copy2(pdf, stored_pdf)

    render_pages(stored_pdf, paths.pages_dir(slug), dpi=dpi)

    outline = build_outline(stored_pdf, slug=slug)
    save_outline(paths.outline_file(slug), outline)

    for page in range(1, outline.pages + 1):
        text = extract_text(stored_pdf, page)
        if text.strip():
            paths.page_text(slug, page).write_text(text)

    cursor_path = paths.cursor_file(slug)
    if not cursor_path.exists():
        save_cursor(cursor_path, load_cursor(cursor_path))

    return {
        "slug": slug,
        "pages": outline.pages,
        "structure": outline.structure,
        "sections": [asdict(s) for s in outline.sections],
    }


def get_progress(slug: str, paths: Paths) -> dict:
    outline = _require_outline(slug, paths)
    cursor = load_cursor(paths.cursor_file(slug))
    upcoming = next_section(outline, cursor)
    return {
        "slug": slug,
        "structure": outline.structure,
        "position": cursor.position,
        "covered": cursor.covered,
        "remaining": len(outline.sections) - len(cursor.covered),
        "next": asdict(upcoming) if upcoming else None,
        "complete": upcoming is None,
    }


def read_section(
    slug: str,
    section_id: str | None,
    paths: Paths,
    max_pages: int = DEFAULT_MAX_PAGES_PER_READ,
) -> dict:
    """Return a section's page images and text for the agent to read.

    Passing section_id=None reads the next uncovered section.
    """
    outline = _require_outline(slug, paths)

    if section_id is None:
        section = next_section(outline, load_cursor(paths.cursor_file(slug)))
        if section is None:
            raise ValueError(f"source {slug!r} is fully covered")
    else:
        section = outline.section(section_id)
        if section is None:
            raise ValueError(f"no section {section_id!r} in source {slug!r}")

    page_numbers = list(range(section.start, min(section.end, outline.pages + 1)))
    truncated = len(page_numbers) > max_pages
    pages = []
    for number in page_numbers[:max_pages]:
        text_file = paths.page_text(slug, number)
        pages.append(
            {
                "number": number,
                "image": str(paths.page_image(slug, number)),
                "text": text_file.read_text() if text_file.exists() else "",
            }
        )

    return {
        "slug": slug,
        "section": asdict(section),
        "pages": pages,
        "truncated": truncated,
        "note": TEXT_LAYER_WARNING,
    }
