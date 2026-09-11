"""Resolves every on-disk path from a source slug.

This is the single source of truth for the state directory layout. No other
module should construct paths by string concatenation.
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Paths:
    root: Path

    def source_dir(self, slug: str) -> Path:
        return self.root / "sources" / slug

    def pages_dir(self, slug: str) -> Path:
        return self.source_dir(slug) / "pages"

    def text_dir(self, slug: str) -> Path:
        return self.source_dir(slug) / "text"

    def source_pdf(self, slug: str) -> Path:
        return self.source_dir(slug) / "source.pdf"

    def outline_file(self, slug: str) -> Path:
        return self.source_dir(slug) / "outline.json"

    def cursor_file(self, slug: str) -> Path:
        return self.source_dir(slug) / "cursor.json"

    def ledger_file(self, slug: str) -> Path:
        # Document slugs and deck slugs share this one flat namespace, and both
        # are lowercase-hyphenated, so a deck named "Stats Ch1" lands in the
        # same file as the PDF ingested as "stats-ch1". That is safe -- cards
        # key on id and adopted notes on note_id -- and usually wanted, since a
        # deck and the document it came from share a subject. No guard mirrors
        # note_file's because both slug sources are trusted: one is deck_slug
        # output, the other a name the user typed for their own ingest.
        return self.root / "cards" / f"{slug}.yaml"

    def cheatsheet_file(self, course_slug: str) -> Path:
        # Keyed on the course rather than a source: one sheet gathers formulas
        # from every document and conversation in a course. The slug comes
        # from deck_slug, so its charset already keeps it inside cheatsheets/.
        return self.root / "cheatsheets" / f"{course_slug}.yaml"

    def cheatsheet_page(self, course_slug: str) -> Path:
        # Under pad/ so the pad server, rooted there, serves it at a stable URL
        # the way it serves kept notes.
        return self.pad_dir() / "cheatsheets" / f"{course_slug}.html"

    def config_file(self) -> Path:
        return self.root / "config.yaml"

    def page_image(self, slug: str, page: int) -> Path:
        return self.pages_dir(slug) / f"page-{page:03d}.png"

    def page_text(self, slug: str, page: int) -> Path:
        return self.text_dir(slug) / f"page-{page:03d}.txt"

    def ensure_source_dirs(self, slug: str) -> None:
        self.pages_dir(slug).mkdir(parents=True, exist_ok=True)
        self.text_dir(slug).mkdir(parents=True, exist_ok=True)
        self.ledger_file(slug).parent.mkdir(parents=True, exist_ok=True)

    def pad_dir(self) -> Path:
        return self.root / "pad"

    def pad_file(self) -> Path:
        return self.pad_dir() / "pad.html"

    def notes_dir(self) -> Path:
        return self.pad_dir() / "notes"

    def note_file(self, name: str) -> Path:
        # The name arrives from a conversation, so a separator or a dot segment
        # would escape the notes directory entirely.
        if not name or "/" in name or "\\" in name or name in (".", ".."):
            raise ValueError(f"note name must be a single path segment: {name!r}")
        return self.notes_dir() / f"{name}.html"


def deck_slug(deck: str) -> str:
    """A ledger slug for the course a deck belongs to.

    Only the top-level deck is used, so every note from a course lands in one
    ledger however deep its subdeck. Anki deck names are free text and this
    becomes a filename, so unusable characters are dropped -- and a name with
    nothing left is refused rather than silently naming an empty file. A deck
    titled wholly in a non-Latin script has nothing left, so it raises.
    """
    top = deck.split("::")[0]
    # The charset is what keeps the result inside cards/, not a separate check:
    # widen it and separators and dot segments come back.
    slug = re.sub(r"[^a-z0-9]+", "-", top.lower()).strip("-")
    if not slug:
        raise ValueError(f"deck name has no usable slug characters: {deck!r}")
    return slug
