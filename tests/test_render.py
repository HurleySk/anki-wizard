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


def test_steps_render_in_order_with_numbers():
    html = render_html([{
        "type": "steps",
        "steps": [
            {"tex": r"\mathbb{E}[X] = \sum_x x\,\mathbb{P}(X=x)"},
            {"tex": r"= 0\cdot(1-p) + 1\cdot p"},
            {"tex": "= p"},
        ],
    }])
    # Searched by their marker, not as bare digits: the page's own CSS is full
    # of numbers (#33333a, 1.5rem), so a bare "3" matches the stylesheet first.
    positions = [html.index(f'class="step-num">{n}</span>') for n in (1, 2, 3)]
    assert positions == sorted(positions)
    assert r"\[= p\]" in html


def test_a_step_can_carry_its_justification():
    html = render_html([{
        "type": "steps",
        "steps": [
            {"tex": r"\mathbb{E}[X^2] = \mathbb{E}[X]", "why": "X is 0 or 1, so X^2 = X"},
        ],
    }])
    assert "X is 0 or 1, so X^2 = X" in html


def test_step_justification_is_escaped():
    html = render_html([{
        "type": "steps",
        "steps": [{"tex": "x", "why": "since a < b"}],
    }])
    assert "a &lt; b" in html


def test_steps_block_requires_at_least_one_step():
    with pytest.raises(ValueError, match="at least one step"):
        render_html([{"type": "steps", "steps": []}])


def _a_figure():
    """Build a figure without requiring a display."""
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib.figure import Figure

    fig = Figure(figsize=(4, 2))
    fig.add_subplot(1, 1, 1).plot([0, 1, 2], [0, 1, 4])
    return fig


def test_figure_is_embedded_as_a_data_uri():
    """Self-contained: no sidecar file to lose when the page is moved.

    Checks the <img> tag itself rather than just the absence of ".png" --
    the page also has a CDN <script src> and a base64 blob, so a bare
    substring search could pass without the image actually being inlined.
    """
    html = render_html([{"type": "figure", "figure": _a_figure()}])
    assert "data:image/png;base64," in html
    assert html.count("<img") == 1
    img_start = html.index("<img")
    img_tag = html[img_start:html.index(">", img_start)]
    assert 'src="data:' in img_tag
    assert ".png\"" not in html


def test_figure_caption_is_rendered_and_escaped():
    html = render_html([
        {"type": "figure", "figure": _a_figure(), "caption": "density of a < b"}
    ])
    assert "a &lt; b" in html
    assert "<figcaption>" in html


def test_figure_without_a_caption_omits_the_element():
    # Sound even against the base64 blob on the same page: base64's alphabet
    # is A-Za-z0-9+/=, which cannot contain "<", so this can't false-positive.
    html = render_html([{"type": "figure", "figure": _a_figure()}])
    assert "<figcaption>" not in html


def test_markup_in_prose_is_refused():
    """Prose is plain text, so markup in it is a mistake worth failing on.

    Escaping renders `<b>x</b>` as visible tag text and an entity as its own
    source. Both are silent: the page loads and simply reads wrong. An author
    reaching for markup wanted a different block, so say so at render time.
    """
    with pytest.raises(ValueError, match="plain text"):
        render_html([{"type": "prose", "text": "the <b>mean</b> of X"}])
    with pytest.raises(ValueError, match="plain text"):
        render_html([{"type": "prose", "text": "seven letters &mdash; three As"}])


def test_comparisons_in_prose_are_not_mistaken_for_markup():
    """The guard must not break the case escaping exists for."""
    html = render_html([{"type": "prose", "text": "if a < b and c > d"}])
    assert "a &lt; b" in html


def test_image_block_inlines_bytes_as_base64():
    """Inlined for the same reason figures are: the page is one artifact."""
    html = render_html([{"type": "image", "data": b"PNGDATA", "mime": "image/png"}])
    assert "data:image/png;base64,UE5HREFUQQ==" in html


