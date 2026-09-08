"""Binds config, paths, and an Anki client together.

The tool functions take explicit arguments so they stay easy to test and easy
for an MCP server to wrap. Session is the convenience layer that reads
config.yaml once and supplies those arguments.
"""

from pathlib import Path

from anki_wizard import tools
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
        self, slug: str, proposals: list[dict], section_id: str | None = None
    ) -> dict:
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

    def revise(self, slug: str, card_id: str, **edits) -> dict:
        return tools.revise_card(
            slug, card_id, self.client, paths=self.paths, **edits
        )
