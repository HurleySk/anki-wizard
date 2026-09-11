"""The cheat sheet tools: propose, review, revise, show, render."""

from pathlib import Path

import pytest

from anki_wizard.cheatsheet import (
    formula_blocks,
    load_sheet,
    propose_formulas,
    render_cheatsheet,
    review_formulas,
    revise_formula,
)
from anki_wizard.paths import Paths
from anki_wizard.tools import ingest_source

FIXTURES = Path(__file__).parent / "fixtures"
COURSE = "Intro to Probability"
L1 = "Unit I: Foundations::L01 Events"
L2 = "Unit I: Foundations::L02 Expectation"


@pytest.fixture
def workspace(tmp_path):
    return Paths(root=tmp_path)


def scaling(**kw) -> dict:
    return {"tex": r"\mathbb{E}[aX] = a\,\mathbb{E}[X]", "label": "Scaling", **kw}


def variance(**kw) -> dict:
    return {"tex": r"\mathrm{Var}(X) = \mathbb{E}[X^2] - \mathbb{E}[X]^2",
            "label": "Variance", **kw}


# --- proposing ---------------------------------------------------------------


def test_propose_writes_to_the_course_sheet(workspace):
    result = propose_formulas(COURSE, [scaling(lecture=L2)], paths=workspace)
    assert result["added"] == 1
    (f,) = result["formulas"]
    assert f["id"] == "f-0001"
    assert f["state"] == "proposed"
    assert f["lecture"] == L2
    assert f["source"] is None
    assert workspace.cheatsheet_file("intro-to-probability").exists()


def test_propose_keys_on_the_top_level_deck(workspace):
    """One sheet per course, however deep the configured deck."""
    propose_formulas(COURSE + "::Unit I", [scaling()], paths=workspace)
    assert load_sheet(workspace.cheatsheet_file("intro-to-probability"))


def test_propose_merges_default_tags(workspace):
    result = propose_formulas(
        COURSE, [scaling(tags=["expectation"])], paths=workspace, default_tags=["6-041"]
    )
    assert result["formulas"][0]["tags"] == ["6-041", "expectation"]


def test_propose_records_a_document_source(workspace):
    ingest_source(FIXTURES / "slides.pdf", slug="slides", paths=workspace, dpi=50)
    result = propose_formulas(
        COURSE, [scaling()], paths=workspace, slug="slides", section_id="1"
    )
    assert result["formulas"][0]["source"] == {"slug": "slides", "section": "1", "pages": [1]}


def test_propose_records_a_conversation_source(workspace):
    """A topic slug with no document still says where the formula came up."""
    result = propose_formulas(COURSE, [scaling()], paths=workspace, slug="pset-3")
    assert result["formulas"][0]["source"] == {"slug": "pset-3", "section": None, "pages": []}


def test_propose_with_a_section_requires_ingestion(workspace):
    with pytest.raises(FileNotFoundError, match="not ingested"):
        propose_formulas(COURSE, [scaling()], paths=workspace, slug="nope", section_id="1")


@pytest.mark.parametrize(
    "proposal, message",
    [
        ({"tex": "", "label": "x"}, "tex"),
        ({"tex": "x", "label": " "}, "label"),
        ({"tex": r"\[x\]", "label": "ok"}, "delimiters"),
        ({"tex": "$x$", "label": "ok"}, "delimiters"),
        ({"tex": "x", "label": "Var(X) rule"}, "typeset only inside"),
        ({"tex": "x", "label": "ok", "note": "<i>iid</i>"}, "plain text"),
    ],
)
def test_propose_validates_before_writing(workspace, proposal, message):
    """A bad label would otherwise fail at render time, on every later change
    to the sheet, long after anyone could say which proposal was at fault."""
    with pytest.raises(ValueError, match=message):
        propose_formulas(COURSE, [scaling(), proposal], paths=workspace)
    assert not workspace.cheatsheet_file("intro-to-probability").exists()


def test_propose_refuses_a_formula_already_on_the_sheet(workspace):
    """The sheet must not balloon, and an exact repeat is the one duplicate a
    tool can catch. Whitespace does not make a formula different."""
    propose_formulas(COURSE, [scaling()], paths=workspace)
    again = {"tex": r"\mathbb{E}[aX]  =  a\,\mathbb{E}[X]", "label": "Linearity"}
    with pytest.raises(ValueError, match="already on the sheet as f-0001"):
        propose_formulas(COURSE, [again], paths=workspace)


def test_propose_refuses_a_repeat_within_the_batch(workspace):
    with pytest.raises(ValueError, match="twice in this batch"):
        propose_formulas(COURSE, [scaling(), scaling(label="Again")], paths=workspace)
    assert not workspace.cheatsheet_file("intro-to-probability").exists()


def test_a_rejected_formula_can_be_proposed_again(workspace):
    propose_formulas(COURSE, [scaling()], paths=workspace)
    review_formulas(COURSE, {"f-0001": "reject"}, paths=workspace)
    result = propose_formulas(COURSE, [scaling()], paths=workspace)
    assert result["formulas"][0]["id"] == "f-0002"


# --- reviewing and revising --------------------------------------------------


def test_review_approves_rejects_and_edits(workspace):
    propose_formulas(COURSE, [scaling(), variance(), scaling(tex="x", label="Third")],
                     paths=workspace)
    result = review_formulas(
        COURSE,
        {
            "f-0001": "approve",
            "f-0002": "reject",
            "f-0003": {"edit": {"label": "Renamed", "note": "if it exists"}, "then": "approve"},
        },
        paths=workspace,
    )
    assert result["updated"] == {"f-0001": "approved", "f-0002": "rejected", "f-0003": "approved"}
    sheet = load_sheet(workspace.cheatsheet_file("intro-to-probability"))
    assert sheet[2].label == "Renamed"
    assert sheet[2].note == "if it exists"
    assert sheet[2].history[-2]["action"] == "edited"


