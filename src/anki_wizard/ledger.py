"""The card ledger: cards/<slug>.yaml.

The ledger is the source of truth. Every card lives here from the moment it is
proposed, and it records provenance and the Anki note id so a card can be
revised later without losing its review history.

It also holds adopted notes -- references to notes this harness did not author,
kept so edits to them leave the same trail. A `kind` key tells the two apart.
"""

from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

import yaml

from anki_wizard.atomic import locked, write_text_atomic
from anki_wizard.models import AdoptedNote, Card, CardSource

# Anything with a history list: a card, an adopted note, a cheat sheet formula.
E = TypeVar("E")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def record(
    entry: E,
    action: str,
    detail: dict | None = None,
    **changes,
) -> E:
    """Return a copy of `entry` with `changes` applied and `action` in its history.

    Every change to a ledger entry goes through here so the history stays an
    audit trail: nothing changes a field without saying what happened and when.
    Adopted notes and cheat sheet formulas get the same treatment as authored
    cards -- all are dataclasses carrying a history list, which is all this
    needs.

    `detail` is merged into the history entry rather than set on the entry, for
    facts about the event that are not fields of the thing: which fields an
    edit touched, say. An adopted note stores no content, so what changed is
    the only substantive thing its history can carry.
    """
    event = {"at": _now(), "action": action}
    if detail:
        event |= detail
    return replace(entry, history=entry.history + [event], **changes)


def _load_card(r: dict) -> Card:
    return Card(
        id=r["id"],
        front=r["front"],
        back=r["back"],
        source=CardSource(**r["source"]),
        why=r.get("why"),
        lecture=r.get("lecture"),
        state=r.get("state", "proposed"),
        tags=r.get("tags", []),
        anki_note_id=r.get("anki_note_id"),
        history=r.get("history", []),
    )


def _load_adopted(r: dict) -> AdoptedNote:
    if not isinstance(r["fields"], list):
        # "fields: Text" is the natural way to hand-write a single field, and
        # list() would spell it into four bogus names rather than complain.
        # An edit is checked against these before it reaches Anki, so a garbled
        # value here weakens that check instead of failing it.
        raise TypeError(f"fields must be a list, not {type(r['fields']).__name__}")
    return AdoptedNote(
        note_id=r["note_id"],
        model=r["model"],
        deck=r["deck"],
        fields=list(r["fields"]),
        tags=r.get("tags", []),
        history=r.get("history", []),
    )


def load_ledger(path: Path) -> list[Card | AdoptedNote]:
    """Every entry in a ledger, authored cards and adopted notes alike.

    `kind` defaults to "card" because every ledger written before adoption
    existed has no such key, and those must keep loading untouched.
    """
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or []
    entries: list[Card | AdoptedNote] = []
    for position, r in enumerate(raw):
        try:
            kind = r.get("kind", "card")
            if kind == "adopted":
                entries.append(_load_adopted(r))
            elif kind == "card":
                entries.append(_load_card(r))
            else:
                raise ValueError(f"unknown kind {kind!r}")
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            # The ledger is the source of truth and is meant to be readable, so
            # it gets hand-edited. Say which file and which entry is wrong.
            raise ValueError(
                f"{path}: entry {position} is not readable ({exc})"
            ) from exc

    _reject_duplicates(path, entries)
    return entries


def _reject_duplicates(path: Path, entries: list[Card | AdoptedNote]) -> None:
    """Lookup takes the first match, so a repeat makes the second unreachable.

    Edits and pushes would silently land on the first copy. Card ids and note
    ids are separate namespaces, so the key carries which one it came from.
    """
    seen: dict[object, int] = {}
    for position, entry in enumerate(entries):
        key = ("card", entry.id) if isinstance(entry, Card) else ("note", entry.note_id)
        shown = entry.id if isinstance(entry, Card) else entry.note_id
        if key in seen:
            raise ValueError(
                f"{path}: entries {seen[key]} and {position} share the id "
                f"{shown!r}; ids must be unique"
            )
        seen[key] = position


def _as_row(entry: Card | AdoptedNote) -> dict:
    kind = "card" if isinstance(entry, Card) else "adopted"
    # Written even for cards, which never needed it, so a hand-edited ledger
    # reads unambiguously rather than relying on the back-compat default.
    return {"kind": kind, **asdict(entry)}


def save_ledger(path: Path, entries: list[Card | AdoptedNote]) -> None:
    write_text_atomic(
        path,
        yaml.safe_dump(
            [_as_row(e) for e in entries], sort_keys=False, allow_unicode=True
        ),
    )