def test_image_block_reads_a_path(tmp_path):
    image = tmp_path / "page-001.png"
    image.write_bytes(b"PNGDATA")
    html = render_html([{"type": "image", "path": str(image)}])
    assert "data:image/png;base64,UE5HREFUQQ==" in html


def test_image_block_infers_mime_from_the_suffix(tmp_path):
    image = tmp_path / "figure.jpg"
    image.write_bytes(b"JPEGDATA")
    html = render_html([{"type": "image", "path": str(image)}])
    assert "data:image/jpeg;base64," in html


def test_image_caption_is_escaped():
    html = render_html([
        {"type": "image", "data": b"X", "mime": "image/png", "caption": "a < b"}
    ])
    assert "a &lt; b" in html


def test_image_block_needs_data_or_a_path():
    with pytest.raises(ValueError, match=r"data.*path"):
        render_html([{"type": "image"}])


def test_image_mime_cannot_break_out_of_the_src_attribute():
    """mime is interpolated into an attribute, so a quote in it would escape.

    Reachable rather than theoretical: a note block infers the mime for Anki
    media, and those filenames are user data. The payload below renders an
    onerror handler if the value is passed through unchecked.
    """
    with pytest.raises(ValueError, match="mime"):
        render_html(
            [
                {
                    "type": "image",
                    "data": b"X",
                    "mime": 'image/png" onerror="alert(1)',
                }
            ]
        )


def test_a_hostile_filename_cannot_reach_the_src_attribute(tmp_path):
    """A filename is never interpolated, so the suffix cannot carry a quote out.

    The suffix table has no entry for this one, so it is refused by name rather
    than reaching the attribute. Anki media filenames are user data, so it is
    worth pinning that the name stays out of the page either way.
    """
    odd = tmp_path / 'x.png" onerror="alert(1)'
    odd.write_bytes(b"X")
    with pytest.raises(ValueError, match="cannot infer"):
        render_html([{"type": "image", "path": str(odd)}])


def test_an_unknown_suffix_is_refused_rather_than_guessed(tmp_path):
    """A non-image data URI renders as nothing, which is the silent failure.

    Requiring a mime for bytes and then guessing one for a path would leave the
    same mislabelled URI the strictness exists to prevent.
    """
    odd = tmp_path / "scan.tiff"
    odd.write_bytes(b"X")
    with pytest.raises(ValueError, match=r"scan\.tiff"):
        render_html([{"type": "image", "path": str(odd)}])


def test_an_explicit_mime_carries_a_suffix_the_table_lacks(tmp_path):
    """The escape hatch from the refusal above: name the mime yourself."""
    odd = tmp_path / "scan.tiff"
    odd.write_bytes(b"X")
    html = render_html([{"type": "image", "path": str(odd), "mime": "image/tiff"}])
    assert "data:image/tiff;base64," in html


