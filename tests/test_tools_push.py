from pathlib import Path

import pytest

from anki_wizard.anki import AnkiClient, AnkiNotRunning
from anki_wizard.cursor import load_cursor
from anki_wizard.ledger import load_ledger
from anki_wizard.paths import Paths
from anki_wizard.tools import (
    ingest_source,
    propose_cards,
    push_to_anki,
    review_cards,
    revise_card,
)
from tests.fake_anki import FakeAnki

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workspace(tmp_path):
    paths = Paths(root=tmp_path)
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=paths, dpi=50)
    return paths


def approved(paths, count=1, section="1"):
    propose_cards(
        "slides",
        [{"front": f"F{n}", "back": f"B{n}"} for n in range(1, count + 1)],
        section_id=section,
        paths=paths,
    )
    ids = [f"c-{n:04d}" for n in range(1, count + 1)]
    review_cards("slides", {cid: "approve" for cid in ids}, paths=paths)
    return ids


def test_push_sends_approved_cards_and_records_ids(workspace):
    approved(workspace, 2)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001, 1002])
        result = push_to_anki(
            "slides", AnkiClient(fake.url), deck="Deck", paths=workspace
        )
    assert result["pushed"] == 2
    assert result["failed"] == 0
    cards = load_ledger(workspace.ledger_file("slides"))
    assert [c.state for c in cards] == ["pushed", "pushed"]
    assert [c.anki_note_id for c in cards] == [1001, 1002]


def test_push_advances_cursor_on_full_success(workspace):
    approved(workspace, 1)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)
    cursor = load_cursor(workspace.cursor_file("slides"))
    assert cursor.covered == ["1"]
    assert cursor.position == "1"


def test_push_does_not_advance_cursor_on_partial_failure(workspace):
    """The spec is explicit: a partial push leaves the section uncovered."""
    approved(workspace, 2)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001, None])
        result = push_to_anki(
            "slides", AnkiClient(fake.url), deck="Deck", paths=workspace
        )
    assert result["pushed"] == 1
    assert result["failed"] == 1
    assert load_cursor(workspace.cursor_file("slides")).covered == []


def test_partial_failure_leaves_failed_card_approved(workspace):
    approved(workspace, 2)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001, None])
        push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)
    cards = {c.id: c for c in load_ledger(workspace.ledger_file("slides"))}
    assert cards["c-0001"].state == "pushed"
    assert cards["c-0002"].state == "approved"
    assert cards["c-0002"].history[-1]["action"] == "push-failed"


def test_repush_retries_only_failures(workspace):
    approved(workspace, 2)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001, None])
        push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)
        fake.set_response("addNotes", [1002])
        result = push_to_anki(
            "slides", AnkiClient(fake.url), deck="Deck", paths=workspace
        )
    assert result["pushed"] == 1
    sent = fake.requests[-1]["params"]["notes"]
    assert len(sent) == 1
    assert sent[0]["fields"]["Front"] == "F2"


def test_push_with_anki_closed_leaves_cards_approved(workspace):
    approved(workspace, 1)
    client = AnkiClient("http://127.0.0.1:1")
    with pytest.raises(AnkiNotRunning):
        push_to_anki("slides", client, deck="Deck", paths=workspace)
    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.state == "approved"


def test_push_with_nothing_approved_is_a_noop(workspace):
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        result = push_to_anki(
            "slides", AnkiClient(fake.url), deck="Deck", paths=workspace
        )
    assert result["pushed"] == 0
    assert result["message"] == "no approved cards to push"


def test_revise_updates_note_in_place(workspace):
    approved(workspace, 1)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)

        fake.set_response("notesInfo", [{"noteId": 1001, "fields": {}}])
        fake.set_response("updateNoteFields", None)
        result = revise_card(
            "slides", "c-0001", AnkiClient(fake.url), paths=workspace, front="Fixed"
        )
    assert result["state"] == "pushed"
    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.front == "Fixed"
    assert card.anki_note_id == 1001


def test_revise_marks_deleted_note_orphaned(workspace):
    approved(workspace, 1)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)

        fake.set_response("notesInfo", [{}])
        result = revise_card(
            "slides", "c-0001", AnkiClient(fake.url), paths=workspace, front="Fixed"
        )
    assert result["state"] == "orphaned"
    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.state == "orphaned"
    assert card.front == "F1", "content is not revised on an orphaned card"


def test_revise_unpushed_card_edits_ledger_only(workspace):
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    with FakeAnki() as fake:
        result = revise_card(
            "slides", "c-0001", AnkiClient(fake.url), paths=workspace, front="Fixed"
        )
    assert result["state"] == "proposed"
    assert fake.requests == [], "must not call Anki for a card never pushed"
