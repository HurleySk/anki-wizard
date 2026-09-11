"""The cheat sheet: one page of key formulas per course.

Cards test recall one fact at a time; the sheet is the opposite artifact, the
formulas a course reaches for again and again, organised by lecture and meant
to be printed. It is per course rather than per source, so it gathers from
every document and conversation in a course, and its slug is the deck's.

The store mirrors the ledger: YAML, atomic writes, an audit history on every
entry, and rows that are never deleted. Entries are proposed and reviewed like
cards, but only when the user asks -- the sheet is worth less the longer it
gets, and that judgment is the user's.

The tools live here rather than in tools.py for the reason collection.py's do:
they key on a course, not a slug, and none of them touches a cursor.
"""

from dataclasses import asdict
from pathlib import Path

import yaml

from anki_wizard.atomic import locked, write_text_atomic
from anki_wizard.ledger import record
from anki_wizard.models import CardSource, Formula
from anki_wizard.paths import Paths, deck_slug
from anki_wizard.render import check_prose, render_html
from anki_wizard.viewer import open_page


def _load_formula(r: dict) -> Formula:
    source = r.get("source")
    return Formula(
        id=r["id"],
        tex=r["tex"],
        label=r["label"],
        note=r.get("note"),
        lecture=r.get("lecture"),
        tags=r.get("tags", []),
        source=CardSource(**source) if source else None,
        state=r.get("state", "proposed"),
        history=r.get("history", []),
    )


def load_sheet(path: Path) -> list[Formula]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or []
    formulas: list[Formula] = []
    for position, r in enumerate(raw):
        try:
            formulas.append(_load_formula(r))
        except (AttributeError, KeyError, TypeError) as exc:
            # Hand-edited like the ledger, so say which file and which entry.
            raise ValueError(
                f"{path}: entry {position} is not readable ({exc})"
            ) from exc

    seen: dict[str, int] = {}
    for position, formula in enumerate(formulas):
        if formula.id in seen:
            raise ValueError(
                f"{path}: entries {seen[formula.id]} and {position} share the id "
                f"{formula.id!r}; ids must be unique"
            )
        seen[formula.id] = position
    return formulas


def save_sheet(path: Path, formulas: list[Formula]) -> None:
    write_text_atomic(
        path,
        yaml.safe_dump(
            [asdict(f) for f in formulas], sort_keys=False, allow_unicode=True
        ),
    )


def next_formula_id(formulas: list[Formula]) -> str:
    highest = 0
    for formula in formulas:
        try:
            highest = max(highest, int(formula.id.split("-")[1]))
        except (IndexError, ValueError):
            continue
    return f"f-{highest + 1:04d}"


def index_of(formulas: list[Formula], formula_id: str, course: str) -> int:
    for index, formula in enumerate(formulas):
        if formula.id == formula_id:
            return index
    raise ValueError(f"no formula {formula_id!r} on the sheet for {course!r}")


# Approved is the terminal good state: there is no push, the sheet is the
# destination. Rejecting an approved entry is how it leaves the sheet.
LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"approved", "rejected"},
    "approved": {"rejected"},
    "rejected": set(),
}


def transition(formula: Formula, target: str) -> Formula:
    if target not in LEGAL_TRANSITIONS.get(formula.state, set()):
        raise ValueError(f"illegal transition: {formula.state} -> {target}")
    return record(formula, target, state=target)


def edit_formula(
    formula: Formula,
    tex: str | None = None,
    label: str | None = None,
    note: str | None = None,
    tags: list[str] | None = None,
) -> Formula:
    """A copy with edited content, preserving state; unchanged if nothing changed."""
    if formula.state == "rejected":
        raise ValueError(
            f"formula {formula.id} is rejected, which is terminal, so it cannot "
            "be edited. Propose it again instead."
        )
    new = {
        "tex": formula.tex if tex is None else tex,
        "label": formula.label if label is None else label,
        "note": formula.note if note is None else note,
        "tags": formula.tags if tags is None else list(tags),
    }
    if all(getattr(formula, k) == v for k, v in new.items()):
        return formula
    return record(formula, "edited", **new)
