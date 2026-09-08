"""The card ledger: cards/<slug>.yaml.

The ledger is the source of truth. Every card lives here from the moment it is
proposed, and it records provenance and the Anki note id so a card can be
revised later without losing its review history.
"""

from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from anki_wizard.atomic import write_text_atomic
from anki_wizard.models import Card, CardSource


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger(path: Path) -> list[Card]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or []
    cards: list[Card] = []
    for position, r in enumerate(raw):
        try:
            cards.append(
                Card(
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
            )
        except (KeyError, TypeError) as exc:
            # The ledger is the source of truth and is meant to be readable, so
            # it gets hand-edited. Say which file and which entry is wrong.
            raise ValueError(
                f"{path}: entry {position} is not a readable card ({exc})"
            ) from exc
    return cards


def save_ledger(path: Path, cards: list[Card]) -> None:
    write_text_atomic(
        path,
        yaml.safe_dump([asdict(c) for c in cards], sort_keys=False, allow_unicode=True),
    )


def next_card_id(cards: list[Card]) -> str:
    highest = 0
    for card in cards:
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
            history=[{"at": _now(), "action": "proposed"}],
        )
        added.append(card)
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
    updated = replace(
        card,
        state=target,
        history=card.history + [{"at": _now(), "action": target}],
    )
    if anki_note_id is not None:
        updated.anki_note_id = anki_note_id
    return updated


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
    return replace(
        card,
        front=new_front,
        back=new_back,
        why=new_why,
        tags=new_tags,
        history=card.history + [{"at": _now(), "action": "edited"}],
    )
