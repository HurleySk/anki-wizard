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
from anki_wizard.tools import require_section
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


# --- tools -------------------------------------------------------------------

_DELIMITERS = ("\\[", "\\]", "\\(", "\\)", "$")


def _check_content(tex: str | None, label: str | None, note: str | None) -> None:
    """Refuse content the page would render wrong, before it is written.

    The page is rebuilt on every change to the sheet, so a label that fails
    the prose guard would fail on every later edit too, long after anyone
    could say which proposal put it there. tex is checked the other way: the
    renderer adds display delimiters, so a proposal carrying its own would
    typeset as nested delimiters, which MathJax shows as source.
    """
    if tex is not None:
        if not tex.strip():
            raise ValueError("a formula needs a non-empty tex")
        if any(d in tex for d in _DELIMITERS):
            raise ValueError(
                f"tex is bare TeX; the renderer adds the display delimiters, so "
                f"{tex!r} must not carry its own"
            )
    if label is not None:
        if not label.strip():
            raise ValueError("a formula needs a non-empty label")
        check_prose(label)
    if note is not None:
        check_prose(note)


def _normalise_tex(tex: str) -> str:
    # Spacing between tokens does not change what TeX typesets, so it must not
    # make two copies of a formula count as different. Dropping it entirely
    # also equates "\sin x" with the broken "\sinx", which nobody proposes.
    return "".join(tex.split())


def _refuse_repeat(formulas: list[Formula], tex: str, except_id: str | None) -> None:
    """Refuse a tex already live on the sheet, naming the entry it repeats.

    The sheet must not balloon, and an exact repeat is the one duplicate a
    tool can catch. Applied to edits as well as proposals, since an edit can
    turn one formula into a copy of another just as easily.
    """
    key = _normalise_tex(tex)
    for formula in formulas:
        if formula.state == "rejected" or formula.id == except_id:
            continue
        if _normalise_tex(formula.tex) == key:
            raise ValueError(f"{tex!r} is already on the sheet as {formula.id}")


def _source_for(slug: str | None, section_id: str | None, paths: Paths) -> CardSource | None:
    if slug is None:
        if section_id is not None:
            raise ValueError("a section needs a slug to belong to")
        return None
    if section_id is None:
        # Unlike propose_cards, an ingested slug with no section is fine: a
        # formula can be drawn from a document as a whole.
        return CardSource(slug=slug)
    outline, section = require_section(slug, section_id, paths)
    return CardSource(slug=slug, section=section.id, pages=outline.page_numbers(section))


def propose_formulas(
    deck: str,
    proposals: list[dict],
    paths: Paths,
    slug: str | None = None,
    section_id: str | None = None,
    default_tags: list[str] | None = None,
) -> dict:
    """Append proposed formulas to the course's sheet.

    Each proposal is a dict with `tex` and `label`, and optional `note`,
    `lecture`, and `tags`. `slug` and `section_id` say where the batch came
    from, the way a card's source does; both are optional because a formula
    asked for in conversation has no document.

    An exact repeat of a formula already on the sheet is refused, naming the
    entry it repeats. That is the one duplicate a tool can catch; a near
    duplicate is a curation question for the user.
    """
    for proposal in proposals:
        _check_content(
            proposal.get("tex") or "", proposal.get("label") or "", proposal.get("note")
        )

    source = _source_for(slug, section_id, paths)
    tags = list(default_tags or [])

    path = paths.cheatsheet_file(deck_slug(deck))
    with locked(path):
        formulas = load_sheet(path)
        added: list[Formula] = []
        for proposal in proposals:
            _refuse_repeat(formulas, proposal["tex"], except_id=None)
            key = _normalise_tex(proposal["tex"])
            if any(_normalise_tex(a.tex) == key for a in added):
                raise ValueError(f"{proposal['tex']!r} appears twice in this batch")
            formula = Formula(
                id=next_formula_id(formulas + added),
                tex=proposal["tex"],
                label=proposal["label"],
                note=proposal.get("note"),
                lecture=proposal.get("lecture"),
                tags=sorted(set(list(proposal.get("tags", [])) + tags)),
                source=None
                if source is None
                else CardSource(source.slug, source.section, list(source.pages)),
            )
            added.append(record(formula, "proposed"))
        save_sheet(path, formulas + added)
    return {"added": len(added), "formulas": [asdict(f) for f in added]}


def review_formulas(deck: str, decisions: dict, paths: Paths) -> dict:
    """Apply approve, reject, and edit decisions, the grammar review_cards uses.

    A decision is "approve", "reject", or {"edit": {...}, "then": ...}. The
    page is rewritten afterwards so it never shows a state the sheet has left.
    """
    course = deck_slug(deck)
    path = paths.cheatsheet_file(course)
    with locked(path):
        formulas = load_sheet(path)
        updated: dict[str, str] = {}
        for formula_id, decision in decisions.items():
            index = index_of(formulas, formula_id, course)
            formula = formulas[index]

            if isinstance(decision, dict):
                edits = decision.get("edit") or {}
                if edits:
                    _check_content(edits.get("tex"), edits.get("label"), edits.get("note"))
                    if edits.get("tex") is not None:
                        _refuse_repeat(formulas, edits["tex"], except_id=formula_id)
                    formula = edit_formula(
                        formula,
                        tex=edits.get("tex"),
                        label=edits.get("label"),
                        note=edits.get("note"),
                        tags=edits.get("tags"),
                    )
                follow_up = decision.get("then")
            else:
                follow_up = decision

            if follow_up == "approve":
                formula = transition(formula, "approved")
            elif follow_up == "reject":
                formula = transition(formula, "rejected")
            elif follow_up is not None:
                raise ValueError(f"unknown review action {follow_up!r}")

            formulas[index] = formula
            updated[formula_id] = formula.state

        _save_sheet_and_page(deck, path, formulas, paths)
    return {"updated": updated}


