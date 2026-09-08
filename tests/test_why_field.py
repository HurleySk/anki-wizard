from anki_wizard.anki import NOTE_TYPE, AnkiClient
from anki_wizard.models import Card, CardSource
from tests.fake_anki import FakeAnki


def _sent(server, action: str) -> dict:
    """The params of the last request for an action."""
    return [r for r in server.requests if r["action"] == action][-1]["params"]


def test_card_defaults_to_no_why():
    """Optional: most cards do not earn one, and a blank field is noise."""
    card = Card(id="c-0001", front="f", back="b", source=CardSource(slug="s"))
    assert card.why is None


def test_add_notes_sends_the_why_field():
    with FakeAnki() as server:
        server.set_response("addNotes", [1])
        AnkiClient(server.url).add_notes(
            "Deck", [{"front": "f", "back": "b", "why": "because"}]
        )

    note = _sent(server, "addNotes")["notes"][0]
    assert note["fields"]["Why"] == "because"
    assert note["modelName"] == NOTE_TYPE


def test_add_notes_sends_an_empty_why_when_absent():
    """The field must be present but empty -- Anki rejects an unknown field
    name, and omitting a declared field is not the same as leaving it blank."""
    with FakeAnki() as server:
        server.set_response("addNotes", [1])
        AnkiClient(server.url).add_notes("Deck", [{"front": "f", "back": "b"}])

    assert _sent(server, "addNotes")["notes"][0]["fields"]["Why"] == ""


def test_a_missing_why_is_not_an_incomplete_card():
    """front and back are required; why is not. Pushing without one must work."""
    with FakeAnki() as server:
        server.set_response("addNotes", [1])
        ids = AnkiClient(server.url).add_notes("Deck", [{"front": "f", "back": "b"}])
    assert ids == [1]


def test_update_note_fields_carries_the_why():
    with FakeAnki() as server:
        server.set_response("updateNoteFields", None)
        AnkiClient(server.url).update_note_fields(123, "f", "b", why="revised")

    assert _sent(server, "updateNoteFields")["note"]["fields"]["Why"] == "revised"
