"""Resolves every on-disk path from a source slug.

This is the single source of truth for the state directory layout. No other
module should construct paths by string concatenation.
"""

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
        return self.root / "cards" / f"{slug}.yaml"

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
