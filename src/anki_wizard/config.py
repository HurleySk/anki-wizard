"""Configuration loading with defaults.

A missing or empty config.yaml is not an error: every field has a default that
works against a stock Anki install.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    anki_connect_url: str = "http://localhost:8765"
    deck: str = "anki-wizard"
    default_tags: list[str] = field(default_factory=list)
    max_pages_per_read: int = 10


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    raw = yaml.safe_load(path.read_text()) or {}
    defaults = Config()
    return Config(
        anki_connect_url=raw.get("anki_connect_url", defaults.anki_connect_url),
        deck=raw.get("deck", defaults.deck),
        default_tags=raw.get("default_tags", defaults.default_tags),
        max_pages_per_read=raw.get("max_pages_per_read", defaults.max_pages_per_read),
    )
