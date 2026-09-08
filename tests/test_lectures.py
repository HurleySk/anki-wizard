"""Cards carry the lecture they belong to, and push routes them to subdecks.

A lecture is recorded per card rather than per source so that one document can
span several lectures and one lecture can draw on several documents -- including
conversation cards, which have no document at all.
"""

from pathlib import Path

import pytest

from anki_wizard.anki import AnkiClient
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


def approve(paths, proposals, section="1", slug="slides"):
    before = len(load_ledger(paths.ledger_file(slug)))
    propose_cards(slug, proposals, section_id=section, paths=paths)
    cards = load_ledger(paths.ledger_file(slug))[before:]
    review_cards(slug, {c.id: "approve" for c in cards}, paths=paths)
    return [c.id for c in cards]


def decks_pushed_to(fake):
    return [
        r["params"]["notes"][0]["deckName"]
        for r in fake.requests
        if r["action"] == "addNotes"
    ]


def test_a_lecture_given_at_proposal_time_reaches_the_ledger(workspace):
    propose_cards(
        "slides",
        [{"front": "F", "back": "B", "lecture": "L01 What is Statistics?"}],
        section_id="1",
        paths=workspace,
    )
    card = load_ledger(workspace.ledger_file("slides"))[0]
    assert card.lecture == "L01 What is Statistics?"


def test_a_card_without_a_lecture_has_none(workspace):
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    assert load_ledger(workspace.ledger_file("slides"))[0].lecture is None


def test_push_sends_a_lectures_cards_to_its_subdeck(workspace):
    approve(workspace, [{"front": "F", "back": "B", "lecture": "L01 Intro"}])
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Stats", paths=workspace)
    assert decks_pushed_to(fake) == ["Stats::L01 Intro"]


def test_push_sends_a_card_without_a_lecture_to_the_base_deck(workspace):
    """The lecture is optional, so an unassigned card must still be pushable."""
    approve(workspace, [{"front": "F", "back": "B"}])
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Stats", paths=workspace)
    assert decks_pushed_to(fake) == ["Stats"]


def test_push_groups_cards_by_lecture(workspace):
    """One addNotes call per deck, each carrying only that deck's cards."""
    approve(workspace, [{"front": "F1", "back": "B", "lecture": "L01 A"}])
    approve(workspace, [{"front": "F2", "back": "B", "lecture": "L02 B"}], section="2")
    approve(workspace, [{"front": "F3", "back": "B", "lecture": "L01 A"}], section="3")
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_sequence("addNotes", [[1001, 1003], [1002]])
        result = push_to_anki(
            "slides", AnkiClient(fake.url), deck="Stats", paths=workspace
        )
    assert result["pushed"] == 3
    assert sorted(decks_pushed_to(fake)) == ["Stats::L01 A", "Stats::L02 B"]

    sent = {
        r["params"]["notes"][0]["deckName"]: [n["fields"]["Front"] for n in r["params"]["notes"]]
        for r in fake.requests
        if r["action"] == "addNotes"
    }
    assert sent == {"Stats::L01 A": ["F1", "F3"], "Stats::L02 B": ["F2"]}


def test_note_ids_land_on_the_right_cards_across_decks(workspace):
    """The bug grouping invites: ids returned per deck applied by global index.

    Card 2 is in the second deck, so a naive zip over the concatenated results
    would give it the id meant for card 3.
    """
    approve(workspace, [{"front": "F1", "back": "B", "lecture": "L01 A"}])
    approve(workspace, [{"front": "F2", "back": "B", "lecture": "L02 B"}], section="2")
    approve(workspace, [{"front": "F3", "back": "B", "lecture": "L01 A"}], section="3")
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_sequence("addNotes", [[1001, 1003], [1002]])
        push_to_anki("slides", AnkiClient(fake.url), deck="Stats", paths=workspace)
    by_front = {c.front: c.anki_note_id for c in load_ledger(workspace.ledger_file("slides"))}
    assert by_front == {"F1": 1001, "F2": 1002, "F3": 1003}


def test_each_subdeck_is_created_before_its_cards_are_sent(workspace):
    approve(workspace, [{"front": "F1", "back": "B", "lecture": "L01 A"}])
    approve(workspace, [{"front": "F2", "back": "B", "lecture": "L02 B"}], section="2")
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_sequence("addNotes", [[1001], [1002]])
        push_to_anki("slides", AnkiClient(fake.url), deck="Stats", paths=workspace)
    created = [
        r["params"]["deck"] for r in fake.requests if r["action"] == "createDeck"
    ]
    assert sorted(created) == ["Stats::L01 A", "Stats::L02 B"]


