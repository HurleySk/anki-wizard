"""Browser-layer tests. Skipped when Playwright or its Chromium is missing."""

import pytest

from anki_wizard.edx import (
    NO_SOLUTION_LINE,
    LoginRequired,
    capture_unit,
    fetch_units,
    unit_url,
)
from anki_wizard.paths import Paths
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
