"""Content blocks to a self-contained HTML page.

No network, no display, no matplotlib import at module level -- the rendering
rules are tested exhaustively without either. An `image` block with a `path`
is the one exception to "no filesystem": it reads that file so the pad can
show Anki media and rendered PDF pages, which exist only on disk.

The page uses the same MathJax delimiters as the cards -- \\(...\\) and \\[...\\]
-- so a formula that renders here renders in Anki.
"""

import base64
import io
import re
from html import escape
from pathlib import Path

MATHJAX_CDN = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script>
window.MathJax = {{
  tex: {{
    inlineMath: [['\\\\(', '\\\\)']],
    displayMath: [['\\\\[', '\\\\]']]
  }}
}};
</script>
<script id="MathJax-script" async src="{cdn}"></script>
<style>{css}</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""

_CSS = """
:root {
  --ink: #1a1a1a;
  --paper: #fdfdfc;
  --muted: #6b6b6b;
  --rule: #e0e0dd;
}
@media (prefers-color-scheme: dark) {
  :root { --ink: #e8e8e6; --paper: #16161a; --muted: #9a9a97; --rule: #33333a; }
}
body {
  background: var(--paper);
  color: var(--ink);
  font: 17px/1.7 Georgia, 'Iowan Old Style', serif;
  margin: 0;
  padding: 3rem 1.5rem 6rem;
}
main { max-width: 34rem; margin: 0 auto; }
p { margin: 0 0 1.2rem; }
.step { display: flex; gap: 1rem; align-items: baseline; margin: 0 0 0.9rem; }
.step-num {
  color: var(--muted);
  font: 600 13px/1 ui-monospace, monospace;
  min-width: 1.5rem;
}
.step-why {
  color: var(--muted);
  font-size: 14px;
  font-style: italic;
  margin: 0.2rem 0 0 2.5rem;
}
figure { margin: 2rem 0; }
figure img { width: 100%; height: auto; }
figcaption {
  color: var(--muted);
  font-size: 14px;
  text-align: center;
  margin-top: 0.6rem;
}
hr { border: 0; border-top: 1px solid var(--rule); margin: 2.5rem 0; }
.note-field { margin: 1.5rem 0; }
.field-name {
  font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--muted); margin: 0 0 0.35rem;
}
.note-field img { max-width: 100%; height: auto; }
"""


def render_html(blocks: list[dict], title: str = "Study pad") -> str:
    """Turn content blocks into a standalone page."""
    return _PAGE.format(
        title=escape(title),
        cdn=MATHJAX_CDN,
        css=_CSS,
        body="\n".join(_render_block(b) for b in blocks),
    )


def _render_block(block: dict) -> str:
    kind = block.get("type")
    if kind == "prose":
        # Escaped because prose is text: a stray "<" must not open a tag. Math
        # delimiters are backslash sequences, which escaping leaves alone.
        _reject_markup(block["text"])
        return f"<p>{escape(block['text'])}</p>"
    if kind == "math":
        return f"<p>\\[{block['tex']}\\]</p>"
    if kind == "steps":
        steps = block["steps"]
        if not steps:
            raise ValueError("a steps block needs at least one step")
        return "\n".join(_render_step(i, s) for i, s in enumerate(steps, 1))
    if kind == "image":
        return _render_image(block)
    if kind == "figure":
        return _render_figure(block)
    if kind == "note":
        return _render_note(block)
    raise ValueError(f"unknown block type: {kind!r}")


# A tag with a known inline name, or a named/numeric entity. Deliberately not
# a general "<...>" match: prose about a comparison is exactly what escaping is
# for, and "a < b" must keep rendering rather than trip this.
_MARKUP = re.compile(
    r"</?(?:b|i|u|em|strong|br|p|div|span|h[1-6]|hr|a|ul|ol|li)\b[^>]*>"
    r"|&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});"
)


def _reject_markup(text: str) -> None:
    """Fail on markup in prose, which escaping would render as visible source.

    The failure is otherwise silent -- the page loads and simply reads wrong --
    and it means the author wanted a block that does not exist yet or a
    different one that does, so it is worth stopping for rather than escaping.
    """
    found = _MARKUP.search(text)
    if found:
        raise ValueError(
            f"prose is plain text, so {found.group()!r} would render as itself. "
            "Use a math block for displayed formulas, a steps block's why for an "
            "aside, or type the character directly instead of an entity."
        )


def _render_step(number: int, step: dict) -> str:
    row = (
        f'<div class="step"><span class="step-num">{number}</span>'
        f'<span>\\[{step["tex"]}\\]</span></div>'
    )
    why = step.get("why")
    if why:
        row += f'\n<div class="step-why">{escape(why)}</div>'
    return row


