"""Ledgers holding adopted notes alongside authored cards."""

import pytest
import yaml

from anki_wizard.ledger import (
    adopt_note,
    load_ledger,
    record,
    save_ledger,
)
from anki_wizard.models import AdoptedNote, Card, CardSource


def a_card(card_id="c-0001"):
    return Card(
        id=card_id,
        front="State the CLT.",
        back="The sample mean converges in distribution.",
        source=CardSource(slug="stats-ch1", section="1", pages=[1, 2]),
    )


def an_adopted_note(note_id=1739985246842):
    return AdoptedNote(
        note_id=note_id,
        model="Cloze Overlapping",
        deck="Intro to Probability::Unit I",
        fields=["Text", "Answer"],
    )


def test_an_existing_ledger_with_no_kind_key_still_loads(tmp_path):
    """Back-compat is the whole reason kind defaults to card.

    Every ledger already on disk was written before this key existed.
    """
    path = tmp_path / "stats-ch1.yaml"
    path.write_text(
        yaml.safe_dump([
            {
                "id": "c-0001",
                "front": "F",
                "back": "B",
                "source": {"slug": "stats-ch1", "section": "1", "pages": [1, 2]},
                "state": "pushed",
                "anki_note_id": 555,
            }
        ])
    )
    loaded = load_ledger(path)
    assert len(loaded) == 1
    assert isinstance(loaded[0], Card)
    assert loaded[0].anki_note_id == 555


LEGACY_ROW = {
    "id": "c-0007",
    "front": "State Hoeffding's inequality.",
    "back": "\\(\\mathbb{P}(|\\bar X_n - \\mu| \\ge t) \\le 2e^{-2nt^2/(b-a)^2}\\)",
    "source": {"slug": "stats-ch1", "section": "12", "pages": [12, 13]},
    "why": "The bound is non-asymptotic, so it holds for every \\(n\\).",
    "lecture": "Unit I: Introduction to Statistics::L02 Probability Redux",
    "state": "pushed",
    "tags": ["stats-ch1", "hoeffding", "18-6501x"],
    "anki_note_id": 1739985246842,
    "history": [
        {"at": "2025-01-02T10:00:00+00:00", "action": "proposed"},
        {"at": "2025-01-02T10:05:00+00:00", "action": "approved"},
        {"at": "2025-01-02T10:06:00+00:00", "action": "pushed"},
    ],
}


def test_a_fully_populated_legacy_card_keeps_every_field(tmp_path):
    """The 53 entries already on disk are this shape, not the minimal one."""
    path = tmp_path / "legacy.yaml"
    path.write_text(yaml.safe_dump([LEGACY_ROW], sort_keys=False, allow_unicode=True))

    card = load_ledger(path)[0]
    assert isinstance(card, Card)
    assert card.why == LEGACY_ROW["why"]
    assert card.lecture == LEGACY_ROW["lecture"]
    assert card.tags == LEGACY_ROW["tags"]
    assert card.history == LEGACY_ROW["history"]
    assert card.state == "pushed"
    assert card.anki_note_id == 1739985246842
    assert card.source == CardSource(slug="stats-ch1", section="12", pages=[12, 13])


def test_a_legacy_ledger_survives_a_load_save_cycle(tmp_path):
    """The first write to a user's ledger rewrites every entry in it."""
    path = tmp_path / "legacy.yaml"
    path.write_text(yaml.safe_dump([LEGACY_ROW], sort_keys=False, allow_unicode=True))

    before = load_ledger(path)
    save_ledger(path, before)
    assert load_ledger(path) == before


def test_a_mixed_ledger_round_trips(tmp_path):
    path = tmp_path / "mixed.yaml"
    save_ledger(path, [a_card(), an_adopted_note()])
    loaded = load_ledger(path)

    assert isinstance(loaded[0], Card)
    assert isinstance(loaded[1], AdoptedNote)
    assert loaded[1].note_id == 1739985246842
    assert loaded[1].model == "Cloze Overlapping"


