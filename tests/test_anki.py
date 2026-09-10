# tests/test_anki.py
import base64

import pytest

from anki_wizard.anki import (
    AnkiClient,
    AnkiError,
    AnkiNotResponding,
    AnkiNotRunning,
)
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
        assert note["modelName"] == "Basic with Why"
        assert note["fields"] == {"Front": "F", "Back": "B", "Why": ""}
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
        assert note["fields"] == {"Front": "New F", "Back": "New B", "Why": ""}


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


def test_note_exists_false_when_a_different_note_comes_back():
    """This call guards an overwrite, so a mismatched id must not read as True.

    Anki recycles note ids. Answering True about some other note would send
    updateNoteFields at a card the user actually studies from.
    """
    with FakeAnki() as fake:
        fake.set_response("notesInfo", [{"noteId": 999, "fields": {}}])
        assert AnkiClient(fake.url).note_exists(1001) is False


def test_read_timeout_raises_anki_not_responding(monkeypatch):
    """A stalled Anki is not a closed Anki: the retry advice differs.

    Anki serves AnkiConnect on its GUI thread, so a sync or a modal dialog
    stalls the response. That is a read timeout, which is not a subclass of
    ConnectionError and so would otherwise escape uncaught.
    """
    monkeypatch.setattr("anki_wizard.anki.TIMEOUT_SECONDS", 0.05)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.delay_seconds = 0.5
        with pytest.raises(AnkiNotResponding, match="may already have been applied"):
            AnkiClient(fake.url).version()


def test_non_json_response_raises_anki_error():
    """Something else listening on 8765 must not surface as a JSONDecodeError."""
    with FakeAnki() as fake:
        fake.raw_body = b"<html>not anki</html>"
        with pytest.raises(AnkiError, match="did not return JSON"):
            AnkiClient(fake.url).version()


def test_non_200_status_raises_anki_error():
    """AnkiConnect answers 200 even for protocol errors, so 500 means not-Anki."""
    with FakeAnki() as fake:
        fake.raw_body = b"server error"
        fake.status = 500
        with pytest.raises(AnkiError, match="expected 200"):
            AnkiClient(fake.url).version()


def test_add_notes_rejects_a_card_missing_content():
    with FakeAnki() as fake:
        fake.set_response("addNotes", [1001])
        with pytest.raises(AnkiError, match="missing back"):
            AnkiClient(fake.url).add_notes("d", [{"front": "F", "back": ""}])


def test_add_notes_rejects_a_length_mismatch():
    """Ids are matched to cards by position, so a short list must not pass."""
    with FakeAnki() as fake:
        fake.set_response("addNotes", [1001])
        with pytest.raises(AnkiError, match="Cannot match ids to cards"):
            AnkiClient(fake.url).add_notes(
                "d", [{"front": "F1", "back": "B1"}, {"front": "F2", "back": "B2"}]
            )


def test_unstubbed_action_is_an_error_not_a_silent_none():
    """Guards the fake itself: a forgotten stub must fail the test, not pass."""
    with FakeAnki() as fake, pytest.raises(AnkiError, match="unsupported action"):
        AnkiClient(fake.url).version()


def _sent(fake, action: str) -> dict:
    """The params of the last request for an action."""
    return [r for r in fake.requests if r["action"] == action][-1]["params"]


def test_model_names_returns_the_collections_note_types():
    with FakeAnki() as fake:
        fake.set_response("modelNames", ["Basic", "Cloze"])
        assert AnkiClient(fake.url).model_names() == ["Basic", "Cloze"]
        assert _sent(fake, "modelNames") == {}


def test_deck_names_returns_the_tree():
    with FakeAnki() as fake:
        fake.set_response("deckNames", ["Default", "Stats", "Stats::Unit I"])
        client = AnkiClient(fake.url)
        assert client.deck_names() == ["Default", "Stats", "Stats::Unit I"]


def test_retrieve_media_file_decodes_base64():
    """AnkiConnect returns media base64-encoded; callers want the bytes."""
    with FakeAnki() as fake:
        fake.set_response("retrieveMediaFile", base64.b64encode(b"PNGDATA").decode())
        client = AnkiClient(fake.url)
        assert client.retrieve_media_file("figure.png") == b"PNGDATA"
        assert _sent(fake, "retrieveMediaFile") == {"filename": "figure.png"}


def test_retrieve_media_file_returns_none_when_absent():
    """A missing file comes back as False, not an error, so it must be checked."""
    with FakeAnki() as fake:
        fake.set_response("retrieveMediaFile", False)
        client = AnkiClient(fake.url)
        assert client.retrieve_media_file("gone.png") is None


