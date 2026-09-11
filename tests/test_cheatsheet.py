"""The cheat sheet store: cheatsheets/<course-slug>.yaml."""

import pytest
import yaml

from anki_wizard.cheatsheet import (
    LEGAL_TRANSITIONS,
    edit_formula,
    index_of,
    load_sheet,
    next_formula_id,
    save_sheet,
    transition,
)
from anki_wizard.models import CardSource, Formula


def a_formula(fid: str = "f-0001", **kw) -> Formula:
    defaults = dict(id=fid, tex=r"\mathbb{E}[aX] = a\,\mathbb{E}[X]", label="Scaling")
    defaults.update(kw)
    return Formula(**defaults)


def test_load_missing_sheet_is_empty(tmp_path):
    assert load_sheet(tmp_path / "none.yaml") == []


def test_round_trip_preserves_all_fields(tmp_path):
    p = tmp_path / "sheet.yaml"
    f = a_formula(
        note=r"any constant \(a\)",
        lecture="Unit I::L02 Probability Redux",
        tags=["expectation"],
        source=CardSource(slug="stats-ch1", section="4", pages=[4]),
        state="approved",
        history=[{"at": "2026-09-11T00:00:00Z", "action": "proposed"}],
    )
    save_sheet(p, [f])
    assert load_sheet(p) == [f]


def test_sheet_is_readable_yaml(tmp_path):
    """The file is meant to be hand-editable, so it is plain YAML with
    the source written as a mapping or null, never a Python tag."""
    p = tmp_path / "sheet.yaml"
    save_sheet(p, [a_formula(), a_formula("f-0002", source=CardSource(slug="x"))])
    raw = yaml.safe_load(p.read_text())
    assert raw[0]["source"] is None
    assert raw[1]["source"] == {"slug": "x", "section": None, "pages": []}
    assert "!!python" not in p.read_text()


def test_unreadable_entry_names_the_file_and_position(tmp_path):
    p = tmp_path / "sheet.yaml"
    p.write_text("- id: f-0001\n  tex: x\n  label: ok\n- id: f-0002\n  tex: y\n")
    with pytest.raises(ValueError, match="sheet.yaml: entry 1"):
        load_sheet(p)


def test_duplicate_ids_are_refused_on_load(tmp_path):
    p = tmp_path / "sheet.yaml"
    save_sheet(p, [a_formula(), a_formula()])
    with pytest.raises(ValueError, match="entries 0 and 1 share the id 'f-0001'"):
        load_sheet(p)


def test_next_id_follows_the_highest():
    assert next_formula_id([]) == "f-0001"
    assert next_formula_id([a_formula("f-0003"), a_formula("f-0001")]) == "f-0004"


def test_index_of_names_the_course_when_missing():
    with pytest.raises(ValueError, match="no formula 'f-0009' on the sheet for 'stats'"):
        index_of([a_formula()], "f-0009", "stats")
    assert index_of([a_formula("f-0002"), a_formula("f-0001")], "f-0001", "stats") == 1


def test_transitions():
    """Approved is where an entry lives on the sheet; rejecting it is how it
    leaves. Nothing comes back from rejected."""
    assert LEGAL_TRANSITIONS == {
        "proposed": {"approved", "rejected"},
        "approved": {"rejected"},
        "rejected": set(),
    }
    f = transition(a_formula(), "approved")
    assert f.state == "approved"
    assert f.history[-1]["action"] == "approved"
    with pytest.raises(ValueError, match="illegal transition: approved -> proposed"):
        transition(f, "proposed")


def test_edit_records_only_real_changes():
    f = a_formula()
    assert edit_formula(f) is f
    assert edit_formula(f, label="Scaling") is f
    edited = edit_formula(f, note="constant \\(a\\)", tags=["expectation"])
    assert edited.note == "constant \\(a\\)"
    assert edited.tags == ["expectation"]
    assert edited.tex == f.tex
    assert edited.history[-1]["action"] == "edited"


def test_edit_preserves_state():
    f = transition(a_formula(), "approved")
    assert edit_formula(f, label="Linearity").state == "approved"


def test_rejected_cannot_be_edited():
    f = transition(a_formula(), "rejected")
    with pytest.raises(ValueError, match="terminal"):
        edit_formula(f, label="x")
