import pytest

from anki_wizard.paths import Paths
from anki_wizard.tools import render_pad


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
