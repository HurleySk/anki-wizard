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
