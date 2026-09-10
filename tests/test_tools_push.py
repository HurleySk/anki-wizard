from pathlib import Path

import pytest

from anki_wizard.anki import AnkiClient, AnkiNotRunning
from anki_wizard.cursor import load_cursor
from anki_wizard.ledger import adopt_note, load_ledger
from anki_wizard.models import AdoptedNote
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
    review_cards("slides", dict.fromkeys(ids, "approve"), paths=paths)
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


def test_push_reports_note_ids_when_the_ledger_cannot_be_saved(workspace, monkeypatch):
    """Anki and the ledger are separate stores with no shared transaction.

    If notes land but their ids are not recorded, the cards stay approved and
    the next push duplicates them. The ids must be in the error so the state
    can be repaired.
    """
    from anki_wizard.tools import LedgerNotSaved

    approved(workspace, 2)

    def unwritable(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr("anki_wizard.tools.save_ledger", unwritable)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001, 1002])
        with pytest.raises(LedgerNotSaved) as caught:
            push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)

    message = str(caught.value)
    # Every created id must be recoverable, not just the first.
    assert "1001" in message and "1002" in message
    assert "c-0001" in message and "c-0002" in message


def test_partial_push_still_covers_sections_that_fully_succeeded(workspace):
    """A failure in one section must not withhold coverage from another.

    The successful section's cards are now pushed, so they never re-enter the
    pending set. If the section were left uncovered here, nothing would ever
    cover it and the agent would be sent back to re-read work it had finished.
    """
    propose_cards("slides", [{"front": "F1", "back": "B1"}], section_id="1", paths=workspace)
    propose_cards("slides", [{"front": "F2", "back": "B2"}], section_id="2", paths=workspace)
    review_cards("slides", {"c-0001": "approve", "c-0002": "approve"}, paths=workspace)

    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001, None])  # section 2 fails
        result = push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)

    assert result["sections_covered"] == ["1"]
    covered = load_cursor(workspace.cursor_file("slides")).covered
    assert covered == ["1"], "section 1 fully succeeded and must be covered"


def test_failed_section_stays_uncovered_even_when_another_succeeds(workspace):
    propose_cards("slides", [{"front": "F1", "back": "B1"}], section_id="1", paths=workspace)
    propose_cards("slides", [{"front": "F2", "back": "B2"}], section_id="2", paths=workspace)
    review_cards("slides", {"c-0001": "approve", "c-0002": "approve"}, paths=workspace)

    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001, None])
        push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)

    assert "2" not in load_cursor(workspace.cursor_file("slides")).covered


def test_a_section_with_one_failure_stays_uncovered(workspace):
    """Two cards in the same section, one fails: the section is not covered."""
    approved(workspace, 2)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001, None])
        result = push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)
    assert result["sections_covered"] == []
    assert load_cursor(workspace.cursor_file("slides")).covered == []


def test_pushing_conversation_cards_needs_no_outline(workspace):
    """Conversation cards have no section, so they must not touch the cursor.

    Without the guard this reaches _require_outline for a slug that was never
    ingested and raises FileNotFoundError.
    """
    propose_cards(
        "conversation", [{"front": "F", "back": "B"}], section_id=None, paths=workspace
    )
    review_cards("conversation", {"c-0001": "approve"}, paths=workspace)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        result = push_to_anki(
            "conversation", AnkiClient(fake.url), deck="Deck", paths=workspace
        )
    assert result["pushed"] == 1
    assert result["sections_covered"] == []


def test_revise_leaves_ledger_untouched_when_anki_update_fails(workspace):
    """Anki is updated before the ledger, so the two cannot silently diverge.

    Inverting that order would leave the ledger claiming an edit that never
    reached the collection.
    """
    from anki_wizard.anki import AnkiError

    approved(workspace, 1)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)

        fake.set_response("notesInfo", [{"noteId": 1001, "fields": {}}])
        fake.set_error("updateNoteFields", "deck was not found")
        with pytest.raises(AnkiError):
            revise_card(
                "slides", "c-0001", AnkiClient(fake.url), paths=workspace, front="Fixed"
            )

    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.front == "F1", "ledger must not record an edit Anki rejected"


def test_rejecting_an_unpushable_duplicate_releases_its_section(workspace):
    """Anki rejects a duplicate on every retry, so the card can never be pushed.

    Rejecting it is how the user settles the section. Without that release the
    section stays "next" forever with no way past it -- and duplicates are the
    normal failure mode, so this is the likeliest real-world stall.
    """
    approved(workspace, 1)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [None])  # always a duplicate
        for _ in range(3):
            push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)
    assert load_cursor(workspace.cursor_file("slides")).covered == []

    review_cards("slides", {"c-0001": "reject"}, paths=workspace)
    assert load_cursor(workspace.cursor_file("slides")).covered == ["1"]


def test_a_section_is_not_covered_while_cards_await_review(workspace):
    """Proposed cards are outstanding work: the section is not settled yet."""
    propose_cards("slides", [{"front": "F1", "back": "B1"}], section_id="1", paths=workspace)
    propose_cards("slides", [{"front": "F2", "back": "B2"}], section_id="1", paths=workspace)
    review_cards("slides", {"c-0001": "approve"}, paths=workspace)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)
    assert load_cursor(workspace.cursor_file("slides")).covered == []

    review_cards("slides", {"c-0002": "reject"}, paths=workspace)
    assert load_cursor(workspace.cursor_file("slides")).covered == ["1"]


def test_reviewing_conversation_cards_touches_no_cursor(workspace):
    propose_cards(
        "conversation", [{"front": "F", "back": "B"}], section_id=None, paths=workspace
    )
    result = review_cards("conversation", {"c-0001": "approve"}, paths=workspace)
    assert result["sections_covered"] == []


def test_push_leaves_an_adopted_note_in_the_ledger_untouched(workspace):
    """A ledger can hold a Card and an AdoptedNote side by side.

    push_to_anki reads and rewrites the whole ledger file, so a filtering
    mistake there would silently drop the adoption record -- the only trail
    an edit to a foreign note leaves -- on the next unrelated push.
    """
    ledger_path = workspace.ledger_file("slides")
    adopted = adopt_note(
        ledger_path,
        note_id=999,
        model="Basic",
        deck="Some Deck",
        fields=["Front", "Back"],
    )
    approved(workspace, 1)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Deck", paths=workspace)

    entries = load_ledger(ledger_path)
    adopted_entries = [e for e in entries if isinstance(e, AdoptedNote)]
    assert adopted_entries == [adopted]
