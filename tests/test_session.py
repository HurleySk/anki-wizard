from pathlib import Path

import yaml

from anki_wizard.session import Session

FIXTURES = Path(__file__).parent / "fixtures"


def test_session_uses_defaults_without_config(tmp_path):
    s = Session(root=tmp_path)
    assert s.config.deck == "anki-wizard"
    assert s.paths.root == tmp_path
    assert s.client.url == "http://localhost:8765"


def test_session_reads_config_file(tmp_path):
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "deck": "Math::Analysis",
                "anki_connect_url": "http://127.0.0.1:9999",
                "default_tags": ["auto"],
                "max_pages_per_read": 2,
            }
        )
    )
    s = Session(root=tmp_path)
    assert s.config.deck == "Math::Analysis"
    assert s.client.url == "http://127.0.0.1:9999"
    assert s.config.default_tags == ["auto"]


def test_session_read_applies_configured_page_cap(tmp_path):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"max_pages_per_read": 1}))
    s = Session(root=tmp_path)
    s.ingest(FIXTURES / "outlined.pdf", slug="outlined", dpi=50)
    result = s.read("outlined", "1.2")
    assert len(result["pages"]) == 1
    assert result["truncated"] is True


def test_session_propose_applies_default_tags(tmp_path):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"default_tags": ["auto"]}))
    s = Session(root=tmp_path)
    s.ingest(FIXTURES / "slides.pdf", slug="slides", dpi=50)
    result = s.propose("slides", [{"front": "F", "back": "B"}], section_id="1")
    assert result["cards"][0]["tags"] == ["auto"]


def test_session_pad_writes_the_page(tmp_path):
    s = Session(root=tmp_path)
    s.pad([{"type": "prose", "text": "from a session"}], viewer="none")
    assert "from a session" in s.paths.pad_file().read_text()


def test_session_keep_promotes_the_pad(tmp_path):
    s = Session(root=tmp_path)
    s.pad([{"type": "prose", "text": "worth keeping"}], viewer="none")
    s.keep("lln")
    assert "worth keeping" in s.paths.note_file("lln").read_text()


def test_session_pad_uses_the_configured_viewer(tmp_path):
    (tmp_path / "config.yaml").write_text("pad_viewer: none\n")
    s = Session(root=tmp_path)
    assert s.pad([{"type": "prose", "text": "x"}])["viewer"] == "none"


def test_session_pad_viewer_argument_overrides_config(tmp_path):
    (tmp_path / "config.yaml").write_text("pad_viewer: browser\n")
    s = Session(root=tmp_path)
    assert s.pad([{"type": "prose", "text": "x"}], viewer="none")["viewer"] == "none"
