from anki_wizard.models import (
    AdoptedNote,
    Card,
    CardSource,
    Cursor,
    Formula,
    Outline,
    Section,
)


def test_card_source_from_document():
    src = CardSource(slug="folland", section="2.2", pages=[54])
    assert src.slug == "folland"
    assert src.section == "2.2"
    assert src.pages == [54]


def test_card_source_from_conversation():
    src = CardSource(slug="conversation")
    assert src.slug == "conversation"
    assert src.section is None
    assert src.pages == []


def test_card_defaults_to_proposed():
    card = Card(
        id="c-0001",
        front="What is a sigma-algebra?",
        back="A collection of subsets closed under complement and countable union.",
        source=CardSource(slug="conversation"),
    )
    assert card.state == "proposed"
    assert card.anki_note_id is None
    assert card.tags == []
    assert card.history == []


def test_section_holds_page_range():
    s = Section(id="2.1", title="Measurable Functions", pages=[43, 52])
    assert s.start == 43
    assert s.end == 52


def test_outline_lookup_by_id():
    o = Outline(
        slug="folland",
        pages=210,
        structure="sections",
        sections=[
            Section(id="2.1", title="Measurable Functions", pages=[43, 52]),
            Section(id="2.2", title="Integration", pages=[52, 61]),
        ],
    )
    assert o.section("2.2").title == "Integration"
    assert o.section("9.9") is None


def test_cursor_defaults_empty():
    c = Cursor()
    assert c.position is None
    assert c.covered == []


def test_adopted_note_holds_a_reference_not_content():
    """The ledger records which note and which fields, never the field values.

    A copy would drift the moment anyone edited in Anki, and there is no
    sync-back to repair it. A reference cannot show stale content.
    """
    note = AdoptedNote(
        note_id=1739985246842,
        model="Cloze Overlapping",
        deck="Intro to Probability::Unit I",
        fields=["Text", "Answer"],
    )
    assert note.note_id == 1739985246842
    assert note.tags == []
    assert note.history == []
    assert not hasattr(note, "front")


def test_adopted_notes_do_not_share_mutable_defaults():
    a = AdoptedNote(note_id=1, model="Basic", deck="D", fields=["Front"])
    b = AdoptedNote(note_id=2, model="Basic", deck="D", fields=["Front"])
    a.tags.append("x")
    assert b.tags == []


def test_formula_defaults():
    """A formula starts proposed, unfiled, and with its own history."""
    f = Formula(id="f-0001", tex=r"\mathbb{E}[aX] = a\,\mathbb{E}[X]", label="Scaling")
    assert f.state == "proposed"
    assert f.note is None
    assert f.lecture is None
    assert f.source is None
    assert f.tags == []
    assert f.history == []


def test_formulas_do_not_share_mutable_defaults():
    a = Formula(id="f-0001", tex="x", label="a")
    b = Formula(id="f-0002", tex="y", label="b")
    a.tags.append("x")
    assert b.tags == []
