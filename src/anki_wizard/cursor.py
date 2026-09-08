"""Progress tracking through a document.

The next section is the first in outline order that is not in `covered` --
deliberately not "the one after `position`". Sections get skipped and returned
to, so a high-water mark would lose work.
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from anki_wizard.atomic import write_text_atomic
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
        skipped=dict(cursor.skipped),
    )


def load_cursor(path: Path) -> Cursor:
    if not path.exists():
        return Cursor()
    try:
        data = json.loads(path.read_text())
        return Cursor(**data)
    except (ValueError, TypeError) as exc:
        # These files are meant to be hand-inspectable, so they get hand-edited.
        # Name the file rather than surfacing a bare TypeError from this module.
        raise ValueError(f"{path} is not a readable cursor file: {exc}") from exc


def save_cursor(path: Path, cursor: Cursor) -> None:
    write_text_atomic(path, json.dumps(asdict(cursor), indent=2))
