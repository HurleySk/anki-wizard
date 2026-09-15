"""Browser-layer tests. Skipped when Playwright or its Chromium is missing."""

import pytest

from anki_wizard.edx import LoginRequired, fetch_units
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
