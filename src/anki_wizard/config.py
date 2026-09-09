"""Configuration loading with defaults.

A missing or empty config.yaml is not an error: every field has a default that
works against a stock Anki install.
"""

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


@dataclass
class Config:
    anki_connect_url: str = "http://localhost:8765"
    deck: str = "anki-wizard"
    default_tags: list[str] = field(default_factory=list)
    max_pages_per_read: int = 10
    pad_viewer: str = "vscode"
    pad_server_timeout_minutes: float = 30.0


def load_config(path: Path) -> Config:
    if not path.exists():
        return Config()
    raw = yaml.safe_load(path.read_text()) or {}

    # Built from the dataclass rather than a hand-written mapping, so a new
    # field needs no line here and cannot be silently dropped.
    known = {f.name for f in fields(Config)}
    unknown = sorted(set(raw) - known)
    if unknown:
        # A misspelt key that does nothing leaves the user believing they
        # configured something, and the setting quietly keeps its default.
        raise ValueError(
            f"{path}: unknown setting(s) {', '.join(repr(k) for k in unknown)}. "
            f"Known settings: {', '.join(sorted(known))}."
        )
    return Config(**raw)