def cards_only(entries: list[Card | AdoptedNote]) -> list[Card]:
    """Just the authored cards. Adopted notes have no state, source or lecture."""
    return [e for e in entries if isinstance(e, Card)]


def index_of(cards: list[Card | AdoptedNote], card_id: str, slug: str) -> int:
    """The position of `card_id` in the ledger, or ValueError naming the slug.

    load_ledger rejects duplicate ids, so the first match is the only match.
    Callers hold the list rather than the path -- they are already inside the
    lock, and re-reading would defeat it.
    """
    for index, card in enumerate(cards):
        # Adopted notes have no card id, and a ledger can now hold them.
        if isinstance(card, Card) and card.id == card_id:
            return index
    raise ValueError(f"no card {card_id!r} in ledger for {slug!r}")


def next_card_id(cards: list[Card | AdoptedNote]) -> str:
    """The next free `c-NNNN`. Adopted notes carry Anki's ids and are skipped."""
    highest = 0
    for card in cards:
        if not isinstance(card, Card):
            continue
        try:
            highest = max(highest, int(card.id.split("-")[1]))
        except (IndexError, ValueError):
            continue
    return f"c-{highest + 1:04d}"


def append_cards(path: Path, proposals: list[dict], source: CardSource) -> list[Card]:
    """Append proposed cards to the ledger, assigning sequential ids.

    Each proposal is a dict with `front`, `back`, and optional `why`,
    `lecture`, and `tags`.
    """
    with locked(path):
        cards = load_ledger(path)
        added: list[Card] = []
        for proposal in proposals:
            card = Card(
                id=next_card_id(cards + added),
                front=proposal["front"],
                back=proposal["back"],
                source=CardSource(
                    slug=source.slug, section=source.section, pages=list(source.pages)
                ),
                why=proposal.get("why"),
                lecture=proposal.get("lecture"),
                tags=list(proposal.get("tags", [])),
            )
            added.append(record(card, "proposed"))
        save_ledger(path, cards + added)
    return added


LEGAL_TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"approved", "rejected"},
    "approved": {"pushed", "rejected"},
    "pushed": {"orphaned"},
    "rejected": set(),
    "orphaned": set(),
}


def transition(card: Card, target: str, anki_note_id: int | None = None) -> Card:
    """Return a copy of `card` moved to `target` state.

    Raises ValueError on an illegal transition rather than silently corrupting
    the ledger. Does not mutate the input.
    """
    if target not in LEGAL_TRANSITIONS.get(card.state, set()):
        raise ValueError(f"illegal transition: {card.state} -> {target}")
    changes: dict[str, object] = {"state": target}
    if anki_note_id is not None:
        changes["anki_note_id"] = anki_note_id
    return record(card, target, **changes)


def edit_card(
    card: Card,
    front: str | None = None,
    back: str | None = None,
    why: str | None = None,
    tags: list[str] | None = None,
) -> Card:
    """Return a copy of `card` with edited content, preserving state.

    A pushed card stays pushed and is updated in Anki in place, which is why
    editing is not modelled as a state transition.
    """
    if card.state in ("rejected", "orphaned"):
        raise ValueError(
            f"card {card.id} is {card.state}, which is terminal, so it cannot be "
            "edited. Propose a new card instead."
        )
    new_front = card.front if front is None else front
    new_back = card.back if back is None else back
    new_why = card.why if why is None else why
    new_tags = card.tags if tags is None else list(tags)
    # History is an audit trail, so it records edits that happened rather than
    # edits that were requested. A caller assembling this call from optional
    # fields can easily pass all-None, or values equal to what is already
    # there; neither is an event worth recording.
    changed = (new_front, new_back, new_why, new_tags) != (
        card.front,
        card.back,
        card.why,
        card.tags,
    )
    if not changed:
        return card
    return record(
        card, "edited", front=new_front, back=new_back, why=new_why, tags=new_tags
    )


def adopt_note(
    path: Path, note_id: int, model: str, deck: str, fields: list[str]
) -> AdoptedNote:
    """Ensure a ledger entry exists for a note this harness did not create.

    Called on the first edit of a foreign note, and harmlessly again on every
    later one: adoption is a fact about the note, not an event to repeat.
    """
    with locked(path):
        entries = load_ledger(path)
        for entry in entries:
            if isinstance(entry, AdoptedNote) and entry.note_id == note_id:
                return entry
        adopted = record(
            AdoptedNote(note_id=note_id, model=model, deck=deck, fields=list(fields)),
            "adopted",
        )
        save_ledger(path, entries + [adopted])
    return adopted
