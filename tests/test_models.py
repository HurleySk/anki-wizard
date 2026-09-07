from anki_wizard.models import Card, CardSource, Section, Outline, Cursor


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
