"""Reading and editing notes anywhere in the collection."""

import base64

import pytest

from anki_wizard.anki import AnkiClient
from anki_wizard.collection import (
    _plain,
    list_decks,
    note_blocks,
    read_note,
    search_collection,
)
from tests.fake_anki import FakeAnki

CLOZE_NOTE = {
    "noteId": 1739985246842,
    "modelName": "Cloze Overlapping",
    "tags": ["6.041", "L3_Independence"],
    # search and read take card ids off the notesInfo record rather than
    # making a second call, so a fixture without this key reports no deck.
    "cards": [1],
    "fields": {
        "Text": {"value": "A {{c1::network}} connects \\(A\\) and \\(B\\).", "order": 0},
        "Answer": {"value": '<img src="paste-abc.jpg"> so \\(0.957\\)', "order": 1},
        "Summary 1": {"value": "", "order": 2},
    },
}

CLOZE_NOTE_B = {
    "noteId": 1739985246999,
    "modelName": "Cloze Overlapping",
    "tags": ["6.041"],
    "cards": [2],
    "fields": {
        "Text": {"value": "A {{c1::graph}} has \\(V\\) and \\(E\\).", "order": 0},
        "Answer": {"value": "", "order": 1},
        "Summary 1": {"value": "", "order": 2},
    },
}


def test_search_returns_scannable_summaries():
    """Sixteen fields per note would bury the result; the first field locates it."""
    with FakeAnki() as fake:
        fake.set_response("findNotes", [1739985246842])
        fake.set_response("notesInfo", [CLOZE_NOTE])
        fake.set_response("cardsInfo", [{"deckName": "Intro to Probability::Unit I"}])
        client = AnkiClient(fake.url)

        found = search_collection("deck:Probability network", client)

    assert found["count"] == 1
    hit = found["notes"][0]
    assert hit["note_id"] == 1739985246842
    assert hit["model"] == "Cloze Overlapping"
    assert "{{c1::" not in hit["preview"]
    # Positive, not just the absence of markup: a reveal that deleted the
    # deletion instead of unwrapping it would satisfy the negative alone.
    assert hit["preview"].startswith("A network connects")


def test_search_reports_nothing_found_without_calling_for_details():
    with FakeAnki() as fake:
        fake.set_response("findNotes", [])
        client = AnkiClient(fake.url)

        found = search_collection("deck:Nope", client)

    assert found["count"] == 0
    assert found["notes"] == []
    assert not any(r["action"] == "notesInfo" for r in fake.requests)


def test_search_caps_the_number_of_notes_it_details():
    with FakeAnki() as fake:
        fake.set_response("findNotes", list(range(1, 51)))
        fake.set_response("notesInfo", [CLOZE_NOTE])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        client = AnkiClient(fake.url)

        found = search_collection("deck:Big", client, limit=1)

    assert found["count"] == 50
    assert found["truncated"] is True
    detailed = next(r for r in fake.requests if r["action"] == "notesInfo")
    assert len(detailed["params"]["notes"]) == 1
    assert len(found["notes"]) == 1


def test_search_batches_deck_lookup_into_one_call():
    """Fifty notes must not mean fifty round-trips to find their decks."""
    with FakeAnki() as fake:
        fake.set_response("findNotes", [1739985246842, 1739985246999])
        fake.set_response("notesInfo", [CLOZE_NOTE, CLOZE_NOTE_B])
        fake.set_response(
            "cardsInfo",
            [
                {"deckName": "Intro to Probability::Unit I"},
                {"deckName": "Intro to Probability::Unit II"},
            ],
        )
        client = AnkiClient(fake.url)

        found = search_collection("deck:Probability", client)

    assert len(fake.requests) == 3
    assert [r["action"] for r in fake.requests] == [
        "findNotes",
        "notesInfo",
        "cardsInfo",
    ]
    assert len([r for r in fake.requests if r["action"] == "cardsInfo"]) == 1
    decks = {n["note_id"]: n["deck"] for n in found["notes"]}
    assert decks[1739985246842] == "Intro to Probability::Unit I"
    assert decks[1739985246999] == "Intro to Probability::Unit II"


