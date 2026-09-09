"""Cloze deletion counting.

Editing a cloze field changes how many cards a note generates. Removing a
deletion deletes a card in Anki and takes its review history with it, which is
unrecoverable -- so the numbers this module returns gate every foreign edit.
"""

from anki_wizard.cloze import cloze_numbers


def test_no_clozes_is_an_empty_set():
    assert cloze_numbers("just ordinary text") == set()


def test_single_deletion():
    assert cloze_numbers("the {{c1::mean}} of X") == {1}


def test_several_distinct_deletions():
    text = "{{c1::A}} and {{c2::B}} and {{c3::C}}"
    assert cloze_numbers(text) == {1, 2, 3}


def test_repeated_number_counts_once():
    """One card is generated per distinct number, not per occurrence."""
    assert cloze_numbers("{{c1::A}} then {{c1::B}}") == {1}


def test_hint_syntax_is_recognised():
    """Anki allows {{c1::answer::hint}}; the hint must not hide the deletion."""
    assert cloze_numbers("{{c1::answer::a hint}}") == {1}


def test_multi_digit_numbers():
    assert cloze_numbers("{{c10::A}} {{c2::B}}") == {2, 10}


def test_nested_braces_in_math_do_not_confuse_it():
    """Card content is MathJax, so braces inside a deletion are routine."""
    text = r"{{c1::\(\frac{a}{b}\)}} and {{c2::x^{2}}}"
    assert cloze_numbers(text) == {1, 2}


def test_malformed_markup_is_ignored():
    assert cloze_numbers("{{c::no number}} {{cx::bad}} {{1::no c}}") == set()
