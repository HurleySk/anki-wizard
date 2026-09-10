"""Tools for working with notes anywhere in the collection.

The rest of this package treats Anki as a destination: content flows from a PDF
through the ledger and out. These tools read the other way, so a note this
harness never created can still be found, shown, and corrected.

Kept out of tools.py, which is already the largest module here and is about
documents, outlines, and coverage -- none of which these touch.
"""

import re

from anki_wizard.anki import AnkiClient
from anki_wizard.render import reveal_clozes

_TAG = re.compile(r"<[^>]+>")
_IMG_SRC = re.compile(r'<img\b[^>]*?\bsrc="([^"]+)"', re.IGNORECASE)

PREVIEW_CHARS = 120


def _plain(html: str) -> str:
    """Field HTML reduced to something readable in a terminal result."""
    text = reveal_clozes(html)
    text = _TAG.sub(" ", text)
    return " ".join(text.split())


def _ordered_fields(record_: dict) -> list[tuple[str, str]]:
    """A note's fields in the note type's own order.

    notesInfo returns a dict carrying an explicit order per field; relying on
    insertion order would put a card's fields in whatever order the JSON came.
    """
    items = record_.get("fields", {}).items()
    return [
        (name, value.get("value", ""))
        for name, value in sorted(items, key=lambda kv: kv[1].get("order", 0))
    ]


def _fetch(note_id: int, client: AnkiClient) -> dict:
    info = client.notes_info([note_id])
    if not info or not info[0]:
        raise ValueError(f"no note {note_id} in the collection")
    return info[0]


def _deck_of(record_: dict, deck_by_card: dict[int, str]) -> str:
    """The deck a note lives in, from a card-id-to-deck-name map.

    A note has no deck of its own -- its cards do -- and a note can generate
    several cards that a user has since moved to different decks by hand. The
    first is reported: enough to slug the note and show the user, without
    pretending a note lives in one place when Anki does not guarantee that.
    """
    card_ids = record_.get("cards", [])
    if not card_ids:
        return ""
    return deck_by_card.get(card_ids[0], "")


def search_collection(query: str, client: AnkiClient, limit: int = 25) -> dict:
    """Find notes anywhere in the collection.

    `query` is Anki search syntax -- deck:"...", tag:..., or bare text. Results
    carry a short preview rather than full fields: a cloze note type can have
    sixteen fields, and dumping them all would bury the note being looked for.
    """
    note_ids = client.find_notes(query)
    if not note_ids:
        return {"query": query, "count": 0, "truncated": False, "notes": []}

    shown = note_ids[:limit]
    records = [r for r in client.notes_info(shown) if r]

    # Card ids come off the notesInfo records themselves rather than a second
    # per-note call: notesInfo already returns a "cards" key for every note
    # (AnkiConnect builds it from the same nid-to-card-ids map cardsInfo would
    # need), so a per-note fetch would be a redundant round-trip. Deck lookup
    # is then one batched cardsInfo call for every card in the result, not one
    # call per note -- at the default limit that is the difference between 1
    # HTTP round-trip and 25.
    all_card_ids = [cid for r in records for cid in r.get("cards", [])]
    deck_by_card: dict[int, str] = {}
    if all_card_ids:
        cards = client.cards_info(all_card_ids)
        for card_id, card in zip(all_card_ids, cards, strict=True):
            deck_by_card[card_id] = card.get("deckName", "") if card else ""

    notes = []
    for record_ in records:
        fields = _ordered_fields(record_)
        first = fields[0][1] if fields else ""
        notes.append(
            {
                "note_id": record_["noteId"],
                "model": record_.get("modelName", ""),
                "deck": _deck_of(record_, deck_by_card),
                "tags": record_.get("tags", []),
                "preview": _plain(first)[:PREVIEW_CHARS],
            }
        )

    return {
        "query": query,
        "count": len(note_ids),
        "truncated": len(note_ids) > len(shown),
        "notes": notes,
    }


def read_note(note_id: int, client: AnkiClient) -> dict:
    """One note in full: every field by its real name, plus where it lives.

    Field names matter as much as values here -- an edit is checked against
    them, so a caller that never read the note cannot safely write to it.
    """
    record_ = _fetch(note_id, client)
    fields = _ordered_fields(record_)
    media = []
    for _, value in fields:
        media.extend(_IMG_SRC.findall(value))

    card_ids = record_.get("cards", [])
    deck_by_card = {}
    if card_ids:
        cards = client.cards_info(card_ids)
        for card_id, card in zip(card_ids, cards, strict=True):
            deck_by_card[card_id] = card.get("deckName", "") if card else ""

    return {
        "note_id": note_id,
        "model": record_.get("modelName", ""),
        "deck": _deck_of(record_, deck_by_card),
        "tags": record_.get("tags", []),
        "field_names": [name for name, _ in fields],
        "fields": dict(fields),
        "ordered_fields": fields,
        "media": media,
    }


def list_decks(client: AnkiClient) -> dict:
    """Every deck in the collection, sorted.

    Confirming a deck name is a requirement elsewhere in this harness -- Anki
    creates decks on demand, so a typo silently makes a near-duplicate that
    splits reviews with no error to notice.
    """
    return {"decks": sorted(client.deck_names())}
