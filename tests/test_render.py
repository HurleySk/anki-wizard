import pytest

from anki_wizard.render import render_html


def test_prose_block_appears_in_the_page():
    html = render_html([{"type": "prose", "text": "The mean of an indicator."}])
    assert "The mean of an indicator." in html


def test_math_delimiters_survive_unescaped():
    """The critical case: escaping a backslash breaks every formula silently.

    MathJax needs the literal \\( and \\[ sequences. If the renderer HTML-escapes
    its input wholesale, the page still loads and every equation renders as raw
    source, which is the failure this whole feature exists to avoid.
    """
    html = render_html([
        {"type": "prose", "text": r"Recall that \(X^2 = X\) for indicators."},
        {"type": "math", "tex": r"\mathrm{Var}(X) = p(1-p)"},
    ])
    assert r"\(X^2 = X\)" in html
    assert r"\[\mathrm{Var}(X) = p(1-p)\]" in html


def test_math_block_is_wrapped_in_display_delimiters():
    """A math block supplies bare TeX; the renderer adds the delimiters."""
    html = render_html([{"type": "math", "tex": "e^{i\\pi} = -1"}])
    assert r"\[e^{i\pi} = -1\]" in html


def test_html_in_prose_is_escaped():
    """Prose is text, not markup -- a stray < must not open a tag.

    Math delimiters are preserved because they are backslash sequences, which
    escaping leaves untouched. This is why escaping prose is safe.
    """
    html = render_html([{"type": "prose", "text": "if a < b and c > d"}])
    assert "a &lt; b" in html
    assert "c &gt; d" in html


def test_blocks_keep_their_order():
    html = render_html([
        {"type": "prose", "text": "FIRST"},
        {"type": "math", "tex": "x"},
        {"type": "prose", "text": "SECOND"},
    ])
    assert html.index("FIRST") < html.index("SECOND")


def test_page_is_standalone_html():
    html = render_html([{"type": "prose", "text": "hi"}])
    assert html.startswith("<!doctype html>")
    assert "</html>" in html
    assert "MathJax" in html


def test_unknown_block_type_raises():
    with pytest.raises(ValueError, match="unknown block type"):
        render_html([{"type": "interpretive-dance", "text": "no"}])


def test_empty_block_list_still_renders_a_page():
    html = render_html([])
    assert html.startswith("<!doctype html>")