def test_retrieve_media_file_returns_empty_bytes_for_an_empty_file():
    """An existing 0-byte file decodes to '', which is falsy but not missing.

    Testing truthiness rather than the False sentinel would misreport a
    truncated download or interrupted sync as a file that was never there.
    """
    with FakeAnki() as fake:
        fake.set_response("retrieveMediaFile", "")
        client = AnkiClient(fake.url)
        assert client.retrieve_media_file("empty.png") == b""


def test_retrieve_media_file_raises_anki_error_on_malformed_payload():
    """A non-base64 response must not leak a raw binascii.Error past AnkiError."""
    with FakeAnki() as fake:
        fake.set_response("retrieveMediaFile", "<html>error</html>")
        client = AnkiClient(fake.url)
        with pytest.raises(AnkiError, match="figure"):
            client.retrieve_media_file("figure.png")


def test_retrieve_media_file_raises_anki_error_on_non_ascii_payload():
    """A non-ASCII character fails encoding before base64 ever runs.

    That raises a plain ValueError rather than binascii.Error, a distinct
    path from the malformed-payload case above -- catching only
    binascii.Error would let this one escape uncontained. Reachable in
    practice: JSON carries non-ASCII natively, so something other than
    AnkiConnect answering on this port could return a localized error string.
    """
    with FakeAnki() as fake:
        fake.set_response(
            "retrieveMediaFile", "Fehler: Datei nicht gefunden — überprüfen"
        )
        client = AnkiClient(fake.url)
        with pytest.raises(AnkiError, match="figure"):
            client.retrieve_media_file("figure.png")


def test_create_model_sends_fields_templates_and_css():
    with FakeAnki() as fake:
        fake.set_response("createModel", {"name": "Basic with Why"})
        AnkiClient(fake.url).create_model(
            "Basic with Why",
            ["Front", "Back", "Why"],
            front="{{Front}}",
            back="{{FrontSide}}{{Back}}",
            css=".card { color: black; }",
        )

    params = _sent(fake, "createModel")
    assert params["modelName"] == "Basic with Why"
    assert params["inOrderFields"] == ["Front", "Back", "Why"]
    assert params["css"] == ".card { color: black; }"
    assert params["cardTemplates"] == [
        {"Name": "Card 1", "Front": "{{Front}}", "Back": "{{FrontSide}}{{Back}}"}
    ]


def test_find_notes_returns_matching_ids():
    with FakeAnki() as fake:
        fake.set_response("findNotes", [1, 2, 3])
        found = AnkiClient(fake.url).find_notes('note:Basic deck:"anki-wizard"')
        assert found == [1, 2, 3]
        assert _sent(fake, "findNotes") == {"query": 'note:Basic deck:"anki-wizard"'}


def test_notes_info_returns_the_records_for_the_ids():
    with FakeAnki() as fake:
        fake.set_response(
            "notesInfo",
            [
                {"noteId": 1, "modelName": "Basic", "fields": {}, "tags": ["a"]},
                {"noteId": 2, "modelName": "Basic", "fields": {}, "tags": []},
            ],
        )
        info = AnkiClient(fake.url).notes_info([1, 2])

    assert [record["noteId"] for record in info] == [1, 2]
    assert _sent(fake, "notesInfo") == {"notes": [1, 2]}


def test_update_note_model_sends_one_note_object():
    """The real action takes a single note dict, not a batch and not a field map."""
    with FakeAnki() as fake:
        fake.set_response("updateNoteModel", None)
        AnkiClient(fake.url).update_note_model(
            1001,
            "Basic with Why",
            {"Front": "F", "Back": "B", "Why": ""},
            ["stats-ch1"],
        )

    assert _sent(fake, "updateNoteModel") == {
        "note": {
            "id": 1001,
            "modelName": "Basic with Why",
            "fields": {"Front": "F", "Back": "B", "Why": ""},
            "tags": ["stats-ch1"],
        }
    }


def test_update_note_fields_by_name_sends_exactly_what_it_is_given():
    """The general writer must not invent Front/Back/Why on a foreign note."""
    with FakeAnki() as fake:
        fake.set_response("updateNoteFields", None)
        client = AnkiClient(fake.url)
        client.update_note_fields_by_name(1234, {"Text": "new", "Answer": "a"})

        sent = fake.requests[-1]
        assert sent["action"] == "updateNoteFields"
        assert sent["params"]["note"]["id"] == 1234
        assert sent["params"]["note"]["fields"] == {"Text": "new", "Answer": "a"}


def test_update_note_fields_by_name_refuses_an_empty_change():
    """An empty write would be a no-op round trip that reads as success."""
    with FakeAnki() as fake:
        client = AnkiClient(fake.url)
        with pytest.raises(AnkiError, match="no fields"):
            client.update_note_fields_by_name(1234, {})
