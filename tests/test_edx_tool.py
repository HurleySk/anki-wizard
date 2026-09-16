"""The ingest_edx wrapper, tested without a browser: everything it refuses
happens before Chromium starts."""

import builtins

import pytest

from anki_wizard.edx import (
    LoginRequired,
    PlaywrightMissing,
    ingest_edx,
    new_manifest,
    save_manifest,
)
from anki_wizard.paths import Paths

LMS = "https://lms.test"
SEQUENTIAL = "block-v1:T+X+1+type@sequential+block@ps1"
COURSE_URL = f"{LMS}/learn/course/course-v1:T+X+1/{SEQUENTIAL}/block-v1:T+X+1+type@vertical+block@t1"


@pytest.fixture
def workspace(tmp_path):
    return Paths(root=tmp_path)


def test_ingest_edx_refuses_a_bad_url_before_anything_else(workspace):
    with pytest.raises(ValueError, match="type@sequential"):
        ingest_edx("https://lms.test/learn/course/course-v1:T+X+1/home", "pset", workspace)


def test_ingest_edx_refuses_a_second_set_on_a_slug(workspace):
    path = workspace.source_manifest("pset")
    save_manifest(path, new_manifest(COURSE_URL, LMS, "block-v1:T+X+1+type@sequential+block@other"))
    with pytest.raises(ValueError, match="already holds"):
        ingest_edx(COURSE_URL, "pset", workspace)


def test_ingest_edx_refuses_one_tab_on_a_url_naming_no_tab(workspace):
    bare = f"{LMS}/learn/course/course-v1:T+X+1/{SEQUENTIAL}"
    with pytest.raises(ValueError, match="names none"):
        ingest_edx(bare, "lec", workspace, one_tab=True)
    assert not workspace.source_dir("lec").exists()


def test_ingest_edx_requires_a_saved_session(workspace):
    with pytest.raises(LoginRequired, match=r"edx_login\.py"):
        ingest_edx(COURSE_URL, "pset", workspace)
    assert not workspace.source_dir("pset").exists()


def test_ingest_edx_names_the_setup_commands_when_playwright_is_missing(workspace, monkeypatch):
    workspace.edx_auth_state().parent.mkdir(parents=True)
    workspace.edx_auth_state().write_text("{}")
    real_import = builtins.__import__

    def no_playwright(name, *args, **kwargs):
        if name.startswith("playwright"):
            raise ImportError("No module named 'playwright'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_playwright)
    with pytest.raises(PlaywrightMissing, match="uv sync --extra web"):
        ingest_edx(COURSE_URL, "pset", workspace)
