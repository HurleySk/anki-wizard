import pytest

from anki_wizard.paths import Paths
from anki_wizard.tools import promote_pad, render_pad


@pytest.fixture
def workspace(tmp_path):
    return Paths(root=tmp_path)


def test_render_pad_writes_the_page(workspace):
    result = render_pad(
        [{"type": "prose", "text": "hello"}], paths=workspace, viewer="none"
    )
    assert workspace.pad_file().exists()
    assert "hello" in workspace.pad_file().read_text()
    assert result["path"] == str(workspace.pad_file())


def test_render_pad_overwrites_the_previous_pad(workspace):
    """Ephemeral by default: yesterday's derivation does not linger."""
    render_pad([{"type": "prose", "text": "OLD"}], paths=workspace, viewer="none")
    render_pad([{"type": "prose", "text": "NEW"}], paths=workspace, viewer="none")
    text = workspace.pad_file().read_text()
    assert "NEW" in text
    assert "OLD" not in text


def test_render_pad_creates_the_directory(workspace):
    render_pad([{"type": "prose", "text": "x"}], paths=workspace, viewer="none")
    assert workspace.pad_dir().is_dir()


def test_render_pad_rejects_an_unknown_block(workspace):
    """A bad block must fail before a half-written page reaches disk."""
    with pytest.raises(ValueError, match="unknown block type"):
        render_pad([{"type": "nope"}], paths=workspace, viewer="none")
    assert not workspace.pad_file().exists()


def test_promote_pad_moves_it_to_a_named_note(workspace):
    render_pad(
        [{"type": "prose", "text": "keep me"}], paths=workspace, viewer="none"
    )
    result = promote_pad("bernoulli-moments", paths=workspace)

    note = workspace.note_file("bernoulli-moments")
    assert note.exists()
    assert "keep me" in note.read_text()
    assert result["path"] == str(note)


def test_promote_pad_leaves_no_stale_pad(workspace):
    """Promotion moves rather than copies, so the next render starts clean."""
    render_pad([{"type": "prose", "text": "x"}], paths=workspace, viewer="none")
    promote_pad("kept", paths=workspace)
    assert not workspace.pad_file().exists()


def test_promote_pad_without_a_pad_raises(workspace):
    """Better a clear error than an empty note nobody asked for."""
    with pytest.raises(FileNotFoundError, match="no pad"):
        promote_pad("nothing-here", paths=workspace)


def test_promote_pad_refuses_to_clobber_an_existing_note(workspace):
    """A kept note is not scratch space; overwriting one silently loses work."""
    render_pad([{"type": "prose", "text": "first"}], paths=workspace, viewer="none")
    promote_pad("clt", paths=workspace)
    render_pad([{"type": "prose", "text": "second"}], paths=workspace, viewer="none")

    with pytest.raises(FileExistsError, match="already exists"):
        promote_pad("clt", paths=workspace)
    assert "first" in workspace.note_file("clt").read_text()


def test_promote_pad_rejects_a_traversing_name(workspace):
    render_pad([{"type": "prose", "text": "x"}], paths=workspace, viewer="none")
    with pytest.raises(ValueError, match="note name"):
        promote_pad("../escape", paths=workspace)
    # The name is validated before the pad is touched -- a rejected promotion
    # must not consume the pad the user was trying to keep.
    assert workspace.pad_file().exists()


def test_render_pad_reports_the_viewer_it_used(workspace):
    result = render_pad([{"type": "prose", "text": "x"}], paths=workspace, viewer="none")
    assert (result["viewer"], result["opened"]) == ("none", False)


def test_render_pad_embeds_an_animation(workspace):
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.animation import FuncAnimation
    from matplotlib.figure import Figure

    fig = Figure(figsize=(2, 2))
    (line,) = fig.add_subplot(1, 1, 1).plot([0, 1], [0, 1])
    anim = FuncAnimation(fig, lambda k: (line,), frames=2, blit=True)

    render_pad(
        [{"type": "animation", "animation": anim}], paths=workspace, viewer="none"
    )
    assert "function Animation" in workspace.pad_file().read_text()


# --- card_blocks: ledger cards on the pad ---------------------------------


@pytest.fixture
def proposals(workspace):
    from anki_wizard.tools import propose_cards

    propose_cards(
        "pset-3",
        [
            {"front": "F1 \\(x^2\\)", "back": "B1<br><b>bold</b>", "why": "W1",
             "tags": ["clt"], "lecture": "Unit I::L02"},
            {"front": "F2", "back": "B2"},
        ],
        section_id=None,
        paths=workspace,
    )
    return workspace


def test_card_blocks_are_note_blocks_with_the_card_fields(proposals):
    from anki_wizard.tools import card_blocks

    blocks = card_blocks("pset-3", paths=proposals)
    assert [b["type"] for b in blocks] == ["note", "note"]
    first = blocks[0]
    assert first["fields"][:3] == [
        ("Front", "F1 \\(x^2\\)"),
        ("Back", "B1<br><b>bold</b>"),
        ("Why", "W1"),
    ]
    assert "c-0001" in first["title"]
    assert "proposed" in first["title"]
    assert "Unit I::L02" in first["title"]


def test_card_blocks_omit_an_empty_why(proposals):
    from anki_wizard.tools import card_blocks

    second = card_blocks("pset-3", paths=proposals)[1]
    assert not any(name == "Why" for name, _ in second["fields"])


def test_card_blocks_carry_tags_as_a_field(proposals):
    from anki_wizard.tools import card_blocks

    first = card_blocks("pset-3", paths=proposals)[0]
    assert ("Tags", "clt") in first["fields"]


def test_card_blocks_filter_by_id_and_state(proposals):
    from anki_wizard.tools import card_blocks, review_cards

    review_cards("pset-3", {"c-0002": "reject"}, paths=proposals)
    assert [b["title"] for b in card_blocks("pset-3", paths=proposals, state="proposed")] \
        == [b["title"] for b in card_blocks("pset-3", paths=proposals, ids=["c-0001"])]
    assert len(card_blocks("pset-3", paths=proposals, state="rejected")) == 1


def test_card_blocks_reject_an_unknown_id(proposals):
    from anki_wizard.tools import card_blocks

    with pytest.raises(KeyError, match="c-0099"):
        card_blocks("pset-3", paths=proposals, ids=["c-0099"])


def test_card_blocks_render_html_fields_unescaped(proposals):
    """The whole point: a card field is HTML, so <b> and \\( must reach the page intact."""
    from anki_wizard.tools import card_blocks

    render_pad(card_blocks("pset-3", paths=proposals), paths=proposals, viewer="none")
    page = proposals.pad_file().read_text()
    assert "<b>bold</b>" in page
    assert "\\(x^2\\)" in page
    assert "&lt;b&gt;" not in page