# A media type and subtype, which is all a data URI here ever needs. Narrow on
# purpose: the point is to reject anything that could carry a quote out of the
# attribute, not to accept every mime the RFC allows.
_TOKEN = r"[a-zA-Z0-9][a-zA-Z0-9!#$&^_.+-]{0,126}"
_MIME = re.compile(rf"{_TOKEN}/{_TOKEN}")

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def _render_image(block: dict) -> str:
    """An image from bytes or a path, inlined like a figure.

    Bytes rather than a URL because the pad's images come from Anki's media
    collection and from rendered PDF pages -- neither is reachable from the
    page, and a promoted note must not break when its sources move.

    Bytes require an explicit mime: Anki media can be PNG, JPEG, GIF, or WEBP,
    and a wrong label in a data URI is silently wrong -- some browsers sniff
    the real format and render anyway, others don't, so the failure would not
    show up until someone opens the pad in the "wrong" one. A path takes an
    explicit mime if given, else a known suffix; an unrecognised suffix raises
    rather than guessing, for that same reason -- the guess a browser cannot
    render is a blank space on the pad and no error anywhere.
    """
    data = block.get("data")
    path = block.get("path")
    if data is None and path is None:
        raise ValueError("an image block needs data or a path")

    if data is None:
        source = Path(path)
        data = source.read_bytes()
        mime = block.get("mime") or _MIME_BY_SUFFIX.get(source.suffix.lower())
        if not mime:
            # A non-image data URI never enters the browser's image decode
            # path, so a fallback here would render as nothing at all. Naming
            # the file and the way out beats a blank figure on the pad.
            raise ValueError(
                f"cannot infer an image mime type from {source.name!r}; "
                "pass mime explicitly"
            )
    else:
        mime = block.get("mime")
        if not mime:
            raise ValueError("an image block built from data needs a mime type")

    if not _MIME.fullmatch(mime):
        # An injection boundary, not a format policy: this checks the shape a
        # mime has, so text/html passes and only a value that could carry a
        # quote out of the src attribute is refused. mime lands inside that
        # attribute, where a quote would close it and let the rest become
        # attributes of its own -- an onerror handler, say. Escaping would
        # admit a broken-but-inert value silently; a mime that is not a mime
        # is a bug whichever way it arrived, so it raises.
        raise ValueError(f"not a well-formed mime type: {mime!r}")

    encoded = base64.b64encode(data).decode("ascii")
    caption = block.get("caption")
    caption_html = f"\n<figcaption>{escape(caption)}</figcaption>" if caption else ""
    alt = escape(block.get("alt", ""))
    return (
        f'<figure><img src="data:{mime};base64,{encoded}" alt="{alt}">'
        f"{caption_html}</figure>"
    )


def _render_figure(block: dict) -> str:
    # Inlined rather than written alongside: the page is one artifact, so
    # promoting or moving it cannot leave the image behind.
    buffer = io.BytesIO()
    block["figure"].savefig(buffer, format="png", dpi=150, bbox_inches="tight")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    caption = block.get("caption")
    caption_html = f"\n<figcaption>{escape(caption)}</figcaption>" if caption else ""
    return (
        f'<figure><img src="data:image/png;base64,{encoded}" alt="">'
        f"{caption_html}</figure>"
    )


# Anki writes media as a plain filename in the field's HTML, which resolves
# only inside the collection. The pad has to inline the bytes instead.
_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.IGNORECASE)

_CLOZE = re.compile(r"\{\{c\d+::(.*?)(?:::[^}]*)?\}\}", re.DOTALL)

# A separate table from _MIME_BY_SUFFIX, deliberately not shared: this one
# backs a lookup that must fail open (leave the tag alone) rather than raise,
# so merging it with _render_image's table would tie together two branches
# that need different failure behavior for the same missing key.
_NOTE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def _reveal_clozes(html: str) -> str:
    """Show a deletion's answer instead of its markup.

    The pad is for working through a card's content with the user, who is
    looking at it precisely because they want to see the answer. Hints are
    dropped: they exist to prompt recall, which is not what this surface does.
    """
    return _CLOZE.sub(lambda m: m.group(1), html)


def _inline_media(html: str, media: dict[str, bytes]) -> str:
    def replace(match: re.Match) -> str:
        filename = match.group(2)
        data = media.get(filename)
        if data is None:
            # Left as it is on purpose: blanking the tag would hide that the
            # card had an image at all, which is worse than a broken one.
            return match.group(0)
        suffix = Path(filename).suffix.lower()
        mime = _NOTE_MIME_BY_SUFFIX.get(suffix)
        if mime is None:
            # _render_image raises on an unrecognised suffix, because that
            # block is built by our own code and a bad mime there is a bug
            # worth surfacing. This filename instead comes from the user's
            # real Anki collection: raising would take down the whole pad
            # over one odd attachment, which is worse than leaving a single
            # image unrendered. So this fails the same way a missing file
            # does -- tag untouched, filename still visible -- rather than
            # guessing a mime and risking a silently mislabelled data URI.
            return match.group(0)
        encoded = base64.b64encode(data).decode("ascii")
        return f"{match.group(1)}data:{mime};base64,{encoded}{match.group(3)}"

    return _IMG_SRC.sub(replace, html)


def _render_note(block: dict) -> str:
    """An Anki note laid out for reading.

    Takes fields and media already fetched rather than a note id, so this
    module keeps no dependency on anki.py and stays testable without a server.

    Field HTML is emitted unescaped, on purpose: Anki fields are HTML and their
    math is MathJax, and escaping would show the user tags instead of a card.
    The consequence is that a note's markup runs in the pad exactly as written
    -- a <script> or an onerror handler in a field executes, and _IMG_SRC only
    rewrites a quoted src, leaving the rest of a tag's attributes untouched.
    This is accepted rather than sanitized: the pad is served on 127.0.0.1 to
    one local user, not a remote surface, and the same HTML already runs
    inside Anki itself whenever this card comes up for review.
    """
    fields = block["fields"]
    media = block.get("media", {})

    parts: list[str] = []
    title = block.get("title")
    if title:
        parts.append(f"<h2>{escape(title)}</h2>")

    for name, value in fields:
        if not value or not value.strip():
            continue
        rendered = _inline_media(_reveal_clozes(value), media)
        parts.append(
            f'<section class="note-field">'
            f'<h3 class="field-name">{escape(name)}</h3>'
            f"<div>{rendered}</div></section>"
        )
    return "\n".join(parts)
