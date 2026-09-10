"""Reading and editing notes anywhere in the collection."""

import pytest

from anki_wizard.anki import AnkiClient
from anki_wizard.collection import list_decks, read_note, search_collection
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
    assert "network" in hit["preview"]
    assert "{{c1::" not in hit["preview"]


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
    assert len(fake.requests[1]["params"]["notes"]) == 1


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
