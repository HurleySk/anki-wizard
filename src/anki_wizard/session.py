"""Binds config, paths, and an Anki client together.

The tool functions take explicit arguments so they stay easy to test and easy
for an MCP server to wrap. Session is the convenience layer that reads
config.yaml once and supplies those arguments.
"""

from pathlib import Path

from anki_wizard import cheatsheet, collection, tools
from anki_wizard.anki import AnkiClient
from anki_wizard.config import load_config
from anki_wizard.paths import Paths


class Session:
    def __init__(self, root: Path):
        self.paths = Paths(root=Path(root))
        self.config = load_config(self.paths.config_file())
        self.client = AnkiClient(self.config.anki_connect_url)

    def ingest(self, pdf: Path, slug: str, dpi: int = 150) -> dict:
        return tools.ingest_source(pdf, slug=slug, paths=self.paths, dpi=dpi)

    def progress(self, slug: str) -> dict:
        return tools.get_progress(slug, paths=self.paths)

    def read(self, slug: str, section_id: str | None = None) -> dict:
        return tools.read_section(
            slug,
            section_id,
            paths=self.paths,
            max_pages=self.config.max_pages_per_read,
        )

    def propose(
        self,
        slug: str,
        proposals: list[dict],
        section_id: str | None = None,
        lecture: str | None = None,
    ) -> dict:
        """Propose cards, optionally assigning them all to one lecture.

        A lecture on a proposal wins over the batch argument, so a batch that
        straddles a lecture boundary can still be sent in one call.
        """
        if lecture is not None:
            proposals = [{"lecture": lecture, **p} for p in proposals]
        return tools.propose_cards(
            slug,
            proposals,
            section_id=section_id,
            paths=self.paths,
            default_tags=self.config.default_tags,
        )

    def skip(self, slug: str, section_id: str, reason: str) -> dict:
        return tools.skip_section(
            slug, section_id, reason=reason, paths=self.paths
        )

    def review(self, slug: str, decisions: dict) -> dict:
        return tools.review_cards(slug, decisions, paths=self.paths)

    def push(self, slug: str) -> dict:
        return tools.push_to_anki(
            slug, self.client, deck=self.config.deck, paths=self.paths
        )

    def pad(
        self, blocks: list[dict], viewer: str | None = None, title: str = "Study pad"
    ) -> dict:
        return tools.render_pad(
            blocks,
            paths=self.paths,
            viewer=viewer or self.config.pad_viewer,
            title=title,
            server_timeout_minutes=self.config.pad_server_timeout_minutes,
        )

    def keep(self, name: str) -> dict:
        return tools.promote_pad(name, paths=self.paths)

    def revise(self, slug: str, card_id: str, **edits) -> dict:
        return tools.revise_card(
            slug, card_id, self.client, paths=self.paths, deck=self.config.deck, **edits
        )

    def search(self, query: str, limit: int = 25) -> dict:
        return collection.search_collection(query, self.client, limit=limit)

    def note(self, note_id: int) -> dict:
        return collection.read_note(note_id, self.client)

    def decks(self) -> dict:
        return collection.list_decks(self.client)

    def pad_note(self, note_id: int, extra: list[dict] | None = None) -> dict:
        """Render a note on the pad, optionally followed by blocks of your own.

        The card and the working-through belong on one page: the note is what
        the question is about, and the derivation beside it is the answer.
        """
        blocks = collection.note_blocks(note_id, self.client)
        return self.pad(blocks + list(extra or []))

    def pad_cards(
        self,
        slug: str,
        ids: list[str] | None = None,
        state: str | None = "proposed",
        extra: list[dict] | None = None,
    ) -> dict:
        """Put ledger cards on the pad for review, proposals by default.

        The counterpart of pad_note for cards this harness wrote. Use it
        rather than assembling front and back out of prose blocks: the fields
        are HTML and only the note renderer shows them as the card will look.
        """
        blocks = tools.card_blocks(slug, paths=self.paths, ids=ids, state=state)
        return self.pad(blocks + list(extra or []), title=f"Cards: {slug}")

    def propose_formulas(
        self,
        proposals: list[dict],
        slug: str | None = None,
        section_id: str | None = None,
        lecture: str | None = None,
    ) -> dict:
        """Propose cheat sheet formulas for the configured course.

        Same lecture precedence as propose: a lecture on a proposal wins over
        the batch argument.
        """
        if lecture is not None:
            proposals = [{"lecture": lecture, **p} for p in proposals]
        return cheatsheet.propose_formulas(
            self.config.deck,
            proposals,
            paths=self.paths,
            slug=slug,
            section_id=section_id,
            default_tags=self.config.default_tags,
        )

    def review_formulas(self, decisions: dict) -> dict:
        return cheatsheet.review_formulas(self.config.deck, decisions, paths=self.paths)

    def revise_formula(self, formula_id: str, **edits) -> dict:
        return cheatsheet.revise_formula(
            self.config.deck, formula_id, paths=self.paths, **edits
        )

    def pad_formulas(
        self,
        ids: list[str] | None = None,
        state: str | None = "proposed",
        extra: list[dict] | None = None,
    ) -> dict:
        """Put cheat sheet entries on the pad for review, proposals by default."""
        blocks = cheatsheet.formula_blocks(
            self.config.deck, paths=self.paths, ids=ids, state=state
        )
        return self.pad(
            blocks + list(extra or []), title=f"Formulas: {self.config.deck}"
        )

    def cheatsheet(self) -> dict:
        """Rebuild the course's printable sheet and return where to read it."""
        return cheatsheet.render_cheatsheet(
            self.config.deck,
            paths=self.paths,
            viewer=self.config.pad_viewer,
            server_timeout_minutes=self.config.pad_server_timeout_minutes,
        )

    def edit_note(self, note_id: int, changes: dict, force: bool = False) -> dict:
        return collection.edit_note(
            note_id, changes, self.client, paths=self.paths, force=force
        )
