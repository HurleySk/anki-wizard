"""The card ledger: cards/<slug>.yaml.

The ledger is the source of truth. Every card lives here from the moment it is
proposed, and it records provenance and the Anki note id so a card can be
revised later without losing its review history.
"""

from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import yaml

from anki_wizard.models import Card, CardSource


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_ledger(path: Path) -> list[Card]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or []
    return [
        Card(
            id=r["id"],
            front=r["front"],
            back=r["back"],
            source=CardSource(**r["source"]),
            state=r.get("state", "proposed"),
            tags=r.get("tags", []),
            anki_note_id=r.get("anki_note_id"),
            history=r.get("history", []),
        )
        for r in raw
    ]


def save_ledger(path: Path, cards: list[Card]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump([asdict(c) for c in cards], sort_keys=False, allow_unicode=True)
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

    Each proposal is a dict with `front`, `back`, and optional `tags`.
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
    tags: list[str] | None = None,
) -> Card:
    """Return a copy of `card` with edited content, preserving state.

    A pushed card stays pushed and is updated in Anki in place, which is why
    editing is not modelled as a state transition.
    """
    if card.state in ("rejected", "orphaned"):
        raise ValueError(f"cannot edit a {card.state} card")
    return replace(
        card,
        front=card.front if front is None else front,
        back=card.back if back is None else back,
        tags=card.tags if tags is None else list(tags),
        history=card.history + [{"at": _now(), "action": "edited"}],
    )
