"""Tools for working with notes anywhere in the collection.

The rest of this package treats Anki as a destination: content flows from a PDF
through the ledger and out. These tools read the other way, so a note this
harness never created can still be found, shown, and corrected.

Kept out of tools.py, which is about documents, outlines, and coverage: every
function there takes a Paths and usually a slug, while these take a client and
no state layout at all. That is the seam, not a filing convenience.
"""

import re
from html import unescape

from anki_wizard.anki import AnkiClient, AnkiError
from anki_wizard.render import reveal_clozes

# Stripping tags alone leaves the CSS or JS body behind as if it were text,
# and a per-note <style> block is common in decks shared from AnkiWeb.
_DROP = re.compile(r"<(style|script)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)

# Deliberately not a general "<...>", for the reason render._MARKUP gives: a
# field's math is full of literal comparisons, and "\(n < 5\), then \(p > 0\)"
# would lose everything between the two operators -- previewing as "\(n 0\)",
# which reads as content rather than as damage. Requiring a name character,
# "/" or "!" after the "<" keeps those while still eating real tags. It is not
# airtight: a "<" followed by a letter ("\(a<b\)", "\(a <b\)") still opens a
# match that runs to the next ">" anywhere in the field, so a comparison
# written without a space before its right operand loses the span after it.
# Rarer than the spaced form this protects, which is the house style here,
# and closing it properly needs a real parser rather than a wider regex.
_TAG = re.compile(r"</?[a-zA-Z!][^>]*>")

# Deliberately the same shape as render._IMG_SRC, which rewrites these same
# srcs to data URIs: the filenames extracted here are what get fetched and
# handed to that block, so a tag missed here is a broken image there.
_IMG_SRC = re.compile(r'<img\b[^>]*?\bsrc="([^"]+)"', re.IGNORECASE)

PREVIEW_CHARS = 120


def _plain(html: str) -> str:
    """Field HTML reduced to something readable in a terminal result.

    Entities are unescaped after the tags come out, not before: "&lt;b&gt;" in
    a field is text the user typed, and unescaping first would turn it into a
    tag for the next pass to eat.
    """
    text = reveal_clozes(html)
    text = _DROP.sub(" ", text)
    text = _TAG.sub(" ", text)
    return " ".join(unescape(text).split())


def _ordered_fields(record_: dict) -> list[tuple[str, str]]:
    """A note's fields in the note type's own order.

    The trailing underscore is collision avoidance, not decoration: `record`
    is ledger.py's history helper, which the guarded edit added here later
    imports by that name.

    notesInfo returns a dict carrying an explicit order per field; relying on
    insertion order would put a card's fields in whatever order the JSON came.
    """
    items = record_.get("fields", {}).items()
    return [
        (name, value.get("value", ""))
        for name, value in sorted(items, key=lambda kv: kv[1].get("order", 0))
    ]


def _decks_by_card(card_ids: list[int], client: AnkiClient) -> dict[int, str]:
    """Deck name per card id, in one call.

    strict=True is safe here, and is the check worth having: cardsInfo appends
    an empty dict for a card it cannot find rather than dropping the position,
    so the two lists correspond even when an id is stale. A length mismatch
    would mean decks silently attached to the wrong notes, which is worse than
    an error.
    """
    if not card_ids:
        return {}
    cards = client.cards_info(card_ids)
    return {
        cid: card.get("deckName", "") if card else ""
        for cid, card in zip(card_ids, cards, strict=True)
    }


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
    if limit < 1:
        # A raise, not a clamp: these arguments come from an agent or an MCP
        # client, and 0 meaning "unlimited" is a guess this cannot make safely.
        raise ValueError(f"limit must be at least 1, got {limit}")

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
    deck_by_card = _decks_by_card(all_card_ids, client)

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

    `fields` and `ordered_fields` carry the same pairs in two shapes on
    purpose: an edit looks a field up by name, while the pad's note block
    takes the ordered list. Both preserve note-type order.
    """
    record_ = _fetch(note_id, client)
    fields = _ordered_fields(record_)
    media = []
    for _, value in fields:
        media.extend(_IMG_SRC.findall(value))

    deck_by_card = _decks_by_card(record_.get("cards", []), client)

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


def note_blocks(note_id: int, client: AnkiClient) -> list[dict]:
    """Pad blocks showing one note, with its media fetched and inlined.

    Returned as blocks rather than rendered so the caller can put the card in a
    page beside its own prose -- the point is working through the material, not
    previewing the card on its own.
    """
    note = read_note(note_id, client)

    media: dict[str, bytes] = {}
    unresolved: list[str] = []
    # dict.fromkeys, not set(...): a note referencing one image on both its
    # front and back (read_note's media list is not de-duplicated) must be
    # fetched once, and the fetch order should still match the note's own
    # field order rather than whatever order a set happens to iterate in.
    for filename in dict.fromkeys(note["media"]):
        try:
            data = client.retrieve_media_file(filename)
        except AnkiError:
            unresolved.append(filename)
            # A single corrupt or truncated file must not blank the whole
            # pad -- the pad's job is to show the user the card, and a card
            # missing one image is far better than no pad at all. render.py's
            # _inline_media leaves an unresolved <img src="..."> tag alone
            # rather than hiding it, so skipping the file here degrades to a
            # visible broken image with its filename intact, not silence.
            continue
        if data is None:
            unresolved.append(filename)
        else:
            media[filename] = data

    return [
        {
            "type": "note",
            # The deck path is the only human-readable locator a note has: a
            # note has no name, and its id says nothing to a reader. Empty for
            # a cardless note, which _render_note drops rather than emitting a
            # blank heading.
            "title": note["deck"],
            "fields": note["ordered_fields"],
            "media": media,
            # Named here rather than only on the page. The rendered pad shows a
            # broken <img> carrying the filename, which tells a human reading
            # it -- but the caller describing this note to the user sees only
            # what is returned, and "no images" and "three failed to load" are
            # otherwise the same empty dict. Kept inside the block rather than
            # added as a prose block: prose refuses markup, and a filename
            # holding "&amp;" would raise and take down the very pad this
            # reporting exists to preserve.
            "unresolved_media": unresolved,
        }
    ]


def list_decks(client: AnkiClient) -> dict:
    """Every deck in the collection, sorted.

    Confirming a deck name is a requirement elsewhere in this harness -- Anki
    creates decks on demand, so a typo silently makes a near-duplicate that
    splits reviews with no error to notice.
    """
    return {"decks": sorted(client.deck_names())}