def revise_formula(
    deck: str,
    formula_id: str,
    paths: Paths,
    tex: str | None = None,
    label: str | None = None,
    note: str | None = None,
    tags: list[str] | None = None,
    lecture: str | None = None,
) -> dict:
    """Edit a formula in place, or refile it under another lecture."""
    _check_content(tex, label, note)
    course = deck_slug(deck)
    path = paths.cheatsheet_file(course)
    with locked(path):
        formulas = load_sheet(path)
        index = index_of(formulas, formula_id, course)
        if tex is not None:
            _refuse_repeat(formulas, tex, except_id=formula_id)
        formula = edit_formula(formulas[index], tex=tex, label=label, note=note, tags=tags)
        if lecture is not None and lecture != formula.lecture:
            formula = record(formula, "refiled", lecture=lecture)
        formulas[index] = formula
        _save_sheet_and_page(deck, path, formulas, paths)
    return {"id": formula_id, "state": formula.state, "message": "formula revised"}


def formula_blocks(
    deck: str,
    paths: Paths,
    ids: list[str] | None = None,
    state: str | None = None,
) -> list[dict]:
    """Pad blocks showing the sheet: a heading per lecture, a formula block each.

    Unfiled entries come first under "General", then lectures in path order,
    which the zero-padded numbering makes the course order. The id and state
    ride along as meta except when showing approved entries alone -- that is
    the printable sheet, where an id is noise.
    """
    course = deck_slug(deck)
    formulas = load_sheet(paths.cheatsheet_file(course))
    by_id = {f.id: f for f in formulas}
    if ids is not None:
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise KeyError(f"no such formula for {course!r}: {', '.join(missing)}")
        formulas = [by_id[i] for i in ids]
    if state is not None:
        formulas = [f for f in formulas if f.state == state]

    return _blocks_for(formulas, show_meta=state != "approved")


def _blocks_for(formulas: list[Formula], show_meta: bool) -> list[dict]:
    groups: dict[str | None, list[Formula]] = {}
    for formula in formulas:
        groups.setdefault(formula.lecture, []).append(formula)
    ordered = sorted(groups, key=lambda lecture: (lecture is not None, lecture or ""))

    blocks: list[dict] = []
    for lecture in ordered:
        # The lecture name is Anki's, math and all, and is shown as held.
        blocks.append(
            {"type": "heading", "text": lecture or "General", "verbatim": True}
        )
        for formula in groups[lecture]:
            block = {"type": "formula", "label": formula.label, "tex": formula.tex}
            if formula.note:
                block["note"] = formula.note
            if show_meta:
                block["meta"] = f"{formula.id} \u00b7 {formula.state}"
            blocks.append(block)
    return blocks


def _render_page(deck: str, formulas: list[Formula]) -> tuple[str, int]:
    """The approved entries as the printable page, and how many there are."""
    approved = [f for f in formulas if f.state == "approved"]
    blocks = _blocks_for(approved, show_meta=False)
    html = render_html(blocks, title=deck.split("::")[0], body_class="sheet")
    return html, len(approved)


def _write_page(deck: str, formulas: list[Formula], paths: Paths) -> tuple[Path, int]:
    """Render the approved entries to the course's stable page.

    Derived from the sheet and rebuilt on every change, so the URL a user has
    open in a tab is never behind the YAML.
    """
    html, count = _render_page(deck, formulas)
    page = paths.cheatsheet_page(deck_slug(deck))
    write_text_atomic(page, html)
    return page, count


def _save_sheet_and_page(
    deck: str, path: Path, formulas: list[Formula], paths: Paths
) -> None:
    """Save the sheet and rebuild its page, or change neither.

    Rendering is pure, so it runs first: a render that fails -- a label put
    into the YAML by hand that the prose guard refuses, say -- must not leave
    the sheet saved and the page behind it, with the caller told the review
    failed when half of it stuck.
    """
    html, _ = _render_page(deck, formulas)
    save_sheet(path, formulas)
    write_text_atomic(paths.cheatsheet_page(deck_slug(deck)), html)


def render_cheatsheet(
    deck: str,
    paths: Paths,
    viewer: str = "vscode",
    server_timeout_minutes: float = 30.0,
) -> dict:
    """Rebuild the course's printable sheet and report where to read it.

    The page sits under the pad directory so the pad server serves it, at a
    URL that stays the same across rebuilds. Printing it is the export.
    """
    path = paths.cheatsheet_file(deck_slug(deck))
    with locked(path):
        page, count = _write_page(deck, load_sheet(path), paths)
    return {
        "path": str(page),
        "formulas": count,
        **open_page(
            page,
            viewer=viewer,
            idle_timeout_minutes=server_timeout_minutes,
            root=paths.pad_dir(),
        ),
    }
