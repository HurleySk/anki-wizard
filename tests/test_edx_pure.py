import pytest

from anki_wizard.edx import (
    NO_SOLUTION_LINE,
    block_hint,
    existing_manifest,
    new_manifest,
    outline_from_manifest,
    parse_course_url,
    save_manifest,
    sequence_url,
    unit_url,
    units_from_sequence,
)

URL = (
    "https://courses.learn.mit.edu/learn/course/course-v1:MITxT+18.6501x+3T2026/"
    "block-v1:MITxT+18.6501x+3T2026+type@sequential+block@prob_linalg_diag/"
    "block-v1:MITxT+18.6501x+3T2026+type@vertical+block@prob_linalg_diag-tab1"
)
SEQUENTIAL = "block-v1:MITxT+18.6501x+3T2026+type@sequential+block@prob_linalg_diag"


def test_parse_course_url_returns_lms_origin_and_sequential():
    assert parse_course_url(URL) == ("https://courses.learn.mit.edu", SEQUENTIAL)


def test_parse_course_url_accepts_a_sequential_without_a_vertical():
    url = URL.rsplit("/", 1)[0]
    assert parse_course_url(url) == ("https://courses.learn.mit.edu", SEQUENTIAL)


def test_parse_course_url_refuses_a_url_without_a_sequential():
    with pytest.raises(ValueError, match="type@sequential"):
        parse_course_url(
            "https://courses.learn.mit.edu/learn/course/course-v1:MITxT+18.6501x+3T2026/home"
        )


def test_parse_course_url_refuses_a_non_http_url():
    with pytest.raises(ValueError, match=r"https?"):
        parse_course_url("file:///tmp/x")


def test_sequence_url_and_unit_url():
    assert sequence_url("https://lms.test", SEQUENTIAL) == (
        f"https://lms.test/api/courseware/sequence/{SEQUENTIAL}"
    )
    assert unit_url("https://lms.test", "block-v1:T+X+1+type@vertical+block@u1") == (
        "https://lms.test/xblock/block-v1:T+X+1+type@vertical+block@u1"
    )


def test_units_from_sequence_keeps_order_and_titles():
    payload = {
        "display_name": "Problem Set 1",
        "items": [
            {
                "id": "block-v1:T+X+1+type@vertical+block@ps1-tab1",
                "page_title": "Diagonalization",
                "type": "vertical",
            },
            {
                "id": "block-v1:T+X+1+type@vertical+block@ps1-tab2",
                "page_title": "Eigenvalues",
                "type": "vertical",
            },
        ],
    }
    assert units_from_sequence(payload) == [
        {"id": "block-v1:T+X+1+type@vertical+block@ps1-tab1", "title": "Diagonalization"},
        {"id": "block-v1:T+X+1+type@vertical+block@ps1-tab2", "title": "Eigenvalues"},
    ]


def test_units_from_sequence_falls_back_to_the_block_name_for_a_title():
    payload = {"items": [{"id": "block-v1:T+X+1+type@vertical+block@ps1-tab3"}]}
    assert units_from_sequence(payload) == [
        {"id": "block-v1:T+X+1+type@vertical+block@ps1-tab3", "title": "ps1-tab3"}
    ]


def test_units_from_sequence_refuses_a_response_without_items():
    with pytest.raises(ValueError, match="items"):
        units_from_sequence({"detail": "Authentication credentials were not provided."})


def test_new_manifest_records_the_set_and_no_units():
    m = new_manifest(URL, "https://courses.learn.mit.edu", SEQUENTIAL)
    assert m == {
        "url": URL,
        "lms": "https://courses.learn.mit.edu",
        "sequential": SEQUENTIAL,
        "units": [],
    }


def test_manifest_round_trips_through_disk(tmp_path):
    path = tmp_path / "sources" / "pset" / "source.json"
    m = new_manifest(URL, "https://courses.learn.mit.edu", SEQUENTIAL)
    m["units"].append({"id": "u1", "title": "One", "pages": [1, 3]})
    save_manifest(path, m)
    assert existing_manifest(path, SEQUENTIAL) == m


def test_existing_manifest_is_none_when_absent(tmp_path):
    assert existing_manifest(tmp_path / "source.json", SEQUENTIAL) is None


def test_existing_manifest_refuses_a_different_set(tmp_path):
    path = tmp_path / "source.json"
    save_manifest(path, new_manifest(URL, "https://courses.learn.mit.edu", SEQUENTIAL))
    with pytest.raises(ValueError, match="holds"):
        existing_manifest(path, "block-v1:T+X+1+type@sequential+block@other")


def test_outline_from_manifest_is_one_section_per_unit():
    m = new_manifest(URL, "https://courses.learn.mit.edu", SEQUENTIAL)
    m["units"] = [
        {"id": "u1", "title": "Diagonalization", "pages": [1, 4]},
        {"id": "u2", "title": "Eigenvalues", "pages": [4, 4], "reason": "unit returned 404"},
        {"id": "u3", "title": "Trace", "pages": [4, 6]},
    ]
    o = outline_from_manifest("pset", m)
    assert o.slug == "pset"
    assert o.structure == "units"
    assert o.pages == 5
    assert [(s.id, s.title, s.pages) for s in o.sections] == [
        ("1", "Diagonalization", [1, 4]),
        ("2", "Eigenvalues", [4, 4]),
        ("3", "Trace", [4, 6]),
    ]
    assert o.page_numbers(o.sections[1]) == []


def test_outline_from_empty_manifest_has_no_pages():
    o = outline_from_manifest("pset", new_manifest(URL, "https://lms.test", SEQUENTIAL))
    assert o.pages == 0
    assert o.sections == []


def test_block_hint_names_the_type_and_carries_the_text():
    hint = block_hint({"type": "html", "text": "Let \\(A\\) be symmetric.", "solution_shown": False})
    assert hint == "[html block]\nLet \\(A\\) be symmetric.\n"


def test_block_hint_flags_a_problem_with_no_solution_shown():
    hint = block_hint(
        {"type": "problem", "text": "Compute \\(\\sigma^2\\).", "solution_shown": False}
    )
    assert hint.endswith(NO_SOLUTION_LINE + "\n")
    assert NO_SOLUTION_LINE == "(no solution was shown for this problem)"


def test_block_hint_says_nothing_extra_when_the_solution_is_shown():
    hint = block_hint(
        {"type": "problem", "text": "Compute.\nThe answer is 4.", "solution_shown": True}
    )
    assert hint == "[problem block]\nCompute.\nThe answer is 4.\n"


def test_session_ready_only_for_a_json_sequence_with_items():
    from anki_wizard.edx import session_ready

    api = "https://lms.test/api/courseware/sequence/x"
    ok = {"items": [{"id": "block-v1:T+X+1+type@vertical+block@u", "page_title": "U"}]}
    assert session_ready(200, "application/json", api, ok)
    assert not session_ready(302, "text/html", "https://lms.test/login?next=/", None)
    assert not session_ready(403, "application/json", api, {"detail": "no"})
    assert not session_ready(200, "application/json", api, {"detail": "no"})
