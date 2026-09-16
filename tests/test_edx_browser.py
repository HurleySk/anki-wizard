"""Browser-layer tests. Skipped when Playwright or its Chromium is missing."""

import json

import pytest

from anki_wizard import edx
from anki_wizard.cursor import load_cursor
from anki_wizard.edx import (
    NO_SOLUTION_LINE,
    LoginRequired,
    capture_set,
    capture_unit,
    fetch_units,
    unit_url,
)
from anki_wizard.outline import load_outline
from anki_wizard.paths import Paths
from anki_wizard.tools import get_progress, read_section
from tests.fake_lms import SEQUENTIAL, FakeLms, unit_id

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            launched = playwright.chromium.launch()
        except sync_api.Error as exc:  # the package is installed, the browser is not
            pytest.skip(f"chromium is not installed: {exc}")
        yield launched
        launched.close()


@pytest.fixture
def context(browser):
    ctx = browser.new_context()
    yield ctx
    ctx.close()


@pytest.fixture
def workspace(tmp_path):
    return Paths(root=tmp_path)


def test_fetch_units_reads_the_sequence_api(context):
    with FakeLms([("ps1-tab1", "Diagonalization"), ("ps1-tab2", "Eigenvalues")]) as lms:
        page = context.new_page()
        assert fetch_units(page, lms.url, SEQUENTIAL) == [
            {"id": unit_id("ps1-tab1"), "title": "Diagonalization"},
            {"id": unit_id("ps1-tab2"), "title": "Eigenvalues"},
        ]


def test_fetch_units_raises_login_required_on_a_login_redirect(context):
    with FakeLms([("ps1-tab1", "Diagonalization")], logged_in=False) as lms:
        page = context.new_page()
        with pytest.raises(LoginRequired, match=r"edx_login\.py"):
            fetch_units(page, lms.url, SEQUENTIAL)


def _open_unit(context, lms, name="ps1-tab1"):
    page = context.new_page()
    response = page.goto(unit_url(lms.url, unit_id(name)))
    return page, response


def test_capture_unit_writes_one_image_and_hint_per_block_skipping_video(context, workspace):
    with FakeLms([("ps1-tab1", "Diagonalization")]) as lms:
        page, _ = _open_unit(context, lms)
        workspace.ensure_source_dirs("pset")
        unit = {"id": unit_id("ps1-tab1"), "title": "Diagonalization"}
        entry = capture_unit(page, "pset", unit, first_page=1, paths=workspace)
    assert entry == {"id": unit_id("ps1-tab1"), "title": "Diagonalization", "pages": [1, 5]}
    for n in (1, 2, 3, 4):
        assert workspace.page_image("pset", n).exists()
        assert workspace.page_text("pset", n).exists()
    assert not workspace.page_image("pset", 5).exists()
    assert workspace.page_text("pset", 1).read_text().startswith("[html block]\n")
    assert workspace.page_text("pset", 2).read_text().startswith("[problem block]\n")


def test_capture_unit_numbers_from_first_page(context, workspace):
    with FakeLms([("ps1-tab1", "Diagonalization")]) as lms:
        page, _ = _open_unit(context, lms)
        workspace.ensure_source_dirs("pset")
        unit = {"id": unit_id("ps1-tab1"), "title": "T"}
        entry = capture_unit(page, "pset", unit, first_page=7, paths=workspace)
    assert entry["pages"] == [7, 11]
    assert workspace.page_image("pset", 7).exists()
    assert not workspace.page_image("pset", 1).exists()


def test_capture_unit_reveals_solutions_and_substitutes_tex(context, workspace):
    with FakeLms([("ps1-tab1", "Diagonalization")]) as lms:
        page, _ = _open_unit(context, lms)
        workspace.ensure_source_dirs("pset")
        unit = {"id": unit_id("ps1-tab1"), "title": "T"}
        capture_unit(page, "pset", unit, first_page=1, paths=workspace)
    setup = workspace.page_text("pset", 1).read_text()
    assert "Let \\(A\\) be a symmetric matrix." in setup
    problem_1 = workspace.page_text("pset", 2).read_text()
    assert "Compute \\(\\sigma^2\\)." in problem_1
    assert "\\[\\sigma^2 = 4\\]" in problem_1
    assert "σ²" not in problem_1  # the rendered MathJax span is dropped, the TeX kept
    assert NO_SOLUTION_LINE not in problem_1
    problem_3 = workspace.page_text("pset", 4).read_text()
    assert problem_3.endswith(NO_SOLUTION_LINE + "\n")