def test_read_note_returns_every_field_by_its_real_name():
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [CLOZE_NOTE])
        fake.set_response("cardsInfo", [{"deckName": "Intro to Probability::Unit I"}])
        client = AnkiClient(fake.url)

        note = read_note(1739985246842, client)

    assert note["model"] == "Cloze Overlapping"
    assert note["deck"] == "Intro to Probability::Unit I"
    assert note["fields"]["Text"].startswith("A {{c1::network}}")
    assert note["field_names"] == ["Text", "Answer", "Summary 1"]
    assert note["media"] == ["paste-abc.jpg"]


def test_read_note_raises_on_a_deleted_note():
    """notesInfo answers a deleted note with an empty dict, not an error."""
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [{}])
        client = AnkiClient(fake.url)

        with pytest.raises(ValueError, match="no note"):
            read_note(999, client)


def test_list_decks_returns_the_tree():
    with FakeAnki() as fake:
        fake.set_response("deckNames", ["Default", "Stats::Unit I", "Stats"])
        client = AnkiClient(fake.url)

        assert list_decks(client)["decks"] == ["Default", "Stats", "Stats::Unit I"]


OUT_OF_ORDER_NOTE = {
    "noteId": 42,
    "modelName": "Basic",
    "tags": [],
    "cards": [7],
    # Insertion order deliberately disagrees with the note type's own order,
    # which is the only thing that exercises _ordered_fields at all.
    "fields": {
        "Back": {"value": "second", "order": 1},
        "Front": {"value": "first", "order": 0},
    },
}


def test_read_note_uses_the_note_types_order_not_the_json_order():
    """Anki sends a dict; its insertion order is not the field order."""
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [OUT_OF_ORDER_NOTE])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        client = AnkiClient(fake.url)

        note = read_note(42, client)

    assert note["field_names"] == ["Front", "Back"]
    assert note["ordered_fields"] == [("Front", "first"), ("Back", "second")]


def test_read_note_reports_no_deck_for_a_note_with_no_cards():
    """A note whose cards were all deleted still reads, with an empty deck.

    Task 10 slugs this value to pick a ledger, so it must not surprise: an
    empty string is the honest answer, and raising here would stop a caller
    from even looking at the note.
    """
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [{**OUT_OF_ORDER_NOTE, "cards": []}])
        client = AnkiClient(fake.url)

        note = read_note(42, client)

    assert note["deck"] == ""
    assert not any(r["action"] == "cardsInfo" for r in fake.requests)


def test_read_note_collects_media_from_every_field():
    """Task 9 fetches these bytes, so a filename missed here is a lost image."""
    two_images = {
        **OUT_OF_ORDER_NOTE,
        "fields": {
            "Front": {"value": '<img src="a.png"> text', "order": 0},
            "Back": {"value": "none here", "order": 1},
            "Extra": {"value": '<img src="b.jpg">', "order": 2},
        },
    }
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [two_images])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        client = AnkiClient(fake.url)

        assert read_note(42, client)["media"] == ["a.png", "b.jpg"]


def test_search_rejects_a_limit_below_one():
    """0 reads as "unlimited" to a caller and as "an empty page" to a slice."""
    with FakeAnki() as fake:
        client = AnkiClient(fake.url)
        with pytest.raises(ValueError, match="at least 1"):
            search_collection("deck:D", client, limit=0)


def test_a_preview_keeps_a_comparison_in_math():
    """A greedy <...> strip would delete everything between the operators.

    This collection is a statistics deck, so "\\(n < 5\\)" is house style, and
    a preview reading "\\(n  0\\)" looks like content rather than damage.
    """
    field = {"value": r"If \(n < 5\), then \(p > 0\).", "order": 0}
    with FakeAnki() as fake:
        fake.set_response("findNotes", [1])
        fake.set_response("notesInfo", [{**OUT_OF_ORDER_NOTE, "fields": {"T": field}}])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        client = AnkiClient(fake.url)

        preview = search_collection("n", client)["notes"][0]["preview"]

    assert r"\(n < 5\)" in preview
    assert r"\(p > 0\)" in preview


def test_a_preview_reads_as_text_not_as_source():
    """Entities and a shared deck's <style> block are noise in 120 characters."""
    field = {"value": "<style>.card{color:red}</style>A&nbsp;&amp;&nbsp;B", "order": 0}
    with FakeAnki() as fake:
        fake.set_response("findNotes", [1])
        fake.set_response("notesInfo", [{**OUT_OF_ORDER_NOTE, "fields": {"T": field}}])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        client = AnkiClient(fake.url)

        preview = search_collection("b", client)["notes"][0]["preview"]

    assert preview == "A & B"
    assert "color:red" not in preview


