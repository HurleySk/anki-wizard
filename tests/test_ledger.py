import pytest
import yaml

from anki_wizard.ledger import append_cards, load_ledger, next_card_id, save_ledger
from anki_wizard.models import Card, CardSource


def a_card(cid: str = "c-0001", **kw) -> Card:
    defaults = dict(
        id=cid,
        front="Front",
        back="Back",
        source=CardSource(slug="doc", section="1.1", pages=[3]),
    )
    defaults.update(kw)
    return Card(**defaults)


def test_load_missing_ledger_is_empty(tmp_path):
    assert load_ledger(tmp_path / "none.yaml") == []


def test_load_ledger_written_before_the_why_field_existed(tmp_path):
    """Real ledgers on disk predate `why`. An entry with no such key must still
    load, defaulting to None rather than raising."""
    p = tmp_path / "cards.yaml"
    p.write_text(
        "- id: c-0001\n"
        "  front: Front\n"
        "  back: Back\n"
        "  source:\n"
        "    slug: doc\n"
        "    section: '1.1'\n"
        "    pages: [3]\n"
        "  state: proposed\n"
        "  tags: []\n"
        "  anki_note_id: null\n"
        "  history: []\n"
    )
    (loaded,) = load_ledger(p)
    assert loaded.why is None


def test_round_trip_preserves_all_fields(tmp_path):
    p = tmp_path / "cards.yaml"
    card = a_card(
        state="pushed",
        tags=["math", "thm"],
        anki_note_id=1699887766123,
        history=[{"at": "2026-09-07T00:00:00Z", "action": "proposed"}],
    )
    save_ledger(p, [card])
    (loaded,) = load_ledger(p)
    assert loaded == card


def test_round_trip_preserves_conversation_source(tmp_path):
    p = tmp_path / "cards.yaml"
    card = a_card(source=CardSource(slug="conversation"))
    save_ledger(p, [card])
    (loaded,) = load_ledger(p)
    assert loaded.source.slug == "conversation"
    assert loaded.source.section is None
    assert loaded.source.pages == []


def test_next_card_id_starts_at_one():
    assert next_card_id([]) == "c-0001"


def test_next_card_id_continues_from_max(tmp_path):
    cards = [a_card("c-0001"), a_card("c-0007"), a_card("c-0003")]
    assert next_card_id(cards) == "c-0008"


def test_append_assigns_sequential_ids(tmp_path):
    p = tmp_path / "cards.yaml"
    save_ledger(p, [a_card("c-0001")])
    added = append_cards(
        p,
        [
            {"front": "F1", "back": "B1", "tags": ["t"]},
            {"front": "F2", "back": "B2", "tags": []},
        ],
        source=CardSource(slug="doc", section="1.2", pages=[9]),
    )
    assert [c.id for c in added] == ["c-0002", "c-0003"]
    all_cards = load_ledger(p)
    assert len(all_cards) == 3
    assert all_cards[1].front == "F1"
    assert all_cards[1].state == "proposed"
    assert all_cards[1].source.section == "1.2"


def test_append_records_history(tmp_path):
    p = tmp_path / "cards.yaml"
    (card,) = append_cards(
        p, [{"front": "F", "back": "B"}], source=CardSource(slug="conversation")
    )
    assert len(card.history) == 1
    assert card.history[0]["action"] == "proposed"
    assert "at" in card.history[0]


def test_edit_that_changes_nothing_records_no_history(tmp_path):
    """History is an audit trail: it records edits that happened, not asked for.

    A caller building this call from optional fields can pass all-None, or the
    values already present. Neither is an event.
    """
    from anki_wizard.ledger import edit_card

    card = Card(id="c-0001", front="F", back="B", source=CardSource(slug="s"))
    assert edit_card(card, front=None, back=None, tags=None) is card
    assert edit_card(card, front="F", back="B") is card
    assert card.history == []


def test_edit_that_changes_content_still_records(tmp_path):
    from anki_wizard.ledger import edit_card

    card = Card(id="c-0001", front="F", back="B", source=CardSource(slug="s"))
    edited = edit_card(card, front="Better")
    assert edited.front == "Better"
    assert [h["action"] for h in edited.history] == ["edited"]


def test_malformed_ledger_names_the_file_and_entry(tmp_path):
    """These files are meant to be read and hand-edited, so say what is wrong."""
    path = tmp_path / "cards" / "s.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("- id: c-0001\n  front: F\n")  # no back, no source
    with pytest.raises(ValueError, match="entry 0 is not a readable card"):
        load_ledger(path)


def test_save_ledger_is_atomic(tmp_path):
    """A crash mid-write must not truncate the source of truth.

    The ledger holds the Anki note ids of cards already in the collection, so a
    half-written file would make a re-push duplicate them.
    """
    import anki_wizard.atomic as atomic

    path = tmp_path / "cards" / "s.yaml"
    cards = [Card(id="c-0001", front="F", back="B", source=CardSource(slug="s"))]
    save_ledger(path, cards)
    original = path.read_text()

    real_replace = atomic.os.replace

    def boom(src, dst):
        raise OSError("simulated crash during rename")

    atomic.os.replace = boom
    try:
        with pytest.raises(OSError):
            save_ledger(path, cards + [Card(id="c-0002", front="F2", back="B2", source=CardSource(slug="s"))])
    finally:
        atomic.os.replace = real_replace

    assert path.read_text() == original, "existing ledger must survive a failed write"
    leftovers = [p.name for p in path.parent.iterdir() if p.name != path.name]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_a_proposal_can_carry_a_why(tmp_path):
    """A why written at proposal time must reach the ledger.

    Silently dropping it is worse than rejecting it: the caller sees a card
    created and has no signal that the reasoning went nowhere.
    """
    p = tmp_path / "cards.yaml"
    (card,) = append_cards(
        p,
        [{"front": "f", "back": "b", "why": "because the square of an indicator is itself"}],
        CardSource(slug="s"),
    )
    assert card.why == "because the square of an indicator is itself"
    # Round-trips rather than living only on the returned object.
    assert load_ledger(p)[0].why == card.why


def test_a_proposal_without_a_why_stays_none(tmp_path):
    p = tmp_path / "cards.yaml"
    (card,) = append_cards(p, [{"front": "f", "back": "b"}], CardSource(slug="s"))
    assert card.why is None


def test_duplicate_ids_are_refused(tmp_path):
    """An id names one card, or the tools disagree about which one it names.

    review_cards indexes by id and keeps the last match; revise_card scans and
    takes the first. A ledger with a repeated id silently sends edits to one
    card and approvals to another.
    """
    path = tmp_path / "cards.yaml"
    source = {"slug": "doc", "section": "1.1", "pages": [3]}
    path.write_text(
        yaml.safe_dump(
            [
                {"id": "c-0001", "front": "FIRST", "back": "B", "source": source},
                {"id": "c-0001", "front": "SECOND", "back": "B", "source": source},
            ]
        )
    )
    with pytest.raises(ValueError, match="c-0001"):
        load_ledger(path)
