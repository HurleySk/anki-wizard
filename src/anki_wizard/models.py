"""Data models. Plain containers with no I/O and no business logic."""

from dataclasses import dataclass, field
from typing import Literal

CardState = Literal["proposed", "approved", "rejected", "pushed", "orphaned"]
FormulaState = Literal["proposed", "approved", "rejected"]
Structure = Literal["sections", "slides", "pages"]


@dataclass
class CardSource:
    """Where a card came from.

    Cards generated in conversation rather than from a document leave section
    and pages empty. Their slug names the topic they came from -- "conversation"
    by convention, or something narrower like "pset-3" to keep them findable.
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
    why: str | None = None
    # The subdeck this card belongs to, relative to the configured deck. Held
    # per card rather than per source so one document can span several lectures
    # and one lecture can gather cards from several documents -- including
    # conversation cards, which have no document to inherit from.
    lecture: str | None = None
    state: CardState = "proposed"
    tags: list[str] = field(default_factory=list)
    anki_note_id: int | None = None
    history: list[dict] = field(default_factory=list)


@dataclass
class Formula:
    """One entry on a course's cheat sheet.

    `tex` is bare TeX, displayed by the renderer; `label` and `note` are prose
    in the pad's sense, plain text with math only inside \\(...\\). The note is
    for the condition a formula needs, which is the part that gets missed.
    Approved is the terminal good state -- there is no push, the sheet is the
    destination -- and rejecting an approved entry is how it leaves the sheet.
    """

    id: str
    tex: str
    label: str
    note: str | None = None
    lecture: str | None = None
    tags: list[str] = field(default_factory=list)
    source: CardSource | None = None
    state: FormulaState = "proposed"
    history: list[dict] = field(default_factory=list)


@dataclass
class AdoptedNote:
    """A note this harness did not create, tracked so edits leave a trail.

    Holds a reference and never content. The fields list names the note's real
    fields so an edit can be checked against them before it is sent; the values
    stay in Anki, which is what keeps this entry from going stale.
    """

    note_id: int
    model: str
    deck: str
    fields: list[str]
    tags: list[str] = field(default_factory=list)
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

    def page_numbers(self, section: Section) -> list[int]:
        """The pages a section spans, clamped to the document.

        Outlines are hand-editable, so a section can claim pages past the end.
        """
        return list(range(section.start, min(section.end, self.pages + 1)))


@dataclass
class Cursor:
    """Progress through a document.

    `skipped` maps a section id to why it was passed over. Coverage is otherwise
    derived from cards, so a section that yields none -- a title slide, a divider
    -- could never settle; recording the reason keeps that judgment auditable
    rather than indistinguishable from lost work.
    """

    position: str | None = None
    covered: list[str] = field(default_factory=list)
    updated: str | None = None
    skipped: dict[str, str] = field(default_factory=dict)
