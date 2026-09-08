import pytest

from anki_wizard.paths import Paths
from anki_wizard.tools import promote_pad, render_pad


@pytest.fixture
def workspace(tmp_path):
    return Paths(root=tmp_path)


def test_render_pad_writes_the_page(workspace):
    result = render_pad(
        [{"type": "prose", "text": "hello"}], paths=workspace, open_browser=False
    )
    assert workspace.pad_file().exists()
    assert "hello" in workspace.pad_file().read_text()
    assert result["path"] == str(workspace.pad_file())


def test_render_pad_overwrites_the_previous_pad(workspace):
    """Ephemeral by default: yesterday's derivation does not linger."""
    render_pad([{"type": "prose", "text": "OLD"}], paths=workspace, open_browser=False)
    render_pad([{"type": "prose", "text": "NEW"}], paths=workspace, open_browser=False)
    text = workspace.pad_file().read_text()
    assert "NEW" in text
    assert "OLD" not in text


def test_render_pad_creates_the_directory(workspace):
    render_pad([{"type": "prose", "text": "x"}], paths=workspace, open_browser=False)
    assert workspace.pad_dir().is_dir()


def test_render_pad_rejects_an_unknown_block(workspace):
    """A bad block must fail before a half-written page reaches disk."""
    with pytest.raises(ValueError, match="unknown block type"):
        render_pad([{"type": "nope"}], paths=workspace, open_browser=False)
    assert not workspace.pad_file().exists()


def test_promote_pad_moves_it_to_a_named_note(workspace):
    render_pad(
        [{"type": "prose", "text": "keep me"}], paths=workspace, open_browser=False
    )
    result = promote_pad("bernoulli-moments", paths=workspace)

    note = workspace.note_file("bernoulli-moments")
    assert note.exists()
    assert "keep me" in note.read_text()
    assert result["path"] == str(note)


def test_promote_pad_leaves_no_stale_pad(workspace):
    """Promotion moves rather than copies, so the next render starts clean."""
    render_pad([{"type": "prose", "text": "x"}], paths=workspace, open_browser=False)
    promote_pad("kept", paths=workspace)
    assert not workspace.pad_file().exists()


def test_promote_pad_without_a_pad_raises(workspace):
    """Better a clear error than an empty note nobody asked for."""
    with pytest.raises(FileNotFoundError, match="no pad"):
        promote_pad("nothing-here", paths=workspace)


def test_promote_pad_refuses_to_clobber_an_existing_note(workspace):
    """A kept note is not scratch space; overwriting one silently loses work."""
    render_pad([{"type": "prose", "text": "first"}], paths=workspace, open_browser=False)
    promote_pad("clt", paths=workspace)
    render_pad([{"type": "prose", "text": "second"}], paths=workspace, open_browser=False)

    with pytest.raises(FileExistsError, match="already exists"):
        promote_pad("clt", paths=workspace)
    assert "first" in workspace.note_file("clt").read_text()


def test_promote_pad_rejects_a_traversing_name(workspace):
    render_pad([{"type": "prose", "text": "x"}], paths=workspace, open_browser=False)
    with pytest.raises(ValueError, match="note name"):
        promote_pad("../escape", paths=workspace)
    # The name is validated before the pad is touched -- a rejected promotion
    # must not consume the pad the user was trying to keep.
    assert workspace.pad_file().exists()
