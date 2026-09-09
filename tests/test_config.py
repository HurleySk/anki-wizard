import pytest
import yaml

from anki_wizard.config import Config, load_config


def test_defaults_when_file_missing(tmp_path):
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.anki_connect_url == "http://localhost:8765"
    assert cfg.deck == "anki-wizard"
    assert cfg.default_tags == []
    assert cfg.max_pages_per_read == 10
    assert cfg.pad_viewer == "vscode"


def test_file_values_override_defaults(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "anki_connect_url": "http://127.0.0.1:9999",
                "deck": "Math::Analysis",
                "default_tags": ["auto", "math"],
                "max_pages_per_read": 3,
                "pad_viewer": "browser",
            }
        )
    )
    cfg = load_config(p)
    assert cfg.anki_connect_url == "http://127.0.0.1:9999"
    assert cfg.deck == "Math::Analysis"
    assert cfg.default_tags == ["auto", "math"]
    assert cfg.max_pages_per_read == 3
    assert cfg.pad_viewer == "browser"


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


def test_unknown_key_is_an_error(tmp_path):
    """A misspelt key that does nothing is worse than one that complains.

    The setting silently keeps its default, and the user is left believing they
    configured something.
    """
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"deck": "Stats", "default_tag": ["oops"]}))
    with pytest.raises(ValueError) as caught:
        load_config(p)
    assert "default_tag" in str(caught.value)
    assert str(p) in str(caught.value)


def test_unknown_keys_are_all_named(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump({"nope": 1, "also_nope": 2}))
    with pytest.raises(ValueError) as caught:
        load_config(p)
    message = str(caught.value)
    assert "nope" in message and "also_nope" in message
