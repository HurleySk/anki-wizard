# tests/test_anki.py
import pytest

from anki_wizard.anki import AnkiClient, AnkiError, AnkiNotRunning
from tests.fake_anki import FakeAnki


def test_version_returns_protocol_version():
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        assert AnkiClient(fake.url).version() == 6


def test_connection_refused_raises_anki_not_running():
    # Port 1 is reserved and never listening.
    client = AnkiClient("http://127.0.0.1:1")
    with pytest.raises(AnkiNotRunning, match="Anki is not running"):
        client.version()


def test_error_field_raises_anki_error():
    with FakeAnki() as fake:
        fake.set_error("addNotes", "deck was not found")
        with pytest.raises(AnkiError, match="deck was not found"):
            AnkiClient(fake.url).add_notes("Deck", [])


def test_add_notes_returns_ids():
    with FakeAnki() as fake:
        fake.set_response("addNotes", [1001, 1002])
        ids = AnkiClient(fake.url).add_notes(
            "Deck",
            [
                {"front": "F1", "back": "B1", "tags": ["t"]},
                {"front": "F2", "back": "B2", "tags": []},
            ],
        )
        assert ids == [1001, 1002]


def test_add_notes_sends_basic_note_type_and_deck():
    with FakeAnki() as fake:
        fake.set_response("addNotes", [1001])
        AnkiClient(fake.url).add_notes(
            "Math::Analysis", [{"front": "F", "back": "B", "tags": ["m"]}]
        )
        note = fake.requests[-1]["params"]["notes"][0]
        assert note["deckName"] == "Math::Analysis"
        assert note["modelName"] == "Basic"
        assert note["fields"] == {"Front": "F", "Back": "B"}
        assert note["tags"] == ["m"]


def test_add_notes_partial_failure_returns_nulls():
    """A duplicate note comes back as null in the same position."""
    with FakeAnki() as fake:
        fake.set_response("addNotes", [1001, None, 1003])
        ids = AnkiClient(fake.url).add_notes(
            "Deck",
            [
                {"front": "F1", "back": "B1"},
                {"front": "F2", "back": "B2"},
                {"front": "F3", "back": "B3"},
            ],
        )
        assert ids == [1001, None, 1003]


def test_update_note_fields_sends_note_id():
    with FakeAnki() as fake:
        fake.set_response("updateNoteFields", None)
        AnkiClient(fake.url).update_note_fields(1001, "New F", "New B")
        note = fake.requests[-1]["params"]["note"]
        assert note["id"] == 1001
        assert note["fields"] == {"Front": "New F", "Back": "New B"}


def test_note_exists_true_when_found():
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [{"noteId": 1001, "fields": {}}])
        assert AnkiClient(fake.url).note_exists(1001) is True


def test_note_exists_false_when_deleted():
    """A deleted note comes back as an empty dict, not an error."""
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [{}])
        assert AnkiClient(fake.url).note_exists(1001) is False


def test_ensure_deck_creates_deck():
    with FakeAnki() as fake:
        fake.set_response("createDeck", 12345)
        AnkiClient(fake.url).ensure_deck("Math::Analysis")
        assert fake.requests[-1]["action"] == "createDeck"
        assert fake.requests[-1]["params"]["deck"] == "Math::Analysis"


def test_requests_use_protocol_version_6():
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        AnkiClient(fake.url).version()
        assert fake.requests[-1]["version"] == 6