def test_capture_unit_image_is_the_block_not_the_viewport(context, workspace):
    with FakeLms([("ps1-tab1", "Diagonalization")]) as lms:
        page, _ = _open_unit(context, lms)
        workspace.ensure_source_dirs("pset")
        unit = {"id": unit_id("ps1-tab1"), "title": "T"}
        capture_unit(page, "pset", unit, first_page=1, paths=workspace)
    setup = workspace.page_image("pset", 1).read_bytes()
    problem_1 = workspace.page_image("pset", 2).read_bytes()
    assert setup[:8] == b"\x89PNG\r\n\x1a\n"
    assert setup != problem_1


def test_capture_unit_records_a_reason_for_an_unreadable_page(context, workspace):
    with FakeLms([("ps1-tab2", "Eigenvalues")], unit_status={"ps1-tab2": 404}) as lms:
        page, response = _open_unit(context, lms, "ps1-tab2")
        workspace.ensure_source_dirs("pset")
        unit = {"id": unit_id("ps1-tab2"), "title": "Eigenvalues"}
        entry = capture_unit(page, "pset", unit, first_page=3, paths=workspace, response=response)
    assert entry == {
        "id": unit_id("ps1-tab2"),
        "title": "Eigenvalues",
        "pages": [3, 3],
        "reason": "unit page answered 404",
    }
    assert not workspace.page_image("pset", 3).exists()


def test_capture_set_writes_manifest_outline_cursor_and_pages(context, workspace):
    with FakeLms([("ps1-tab1", "Diagonalization"), ("ps1-tab2", "Eigenvalues")]) as lms:
        result = capture_set(context, lms.course_url, "pset", workspace)
        course_url = lms.course_url
    assert result["slug"] == "pset"
    assert result["structure"] == "units"
    assert result["pages"] == 8
    assert [s["title"] for s in result["sections"]] == ["Diagonalization", "Eigenvalues"]
    assert [s["pages"] for s in result["sections"]] == [[1, 5], [5, 9]]
    outline = load_outline(workspace.outline_file("pset"))
    assert outline.structure == "units"
    assert workspace.cursor_file("pset").exists()
    assert load_cursor(workspace.cursor_file("pset")).covered == []
    manifest = json.loads(workspace.source_manifest("pset").read_text())
    assert manifest["url"] == course_url
    assert manifest["sequential"] == SEQUENTIAL
    assert [u["pages"] for u in manifest["units"]] == [[1, 5], [5, 9]]


def test_capture_set_result_reads_through_the_ordinary_tools(context, workspace):
    with FakeLms([("ps1-tab1", "Diagonalization")]) as lms:
        capture_set(context, lms.course_url, "pset", workspace)
    progress = get_progress("pset", paths=workspace)
    assert progress["next"]["title"] == "Diagonalization"
    section = read_section("pset", None, paths=workspace)
    assert [p["number"] for p in section["pages"]] == [1, 2, 3, 4]
    assert section["pages"][1]["text"].startswith("[problem block]")


def test_capture_set_records_an_unreadable_tab_and_continues(context, workspace):
    units = [("ps1-tab1", "One"), ("ps1-tab2", "Two"), ("ps1-tab3", "Three")]
    with FakeLms(units, unit_status={"ps1-tab2": 404}) as lms:
        result = capture_set(context, lms.course_url, "pset", workspace)
    assert [s["pages"] for s in result["sections"]] == [[1, 5], [5, 5], [5, 9]]
    manifest = json.loads(workspace.source_manifest("pset").read_text())
    assert manifest["units"][1]["reason"] == "unit page answered 404"


def test_capture_set_resumes_after_an_interruption(context, workspace, monkeypatch):
    calls = []
    original = edx.capture_unit

    def interrupted(page, slug, unit, first_page, paths, response=None):
        calls.append(unit["id"])
        if len(calls) == 2:
            raise RuntimeError("browser died")
        return original(page, slug, unit, first_page, paths, response)

    monkeypatch.setattr(edx, "capture_unit", interrupted)
    with FakeLms([("ps1-tab1", "One"), ("ps1-tab2", "Two")]) as lms:
        with pytest.raises(RuntimeError, match="browser died"):
            capture_set(context, lms.course_url, "pset", workspace)
        manifest = json.loads(workspace.source_manifest("pset").read_text())
        assert [u["id"] for u in manifest["units"]] == [unit_id("ps1-tab1")]
        assert len(load_outline(workspace.outline_file("pset")).sections) == 1

        result = capture_set(context, lms.course_url, "pset", workspace)
    assert calls == [unit_id("ps1-tab1"), unit_id("ps1-tab2"), unit_id("ps1-tab2")]
    assert [s["pages"] for s in result["sections"]] == [[1, 5], [5, 9]]


