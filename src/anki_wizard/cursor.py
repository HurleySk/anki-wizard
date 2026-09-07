"""Progress tracking through a document.

The next section is the first in outline order that is not in `covered` --
deliberately not "the one after `position`". Sections get skipped and returned
to, so a high-water mark would lose work.
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from anki_wizard.models import Cursor, Outline, Section


def next_section(outline: Outline, cursor: Cursor) -> Section | None:
    for section in outline.sections:
        if section.id not in cursor.covered:
            return section
    return None


def advance(outline: Outline, cursor: Cursor, section_id: str) -> Cursor:
    if outline.section(section_id) is None:
        raise ValueError(f"section {section_id!r} not in outline")
    covered = list(cursor.covered)
    if section_id not in covered:
        covered.append(section_id)
    return Cursor(
        position=section_id,
        covered=covered,
        updated=datetime.now(timezone.utc).isoformat(),
    )


def load_cursor(path: Path) -> Cursor:
    if not path.exists():
        return Cursor()
    return Cursor(**json.loads(path.read_text()))


def save_cursor(path: Path, cursor: Cursor) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(cursor), indent=2))
