"""Data models. Plain containers with no I/O and no business logic."""

from dataclasses import dataclass, field
from typing import Literal

CardState = Literal["proposed", "approved", "rejected", "pushed", "orphaned"]
Structure = Literal["sections", "slides", "pages"]


@dataclass
class CardSource:
    """Where a card came from.

    Cards generated in conversation rather than from a document use
    slug="conversation" and leave section and pages empty.
    """

    slug: str
    section: str | None = None
    pages: list[int] = field(default_factory=list)


@dataclass
class Card:
    id: str
    front: str
    back: str
    source: CardSource
    state: CardState = "proposed"
    tags: list[str] = field(default_factory=list)
    anki_note_id: int | None = None
    history: list[dict] = field(default_factory=list)


@dataclass
class Section:
    """A traversable unit of a document.

    `pages` is an inclusive start and exclusive end. For structure="slides"
    and structure="pages", a section spans exactly one page.
    """

    id: str
    title: str
    pages: list[int]

    @property
    def start(self) -> int:
        return self.pages[0]

    @property
    def end(self) -> int:
        return self.pages[1]


@dataclass
class Outline:
    slug: str
    pages: int
    structure: Structure
    sections: list[Section] = field(default_factory=list)

    def section(self, section_id: str) -> Section | None:
        for s in self.sections:
            if s.id == section_id:
                return s
        return None


@dataclass
class Cursor:
    position: str | None = None
    covered: list[str] = field(default_factory=list)
    updated: str | None = None