def test_review_rejects_an_unknown_action(workspace):
    propose_formulas(COURSE, [scaling()], paths=workspace)
    with pytest.raises(ValueError, match="unknown review action 'keep'"):
        review_formulas(COURSE, {"f-0001": "keep"}, paths=workspace)


def test_review_edits_are_checked_like_proposals(workspace):
    propose_formulas(COURSE, [scaling()], paths=workspace)
    with pytest.raises(ValueError, match="typeset only inside"):
        review_formulas(COURSE, {"f-0001": {"edit": {"label": "E[X] rule"}}}, paths=workspace)


def test_revise_edits_and_refiles(workspace):
    propose_formulas(COURSE, [scaling(lecture=L1)], paths=workspace)
    result = revise_formula(COURSE, "f-0001", paths=workspace, note=r"any \(a\)", lecture=L2)
    assert result == {"id": "f-0001", "state": "proposed", "message": "formula revised"}
    (f,) = load_sheet(workspace.cheatsheet_file("intro-to-probability"))
    assert f.note == r"any \(a\)"
    assert f.lecture == L2
    assert [h["action"] for h in f.history] == ["proposed", "edited", "refiled"]


def test_revise_names_a_missing_formula(workspace):
    with pytest.raises(ValueError, match="no formula 'f-0009'"):
        revise_formula(COURSE, "f-0009", paths=workspace, label="x")


# --- blocks ------------------------------------------------------------------


def test_blocks_group_by_lecture_with_unfiled_first(workspace):
    propose_formulas(
        COURSE,
        [
            scaling(lecture=L2),
            variance(lecture=L1),
            {"tex": "z", "label": "Unfiled"},
            {"tex": "w", "label": "Also L02", "lecture": L2},
        ],
        paths=workspace,
    )
    blocks = formula_blocks(COURSE, paths=workspace)
    assert [(b["type"], b.get("text") or b["label"]) for b in blocks] == [
        ("heading", "General"),
        ("formula", "Unfiled"),
        ("heading", L1),
        ("formula", "Variance"),
        ("heading", L2),
        ("formula", "Scaling"),
        ("formula", "Also L02"),
    ]


def test_blocks_carry_meta_unless_showing_the_sheet(workspace):
    """On a review page the id is how the user names an entry back; the
    printable sheet shows only what is approved and needs no ids."""
    propose_formulas(COURSE, [scaling(), variance()], paths=workspace)
    review_formulas(COURSE, {"f-0002": "approve"}, paths=workspace)

    proposed = formula_blocks(COURSE, paths=workspace, state="proposed")
    assert [b["label"] for b in proposed if b["type"] == "formula"] == ["Scaling"]
    assert proposed[1]["meta"] == "f-0001 · proposed"

    approved = formula_blocks(COURSE, paths=workspace, state="approved")
    assert [b["label"] for b in approved if b["type"] == "formula"] == ["Variance"]
    assert "meta" not in approved[1]


def test_blocks_by_id_keep_the_asked_order_and_name_a_missing_one(workspace):
    propose_formulas(COURSE, [scaling(), variance()], paths=workspace)
    blocks = formula_blocks(COURSE, paths=workspace, ids=["f-0002", "f-0001"])
    assert [b["label"] for b in blocks if b["type"] == "formula"] == ["Variance", "Scaling"]
    with pytest.raises(KeyError, match="f-0009"):
        formula_blocks(COURSE, paths=workspace, ids=["f-0009"])


def test_blocks_carry_the_note(workspace):
    propose_formulas(COURSE, [scaling(note=r"any \(a\)")], paths=workspace)
    assert formula_blocks(COURSE, paths=workspace)[1]["note"] == r"any \(a\)"


def test_blocks_for_an_empty_sheet(workspace):
    assert formula_blocks(COURSE, paths=workspace) == []


# --- the page ----------------------------------------------------------------


def test_render_writes_the_approved_sheet(workspace):
    propose_formulas(COURSE, [scaling(lecture=L2), variance()], paths=workspace)
    review_formulas(COURSE, {"f-0001": "approve"}, paths=workspace)
    result = render_cheatsheet(COURSE, paths=workspace, viewer="none")
    page = workspace.cheatsheet_page("intro-to-probability")
    assert result["path"] == str(page)
    assert result["formulas"] == 1
    html = page.read_text()
    assert "<title>Intro to Probability</title>" in html
    assert "Scaling" in html
    assert f"<h2>{L2}</h2>" in html
    assert "Variance" not in html
    assert 'class="formula-meta"' not in html


def test_review_and_revise_keep_the_page_current(workspace):
    """The page is derived from the YAML and is never allowed to go stale:
    the user may have its URL open in a tab and hit print."""
    propose_formulas(COURSE, [scaling()], paths=workspace)
    page = workspace.cheatsheet_page("intro-to-probability")
    assert not page.exists()

    review_formulas(COURSE, {"f-0001": "approve"}, paths=workspace)
    assert "Scaling" in page.read_text()

    revise_formula(COURSE, "f-0001", paths=workspace, label="Linearity")
    assert "Linearity" in page.read_text()

    review_formulas(COURSE, {"f-0001": "reject"}, paths=workspace)
    assert "Linearity" not in page.read_text()


def test_render_an_empty_sheet_still_makes_a_page(workspace):
    result = render_cheatsheet(COURSE, paths=workspace, viewer="none")
    assert result["formulas"] == 0
    assert workspace.cheatsheet_page("intro-to-probability").exists()