def test_a_failure_in_one_deck_leaves_the_other_decks_pushed(workspace):
    """Grouping must not turn one deck's duplicate into a whole-push failure."""
    approve(workspace, [{"front": "F1", "back": "B", "lecture": "L01 A"}])
    approve(workspace, [{"front": "F2", "back": "B", "lecture": "L02 B"}], section="2")
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_sequence("addNotes", [[None], [1002]])
        result = push_to_anki(
            "slides", AnkiClient(fake.url), deck="Stats", paths=workspace
        )
    assert (result["pushed"], result["failed"]) == (1, 1)
    states = {c.front: c.state for c in load_ledger(workspace.ledger_file("slides"))}
    assert states == {"F1": "approved", "F2": "pushed"}


def test_conversation_cards_can_carry_a_lecture(workspace):
    """The reason the lecture lives on the card: these have no document."""
    propose_cards(
        "pset-3",
        [{"front": "F", "back": "B", "lecture": "L01 Intro"}],
        section_id=None,
        paths=workspace,
    )
    review_cards("pset-3", {"c-0001": "approve"}, paths=workspace)
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("pset-3", AnkiClient(fake.url), deck="Stats", paths=workspace)
    assert decks_pushed_to(fake) == ["Stats::L01 Intro"]


def test_an_old_ledger_without_lectures_still_loads(workspace):
    """Every existing ledger predates this field; none may become unreadable."""
    workspace.ledger_file("slides").write_text(
        "- id: c-0001\n"
        "  front: F\n"
        "  back: B\n"
        "  source: {slug: slides}\n"
        "  state: pushed\n"
    )
    assert load_ledger(workspace.ledger_file("slides"))[0].lecture is None


def test_revise_can_assign_a_lecture_to_an_unpushed_card(workspace):
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    with FakeAnki() as fake:
        revise_card(
            "slides", "c-0001", AnkiClient(fake.url), paths=workspace,
            lecture="L01 Intro",
        )
    assert load_ledger(workspace.ledger_file("slides"))[0].lecture == "L01 Intro"
    assert [r["action"] for r in fake.requests] == []


def test_revise_moves_a_pushed_card_to_its_new_subdeck(workspace):
    """A misfiled card must be fixable, and moving it must not re-add it."""
    approve(workspace, [{"front": "F", "back": "B", "lecture": "L01 A"}])
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Stats", paths=workspace)

    with FakeAnki() as fake:
        fake.set_response("notesInfo", [{"noteId": 1001, "cards": [55], "fields": {}}])
        fake.set_response("createDeck", 1)
        fake.set_response("changeDeck", None)
        revise_card(
            "slides", "c-0001", AnkiClient(fake.url), paths=workspace,
            lecture="L02 B", deck="Stats",
        )
    moved = [r for r in fake.requests if r["action"] == "changeDeck"]
    assert len(moved) == 1
    assert moved[0]["params"] == {"cards": [55], "deck": "Stats::L02 B"}
    assert "addNotes" not in [r["action"] for r in fake.requests]
    assert load_ledger(workspace.ledger_file("slides"))[0].lecture == "L02 B"


def test_revising_content_without_a_lecture_moves_nothing(workspace):
    """The lecture is optional on revise: omitting it must not clear the field."""
    approve(workspace, [{"front": "F", "back": "B", "lecture": "L01 A"}])
    with FakeAnki() as fake:
        fake.set_response("version", 6)
        fake.set_response("createDeck", 1)
        fake.set_response("addNotes", [1001])
        push_to_anki("slides", AnkiClient(fake.url), deck="Stats", paths=workspace)

    with FakeAnki() as fake:
        fake.set_response("notesInfo", [{"noteId": 1001, "cards": [55], "fields": {}}])
        fake.set_response("updateNoteFields", None)
        revise_card(
            "slides", "c-0001", AnkiClient(fake.url), paths=workspace,
            front="edited", deck="Stats",
        )
    assert "changeDeck" not in [r["action"] for r in fake.requests]
    card = load_ledger(workspace.ledger_file("slides"))[0]
    assert (card.front, card.lecture) == ("edited", "L01 A")