def test_svg_is_inlined_through_img_which_renders_it_inert(tmp_path):
    """The <img> sink is load-bearing, not incidental.

    An SVG in <img src> renders in secure static mode -- no script, no external
    fetches -- which is what makes it safe to inline media from a shared deck.
    Through <object> or an inline <svg> the same bytes execute. Task 9 feeds
    this the user's real collection, so the tag is pinned here rather than left
    to whoever edits the f-string next.
    """
    svg = tmp_path / "diagram.svg"
    svg.write_bytes(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    html = render_html([{"type": "image", "path": str(svg)}])
    assert '<img src="data:image/svg+xml;base64,' in html


def test_image_alt_is_escaped():
    """alt is interpolated into an attribute exactly as mime is."""
    html = render_html([
        {"type": "image", "data": b"X", "mime": "image/png", "alt": "a < b"}
    ])
    assert 'alt="a &lt; b"' in html


def test_an_explicit_mime_is_checked_on_the_path_branch_too(tmp_path):
    """A caller may name the mime alongside a path, and that value is interpolated.

    The guard sits after the two branches converge for this reason; inside the
    bytes branch it would leave this one open.
    """
    image = tmp_path / "figure.png"
    image.write_bytes(b"X")
    with pytest.raises(ValueError, match="mime"):
        render_html(
            [
                {
                    "type": "image",
                    "path": str(image),
                    "mime": 'image/png" onerror="alert(1)',
                }
            ]
        )


def test_note_block_renders_fields_in_order():
    html = render_html([{
        "type": "note",
        "fields": [("Text", "the question"), ("Answer", "the answer")],
    }])
    assert "the question" in html
    assert "the answer" in html
    assert html.index("the question") < html.index("the answer")


def test_note_block_labels_each_field():
    html = render_html([{"type": "note", "fields": [("Back Extra", "a source")]}])
    assert "Back Extra" in html


def test_note_block_skips_empty_fields():
    """A sixteen-field note type is mostly empty; showing blanks buries content."""
    html = render_html([{
        "type": "note",
        "fields": [("Text", "kept"), ("Summary 7", ""), ("Summary 8", "   ")],
    }])
    assert "kept" in html
    assert "Summary 7" not in html
    assert "Summary 8" not in html


def test_note_block_renders_cloze_deletions_readably():
    """Raw {{c1::...}} is unreadable; the answer is what the user is discussing."""
    html = render_html([{
        "type": "note",
        "fields": [("Text", "the {{c1::mean}} of {{c2::X}}")],
    }])
    assert "{{c1::" not in html
    assert "mean" in html
    assert "X" in html


def test_note_block_reveals_a_shared_deletion():
    """{{c2,3::x}} is one deletion feeding two cards, and cloze.py handles it.

    Matching only c\\d+ here left the markup raw on the pad -- the exact
    failure revealing exists to prevent -- while cloze_numbers counted it
    correctly, so the two modules disagreed about what a deletion is.
    """
    html = render_html([{
        "type": "note",
        "fields": [("Text", "the {{c2,3::shared}} term")],
    }])
    assert "{{c2,3::" not in html
    assert "shared" in html


def test_note_block_drops_a_cloze_hint():
    html = render_html([{"type": "note", "fields": [("Text", "{{c1::ans::hint}}")]}])
    assert "ans" in html
    assert "hint" not in html


def test_note_block_keeps_field_html_and_math():
    """Fields are HTML and their math is MathJax, exactly as in Anki."""
    html = render_html([{
        "type": "note",
        "fields": [("Text", r"a<br><b>bold</b> and \(\sqrt{n}\)")],
    }])
    assert "<br>" in html
    assert "<b>bold</b>" in html
    assert r"\(\sqrt{n}\)" in html


def test_note_block_substitutes_media():
    """An <img> pointing at Anki's collection cannot load from the pad."""
    html = render_html([{
        "type": "note",
        "fields": [("Text", '<img src="paste-abc.jpg" width="514">')],
        "media": {"paste-abc.jpg": b"JPEGDATA"},
    }])
    assert "data:image/jpeg;base64,SlBFR0RBVEE=" in html
    assert 'src="paste-abc.jpg"' not in html


def test_note_block_leaves_unresolved_media_alone():
    """A missing file must not blank the tag and hide that an image was there."""
    html = render_html([{
        "type": "note",
        "fields": [("Text", '<img src="gone.jpg">')],
        "media": {},
    }])
    assert "gone.jpg" in html


def test_note_block_shows_a_title_when_given_one():
    html = render_html([{
        "type": "note",
        "title": "L3 Independence",
        "fields": [("Text", "q")],
    }])
    assert "L3 Independence" in html


def test_note_block_leaves_unrecognised_media_suffix_alone():
    """An unknown suffix from a real collection must not fail the whole pad.

    _render_image raises on this because that block is built by our own code,
    where a bad mime is a programming error worth surfacing. A note's fields
    come from the user's actual Anki collection, so the same file that would
    be a bug there is just an odd attachment here -- raising would take down
    an otherwise-readable pad over one attachment we can't label. Left alone,
    exactly like an unresolved filename, the tag stays visible and inert
    instead of guessing a mime and risking a silently mislabelled data URI.
    """
    html = render_html([{
        "type": "note",
        "fields": [("Text", '<img src="note.tiff">')],
        "media": {"note.tiff": b"TIFFDATA"},
    }])
    assert "note.tiff" in html
    assert "data:image/png" not in html