def test_a_typed_entity_survives_as_text():
    """Unescaping before the tag strip would turn "&lt;b&gt;" into a tag to eat."""
    assert _plain("&lt;b&gt; typed as text") == "<b> typed as text"


def test_note_blocks_carry_fields_and_fetched_media():
    """The tool fetches; the renderer stays a pure function of its input."""
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [CLOZE_NOTE])
        fake.set_response("cardsInfo", [{"deckName": "Intro to Probability::Unit I"}])
        fake.set_response(
            "retrieveMediaFile", base64.b64encode(b"JPEGDATA").decode()
        )
        client = AnkiClient(fake.url)

        blocks = note_blocks(1739985246842, client)

    assert len(blocks) == 1
    block = blocks[0]
    assert block["type"] == "note"
    assert (
        "Text",
        "A {{c1::network}} connects \\(A\\) and \\(B\\).",
    ) in block["fields"]
    assert block["media"] == {"paste-abc.jpg": b"JPEGDATA"}
    assert "Intro to Probability" in block["title"]


def test_note_blocks_tolerate_missing_media():
    """A file Anki cannot find must not stop the pad from rendering the card."""
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [CLOZE_NOTE])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        fake.set_response("retrieveMediaFile", False)
        client = AnkiClient(fake.url)

        blocks = note_blocks(1739985246842, client)

    assert blocks[0]["media"] == {}


def test_note_blocks_tolerate_undecodable_media():
    """A corrupt file must not abort the whole pad -- only that file is lost.

    retrieve_media_file raises AnkiError (not None) when the payload does not
    decode as base64, which is a different failure mode than "file missing"
    and must be caught separately.
    """
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [CLOZE_NOTE])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        fake.set_response("retrieveMediaFile", "not!valid!base64")
        client = AnkiClient(fake.url)

        blocks = note_blocks(1739985246842, client)

    assert blocks[0]["media"] == {}
    # The rest of the note is untouched by the one bad file.
    assert (
        "Text",
        "A {{c1::network}} connects \\(A\\) and \\(B\\).",
    ) in blocks[0]["fields"]


def test_note_blocks_fetch_a_repeated_file_once():
    """One image referenced on both sides of a card is one round-trip, not two."""
    repeated = {
        **OUT_OF_ORDER_NOTE,
        "fields": {
            # b before a, and b repeated: the fetch order must follow the
            # note's own fields, which is the other half of why this uses
            # dict.fromkeys rather than a set.
            "Front": {"value": '<img src="c.png"> front', "order": 0},
            "Back": {"value": '<img src="a.png"> <img src="b.png"> <img src="c.png">',
                     "order": 1},
        },
    }
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [repeated])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        fake.set_response(
            "retrieveMediaFile", base64.b64encode(b"PNGDATA").decode()
        )
        client = AnkiClient(fake.url)

        blocks = note_blocks(42, client)

    assert set(blocks[0]["media"]) == {"a.png", "b.png", "c.png"}
    fetches = [r for r in fake.requests if r["action"] == "retrieveMediaFile"]
    # c, a, b is the field order and is neither sorted nor reverse-sorted.
    assert [r["params"]["filename"] for r in fetches] == ["c.png", "a.png", "b.png"]


def test_note_blocks_keep_a_zero_byte_file_rather_than_calling_it_missing():
    """An empty file is falsy but real; dropping it misreports a bad sync.

    anki.py draws this distinction deliberately, and this is the layer where
    the falsy-bytes mistake is the natural one to make.
    """
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [CLOZE_NOTE])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        fake.set_response("retrieveMediaFile", "")
        client = AnkiClient(fake.url)

        blocks = note_blocks(1739985246842, client)

    assert blocks[0]["media"] == {"paste-abc.jpg": b""}
    assert blocks[0]["unresolved_media"] == []


def test_note_blocks_name_the_media_they_could_not_load():
    """"no images" and "three failed" are otherwise the same empty dict.

    The pad shows a broken <img> to whoever reads it, but the caller
    describing this note to the user only sees what is returned here.
    """
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [CLOZE_NOTE])
        fake.set_response("cardsInfo", [{"deckName": "D"}])
        fake.set_response("retrieveMediaFile", False)
        client = AnkiClient(fake.url)

        blocks = note_blocks(1739985246842, client)

    assert blocks[0]["media"] == {}
    assert blocks[0]["unresolved_media"] == ["paste-abc.jpg"]
