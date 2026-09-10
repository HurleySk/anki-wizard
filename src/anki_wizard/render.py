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
    show up until someone opens the pad in the "wrong" one. A path infers the
    mime from its suffix instead, since the file's extension is the mime.
    """
    data = block.get("data")
    path = block.get("path")
    if data is None and path is None:
        raise ValueError("an image block needs data or a path")

    if data is None:
        source = Path(path)
        data = source.read_bytes()
        mime = block.get("mime") or _MIME_BY_SUFFIX.get(
            source.suffix.lower(), "application/octet-stream"
        )
    else:
        mime = block.get("mime")
        if not mime:
            raise ValueError("an image block built from data needs a mime type")

    if not _MIME.fullmatch(mime):
        # mime lands inside the src attribute, so a value carrying a quote
        # would close it and let the rest become attributes of its own -- an
        # onerror handler, say. Anki media filenames are user data and a note
        # block infers this from them, so the check is against a shape rather
        # than an escape: a mime that is not a mime is a bug either way.
        raise ValueError(f"not a usable image mime type: {mime!r}")

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