def test_capture_set_with_one_tab_captures_only_the_url_s_vertical(context, workspace):
    units = [("ps1-tab1", "One"), ("ps1-tab2", "Two"), ("ps1-tab3", "Three")]
    with FakeLms(units) as lms:
        url = lms.course_url.replace("block@ps1-tab1", "block@ps1-tab2")
        result = capture_set(context, url, "lec", workspace, one_tab=True)
    assert [s["title"] for s in result["sections"]] == ["Two"]
    assert [s["pages"] for s in result["sections"]] == [[1, 5]]


def test_capture_set_with_one_tab_appends_the_next_tab_to_the_same_slug(context, workspace):
    units = [("ps1-tab1", "One"), ("ps1-tab2", "Two"), ("ps1-tab3", "Three")]
    with FakeLms(units) as lms:
        second = lms.course_url.replace("block@ps1-tab1", "block@ps1-tab2")
        capture_set(context, second, "lec", workspace, one_tab=True)
        third = lms.course_url.replace("block@ps1-tab1", "block@ps1-tab3")
        result = capture_set(context, third, "lec", workspace, one_tab=True)
    # Capture order, not tab order: the manifest appends, and page numbers follow.
    assert [s["title"] for s in result["sections"]] == ["Two", "Three"]
    assert [s["pages"] for s in result["sections"]] == [[1, 5], [5, 9]]


def test_capture_set_with_one_tab_is_idempotent_on_a_tab_already_held(context, workspace):
    with FakeLms([("ps1-tab1", "One"), ("ps1-tab2", "Two")]) as lms:
        url = lms.course_url.replace("block@ps1-tab1", "block@ps1-tab2")
        capture_set(context, url, "lec", workspace, one_tab=True)
        result = capture_set(context, url, "lec", workspace, one_tab=True)
    assert [s["title"] for s in result["sections"]] == ["Two"]


def test_capture_set_with_one_tab_refuses_a_url_with_no_vertical(context, workspace):
    with FakeLms([("ps1-tab1", "One")]) as lms:
        bare = lms.course_url.rsplit("/", 1)[0]
        with pytest.raises(ValueError, match="names none"):
            capture_set(context, bare, "lec", workspace, one_tab=True)
    assert not workspace.source_manifest("lec").exists()


def test_capture_set_with_one_tab_refuses_a_vertical_not_in_the_sequence(context, workspace):
    with FakeLms([("ps1-tab1", "One")]) as lms:
        url = lms.course_url.replace("block@ps1-tab1", "block@ps1-tab9")
        with pytest.raises(ValueError, match="ps1-tab9"):
            capture_set(context, url, "lec", workspace, one_tab=True)
    assert not workspace.source_manifest("lec").exists()


def test_capture_set_still_captures_every_tab_by_default(context, workspace):
    units = [("ps1-tab1", "One"), ("ps1-tab2", "Two"), ("ps1-tab3", "Three")]
    with FakeLms(units) as lms:
        result = capture_set(context, lms.course_url, "pset", workspace)
    assert [s["title"] for s in result["sections"]] == ["One", "Two", "Three"]


def test_capture_set_refuses_a_second_set_on_a_slug(context, workspace):
    with FakeLms([("ps1-tab1", "One")]) as lms:
        capture_set(context, lms.course_url, "pset", workspace)
        other = lms.course_url.replace("sequential+block@ps1", "sequential+block@ps2")
        with pytest.raises(ValueError, match="already holds"):
            capture_set(context, other, "pset", workspace)


def test_capture_set_raises_login_required_and_writes_nothing(context, workspace):
    with FakeLms([("ps1-tab1", "One")], logged_in=False) as lms, pytest.raises(LoginRequired):
        capture_set(context, lms.course_url, "pset", workspace)
    assert not workspace.source_manifest("pset").exists()
    assert not workspace.outline_file("pset").exists()


def test_capture_set_raises_login_required_when_the_session_expires_midway(context, workspace):
    with FakeLms([("ps1-tab1", "One"), ("ps1-tab2", "Two")]) as lms:
        original = edx.capture_unit

        def expire_after_first(page, slug, unit, first_page, paths, response=None):
            entry = original(page, slug, unit, first_page, paths, response)
            lms.logged_in = False
            return entry

        edx.capture_unit = expire_after_first
        try:
            with pytest.raises(LoginRequired, match="sign in at localhost"):
                capture_set(context, lms.course_url, "pset", workspace)
        finally:
            edx.capture_unit = original
    manifest = json.loads(workspace.source_manifest("pset").read_text())
    assert [u["id"] for u in manifest["units"]] == [unit_id("ps1-tab1")]
