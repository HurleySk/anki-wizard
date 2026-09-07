import yaml

from anki_wizard.config import Config, load_config


def test_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.anki_connect_url == "http://localhost:8765"
    assert cfg.deck == "anki-wizard"
    assert cfg.default_tags == []
    assert cfg.max_pages_per_read == 10


def test_file_values_override_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "anki_connect_url": "http://127.0.0.1:9999",
                "deck": "Math::Analysis",
                "default_tags": ["auto", "math"],
                "max_pages_per_read": 3,
            }
        )
    )
    cfg = load_config(p)
    assert cfg.anki_connect_url == "http://127.0.0.1:9999"
    assert cfg.deck == "Math::Analysis"
    assert cfg.default_tags == ["auto", "math"]
    assert cfg.max_pages_per_read == 3


def test_partial_file_keeps_other_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"deck": "Stats"}))
    cfg = load_config(p)
    assert cfg.deck == "Stats"
    assert cfg.anki_connect_url == "http://localhost:8765"


def test_empty_file_yields_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("")
    cfg = load_config(p)
    assert cfg == Config()