def test_saved_adopted_entries_carry_their_kind(tmp_path):
    path = tmp_path / "adopted.yaml"
    save_ledger(path, [an_adopted_note()])
    raw = yaml.safe_load(path.read_text())
    assert raw[0]["kind"] == "adopted"
    assert "front" not in raw[0]


def test_saved_cards_carry_their_kind_too(tmp_path):
    """Written explicitly so a hand-edited ledger reads unambiguously."""
    path = tmp_path / "cards.yaml"
    save_ledger(path, [a_card()])
    assert yaml.safe_load(path.read_text())[0]["kind"] == "card"


def test_an_unreadable_adopted_entry_names_its_position(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump([{"kind": "adopted", "model": "Basic"}]))
    with pytest.raises(ValueError, match="entry 0"):
        load_ledger(path)


def test_a_single_field_written_as_a_string_is_refused(tmp_path):
    """Refused rather than splatted: list("Text") is four bogus field names.

    Writing one field without the list is the obvious hand-edit, and these
    names are what an edit is checked against before it reaches Anki, so
    accepting the garbled form would weaken that check silently.
    """
    path = tmp_path / "scalar-fields.yaml"
    path.write_text(
        yaml.safe_dump(
            [{"kind": "adopted", "note_id": 1, "model": "M", "deck": "D",
              "fields": "Text"}]
        )
    )
    with pytest.raises(ValueError, match="entry 0"):
        load_ledger(path)


def test_an_unknown_kind_is_rejected(tmp_path):
    path = tmp_path / "odd.yaml"
    path.write_text(yaml.safe_dump([{"kind": "sketch", "id": "c-0001"}]))
    with pytest.raises(ValueError, match="entry 0"):
        load_ledger(path)


def test_two_adopted_entries_for_one_note_are_rejected(tmp_path):
    """A repeat would make the second unreachable, so edits would land on the first."""
    path = tmp_path / "dupe.yaml"
    save_ledger(path, [an_adopted_note(999), an_adopted_note(999)])
    with pytest.raises(ValueError, match="999"):
        load_ledger(path)


def test_a_card_and_a_note_sharing_a_number_do_not_collide(tmp_path):
    """Card ids and note ids live in different namespaces."""
    path = tmp_path / "namespaces.yaml"
    save_ledger(path, [a_card("999"), an_adopted_note(999)])
    assert len(load_ledger(path)) == 2


def test_adopt_note_appends_and_records_history(tmp_path):
    path = tmp_path / "intro-to-probability.yaml"
    note = adopt_note(
        path,
        note_id=42,
        model="Cloze Overlapping",
        deck="Intro to Probability",
        fields=["Text", "Answer"],
    )
    assert note.history[-1]["action"] == "adopted"

    loaded = load_ledger(path)
    assert len(loaded) == 1
    assert loaded[0].note_id == 42


def test_adopting_a_note_twice_returns_the_existing_entry(tmp_path):
    """Adoption happens on first edit, and a note gets edited more than once."""
    path = tmp_path / "intro-to-probability.yaml"
    adopt_note(path, note_id=42, model="M", deck="D", fields=["Text"])
    again = adopt_note(path, note_id=42, model="M", deck="D", fields=["Text"])

    assert len(load_ledger(path)) == 1
    assert len([h for h in again.history if h["action"] == "adopted"]) == 1


def test_adopt_note_leaves_existing_cards_alone(tmp_path):
    """Adoption appends to a ledger that already holds authored cards."""
    path = tmp_path / "stats-ch1.yaml"
    save_ledger(path, [a_card()])
    adopt_note(path, note_id=42, model="M", deck="D", fields=["Text"])

    loaded = load_ledger(path)
    assert [type(e) for e in loaded] == [Card, AdoptedNote]
    assert loaded[0] == a_card()


def test_record_works_on_an_adopted_note():
    """History is an audit trail for adopted notes too."""
    noted = record(an_adopted_note(), "edited")
    assert noted.history[-1]["action"] == "edited"
