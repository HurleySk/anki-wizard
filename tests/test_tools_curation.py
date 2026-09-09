from pathlib import Path

import pytest

from anki_wizard.cursor import load_cursor
from anki_wizard.ledger import load_ledger
from anki_wizard.paths import Paths
from anki_wizard.tools import (
    get_progress,
    ingest_source,
    propose_cards,
    review_cards,
    skip_section,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workspace(tmp_path):
    paths = Paths(root=tmp_path)
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=paths, dpi=50)
    return paths


def test_propose_from_a_section(workspace):
    result = propose_cards(
        "slides",
        [{"front": "F1", "back": "B1", "tags": ["stat"]}],
        section_id="1",
        paths=workspace,
    )
    assert result["added"] == 1
    assert result["cards"][0]["id"] == "c-0001"
    assert result["cards"][0]["state"] == "proposed"
    assert result["cards"][0]["source"]["section"] == "1"
    assert result["cards"][0]["source"]["pages"] == [1]


def test_propose_applies_default_tags(workspace):
    result = propose_cards(
        "slides",
        [{"front": "F", "back": "B", "tags": ["own"]}],
        section_id="1",
        paths=workspace,
        default_tags=["auto"],
    )
    assert sorted(result["cards"][0]["tags"]) == ["auto", "own"]


def test_propose_from_conversation(workspace):
    result = propose_cards(
        "conversation", [{"front": "F", "back": "B"}], section_id=None, paths=workspace
    )
    assert result["cards"][0]["source"]["slug"] == "conversation"
    assert result["cards"][0]["source"]["section"] is None


def test_propose_rejects_unknown_section(workspace):
    with pytest.raises(ValueError, match="no section"):
        propose_cards(
            "slides", [{"front": "F", "back": "B"}], section_id="99", paths=workspace
        )


def test_propose_rejects_empty_front(workspace):
    with pytest.raises(ValueError, match="front and back"):
        propose_cards(
            "slides", [{"front": "", "back": "B"}], section_id="1", paths=workspace
        )


def test_review_approves(workspace):
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    result = review_cards("slides", {"c-0001": "approve"}, paths=workspace)
    assert result["updated"]["c-0001"] == "approved"
    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.state == "approved"


def test_review_rejects(workspace):
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    review_cards("slides", {"c-0001": "reject"}, paths=workspace)
    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.state == "rejected"


def test_review_edits_content_without_changing_state(workspace):
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    review_cards(
        "slides", {"c-0001": {"edit": {"front": "Better front"}}}, paths=workspace
    )
    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.front == "Better front"
    assert card.back == "B"
    assert card.state == "proposed"


def test_review_edit_can_set_the_why(workspace):
    """The edit dict takes the same fields as revise; why must not be dropped."""
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    review_cards(
        "slides", {"c-0001": {"edit": {"why": "because"}}}, paths=workspace
    )
    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.why == "because"


def test_review_edit_then_approve_in_one_call(workspace):
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    review_cards(
        "slides",
        {"c-0001": {"edit": {"front": "Fixed"}, "then": "approve"}},
        paths=workspace,
    )
    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.front == "Fixed"
    assert card.state == "approved"


def test_review_handles_several_cards(workspace):
    propose_cards(
        "slides",
        [{"front": "F1", "back": "B1"}, {"front": "F2", "back": "B2"}],
        section_id="1",
        paths=workspace,
    )
    review_cards(
        "slides", {"c-0001": "approve", "c-0002": "reject"}, paths=workspace
    )
    states = {c.id: c.state for c in load_ledger(workspace.ledger_file("slides"))}
    assert states == {"c-0001": "approved", "c-0002": "rejected"}


def test_review_approve_only_records_no_edit(workspace):
    """A decision with no "edit" key must not stamp a spurious edited entry."""
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    review_cards("slides", {"c-0001": {"then": "approve"}}, paths=workspace)
    (card,) = load_ledger(workspace.ledger_file("slides"))
    assert card.state == "approved"
    actions = [h["action"] for h in card.history]
    assert "edited" not in actions, actions


def test_review_unknown_card_raises(workspace):
    with pytest.raises(ValueError, match="no card"):
        review_cards("slides", {"c-9999": "approve"}, paths=workspace)


def test_review_illegal_action_raises(workspace):
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    review_cards("slides", {"c-0001": "reject"}, paths=workspace)
    with pytest.raises(ValueError, match="illegal transition"):
        review_cards("slides", {"c-0001": "approve"}, paths=workspace)


