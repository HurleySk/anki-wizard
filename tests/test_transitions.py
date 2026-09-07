import pytest

from anki_wizard.ledger import edit_card, transition
from anki_wizard.models import Card, CardSource


def a_card(state="proposed", **kw) -> Card:
    defaults = dict(
        id="c-0001",
        front="Front",
        back="Back",
        source=CardSource(slug="doc", section="1.1", pages=[3]),
        state=state,
    )
    defaults.update(kw)
    return Card(**defaults)


@pytest.mark.parametrize(
    "start,target",
    [
        ("proposed", "approved"),
        ("proposed", "rejected"),
        ("approved", "pushed"),
        ("approved", "rejected"),
        ("pushed", "orphaned"),
    ],
)
def test_legal_transitions(start, target):
    card = transition(a_card(start), target)
    assert card.state == target


@pytest.mark.parametrize(
    "start,target",
    [
        ("proposed", "pushed"),
        ("rejected", "approved"),
        ("pushed", "approved"),
        ("orphaned", "pushed"),
        ("pushed", "rejected"),
    ],
)
def test_illegal_transitions_raise(start, target):
    with pytest.raises(ValueError, match="illegal transition"):
        transition(a_card(start), target)


def test_transition_appends_history():
    card = transition(a_card("proposed"), "approved")
    assert card.history[-1]["action"] == "approved"
    assert "at" in card.history[-1]


def test_transition_to_pushed_records_note_id():
    card = transition(a_card("approved"), "pushed", anki_note_id=1699887766123)
    assert card.anki_note_id == 1699887766123


def test_transition_preserves_other_fields():
    original = a_card("proposed", tags=["math"])
    card = transition(original, "approved")
    assert card.id == original.id
    assert card.front == original.front
    assert card.tags == ["math"]


def test_transition_does_not_mutate_input():
    original = a_card("proposed")
    transition(original, "approved")
    assert original.state == "proposed"
    assert original.history == []


def test_edit_updates_text_and_keeps_state():
    card = edit_card(a_card("pushed", anki_note_id=99), front="New front")
    assert card.front == "New front"
    assert card.back == "Back"
    assert card.state == "pushed"
    assert card.anki_note_id == 99
    assert card.history[-1]["action"] == "edited"


def test_edit_can_change_tags():
    card = edit_card(a_card("proposed"), tags=["new"])
    assert card.tags == ["new"]


def test_edit_rejects_rejected_card():
    with pytest.raises(ValueError, match="terminal"):
        edit_card(a_card("rejected"), front="x")


def test_edit_rejects_orphaned_card_with_recovery_guidance():
    """Orphaned is terminal, so the message must say what to do instead."""
    with pytest.raises(ValueError, match="Propose a new card"):
        edit_card(a_card("orphaned"), front="x")