def test_propose_rejects_none_front_with_a_clear_message(workspace):
    """An agent assembling proposals from optional fields can produce None."""
    with pytest.raises(ValueError, match="front and back"):
        propose_cards(
            "slides", [{"front": None, "back": "B"}], section_id="1", paths=workspace
        )


def test_propose_from_an_uningested_slug(workspace):
    """A slug with no outline is source-less, the same as "conversation".

    Grouping conversation cards by topic is what keeps them findable once there
    are hundreds, so the outline-less path cannot be reserved for one magic
    slug name.
    """
    result = propose_cards(
        "pset-3", [{"front": "F", "back": "B"}], section_id=None, paths=workspace
    )
    assert result["cards"][0]["source"]["slug"] == "pset-3"
    assert result["cards"][0]["source"]["section"] is None
    assert result["cards"][0]["source"]["pages"] == []
    assert load_ledger(workspace.ledger_file("pset-3"))[0].front == "F"


def test_uningested_slug_keeps_its_own_ledger(workspace):
    """Separate slugs must not collide in one file."""
    propose_cards("pset-3", [{"front": "A", "back": "B"}], None, paths=workspace)
    propose_cards("pset-4", [{"front": "C", "back": "D"}], None, paths=workspace)
    assert [c.front for c in load_ledger(workspace.ledger_file("pset-3"))] == ["A"]
    assert [c.front for c in load_ledger(workspace.ledger_file("pset-4"))] == ["C"]


def test_propose_with_a_section_still_requires_ingestion(workspace):
    """Naming a section for an uningested slug is a mistake, not a free pass.

    Only section_id=None means "source-less". Asking for a section of a
    document that was never ingested should say so rather than silently
    dropping the provenance.
    """
    with pytest.raises(FileNotFoundError, match="not ingested"):
        propose_cards(
            "pset-3", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
        )


def test_skip_section_covers_it_without_cards(workspace):
    """A section with nothing worth carding must still be able to settle.

    Coverage is otherwise derived from cards, so a section that legitimately
    yields none -- a title slide, a section divider -- could never be covered
    and would block the cursor forever.
    """
    result = skip_section("slides", "1", reason="title slide", paths=workspace)
    assert result["covered"] == ["1"]
    assert get_progress("slides", paths=workspace)["covered"] == ["1"]


def test_skip_section_records_the_reason(workspace):
    """A skip is a judgment call, so it has to be auditable after the fact."""
    skip_section("slides", "1", reason="title slide", paths=workspace)
    cursor = load_cursor(workspace.cursor_file("slides"))
    assert cursor.skipped == {"1": "title slide"}


def test_skip_section_requires_a_reason(workspace):
    """Without a reason a skip is indistinguishable from a mistake."""
    with pytest.raises(ValueError, match="reason"):
        skip_section("slides", "1", reason="   ", paths=workspace)


def test_skip_section_rejects_unknown_section(workspace):
    with pytest.raises(ValueError, match="no section"):
        skip_section("slides", "99", reason="nothing here", paths=workspace)


def test_skip_section_is_idempotent(workspace):
    """Re-skipping must not duplicate coverage or stack reasons."""
    skip_section("slides", "1", reason="title slide", paths=workspace)
    skip_section("slides", "1", reason="still a title slide", paths=workspace)
    cursor = load_cursor(workspace.cursor_file("slides"))
    assert cursor.covered == ["1"]
    assert cursor.skipped == {"1": "still a title slide"}


def test_skip_section_refuses_a_section_that_has_cards(workspace):
    """Cards and a skip are contradictory claims about the same section.

    Silently skipping would strand proposals that the user never reviewed.
    """
    propose_cards(
        "slides", [{"front": "F", "back": "B"}], section_id="1", paths=workspace
    )
    with pytest.raises(ValueError, match="has cards"):
        skip_section("slides", "1", reason="changed my mind", paths=workspace)


def test_skipped_section_is_not_returned_as_next(workspace):
    """The whole point: a skipped section must not block the cursor."""
    skip_section("slides", "1", reason="title slide", paths=workspace)
    assert get_progress("slides", paths=workspace)["next"]["id"] == "2"


def test_progress_reports_skipped_sections(workspace):
    """Skips are visible in progress, so coverage can be read honestly."""
    skip_section("slides", "1", reason="title slide", paths=workspace)
    assert get_progress("slides", paths=workspace)["skipped"] == {"1": "title slide"}
