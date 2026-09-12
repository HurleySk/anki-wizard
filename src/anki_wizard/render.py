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
import uuid
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
<body{body_class}>
<main>
{body}
</main>
</body>
</html>
"""

_CSS = """
:root {
  color-scheme: light dark;
  --ink: #1a1a1a;
  --paper: #fdfdfc;
  --muted: #6b6b6b;
  --rule: #e0e0dd;
}
@media (prefers-color-scheme: dark) {
  :root { --ink: #e8e8e6; --paper: #16161a; --muted: #9a9a97; --rule: #33333a; }
}
/* matplotlib's player styles itself inline-block, which under a bare
   <figure> sits left while the caption centers. */
figure > .animation { display: block; }
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
.sheet h2 { font-size: 1.1rem; margin: 2.5rem 0 1rem; }
.formula { margin: 0 0 1.4rem; break-inside: avoid; }
.formula-label { font-weight: 600; }
.formula-meta {
  color: var(--muted);
  font: 500 12px/1 ui-monospace, monospace;
  margin-left: 0.6rem;
}
.formula-note { color: var(--muted); font-size: 14px; font-style: italic; }
/* The cheat sheet is meant to be printed: two columns, no margins, and a
   formula never split across a page. Scoped to the sheet so a derivation
   pad prints as it reads. */
@media print {
  body.sheet { font-size: 12px; padding: 0; }
  .sheet main { max-width: none; column-count: 2; column-gap: 2rem; }
  .sheet h2 { break-after: avoid; margin-top: 1.2rem; }
  .sheet .formula { margin-bottom: 0.8rem; }
}
"""


def render_html(
    blocks: list[dict], title: str = "Study pad", body_class: str | None = None
) -> str:
    """Turn content blocks into a standalone page.

    `body_class` scopes styling that is not for every page: the cheat sheet
    sets "sheet" for its print layout, which a derivation pad must not get.
    """
    return _PAGE.format(
        title=escape(title),
        cdn=MATHJAX_CDN,
        css=_CSS,
        body_class=f' class="{escape(body_class)}"' if body_class else "",
        body="\n".join(_render_block(b) for b in blocks),
    )


def _render_block(block: dict) -> str:
    kind = block.get("type")
    if kind == "prose":
        # Escaped because prose is text: a stray "<" must not open a tag. Math
        # delimiters are backslash sequences, which escaping leaves alone.
        return f"<p>{_prose(block['text'])}</p>"
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
    if kind == "animation":
        return _render_animation(block)
    if kind == "note":
        return _render_note(block)
    if kind == "heading":
        # A heading an agent writes is prose: "T_n" in an h2 shows a literal
        # underscore as silently as it would in a paragraph, and MathJax does
        # typeset \(...\) in a heading, so the guard costs nothing. The
        # exemption is for a name copied from Anki -- a deck can be called
        # "L03 E[X] and Var(X)", and refusing it as undelimited math would
        # refuse the user's own deck -- and only the tool that copied it
        # knows, so it says so with "verbatim". Markup is refused either way.
        text = block["text"]
        if block.get("verbatim"):
            _reject_markup(text)
        else:
            check_prose(text)
        return f"<h2>{escape(text)}</h2>"
    if kind == "formula":
        return _render_formula(block)
    raise ValueError(f"unknown block type: {kind!r}")


# A tag with a known inline name, or a named/numeric entity. Deliberately not
# a general "<...>" match: prose about a comparison is exactly what escaping is
# for, and "a < b" must keep rendering rather than trip this.
_MARKUP = re.compile(
    r"</?(?:b|i|u|em|strong|br|p|div|span|h[1-6]|hr|a|ul|ol|li)\b[^>]*>"
    r"|&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#\d{1,7}|#[xX][0-9a-fA-F]{1,6});"
)


def _prose(text: str) -> str:
    """Plain text made safe for the page, refused if it was not plain text.

    Every prose-shaped string -- a paragraph, a step's why, a caption -- goes
    through here, so a guard added once covers all of them. The why was the
    gap: it was escaped like prose but never checked like prose, and that is
    where ASCII math first slipped through.
    """
    check_prose(text)
    return escape(text)


def check_prose(text: str) -> None:
    """Refuse text the pad would render wrong, without rendering it.

    Public so a cheat sheet entry's label can be checked when it is proposed:
    the page is written again on every change, and a label that fails there
    would fail long after anyone could say which proposal was at fault.
    """
    _reject_markup(text)
    _reject_ascii_math(text)


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


# Math that only typesets inside \\(...\\): a caret or subscript on a symbol, a
# named function applied to something, or a bare TeX command. Checked with the
# delimited spans removed, so \\(n\\sigma^2\\) is exactly what passes. Deliberately
# not matching Greek names as words -- "the beta distribution" is prose -- nor
# underscores inside identifiers, since a config key is prose too.
_DELIMITED_MATH = re.compile(r"\\\(.*?\\\)|\\\[.*?\\\]", re.S)
_STRAY_DELIMITER = re.compile(r"\\[()\[\]]")
_ASCII_MATH = re.compile(
    r"[\w)]+\^[\w{(]+"                      # sigma^2, n^2, a^{-1}
    r"|(?<![\w])[A-Za-z]_[\w{]+"             # X_i, x_1
    r"|\b(?:sqrt|exp|log|E|Var|Cov|sd|SD)[(\[]"  # sqrt(, E[, Var(
    r"|\\[A-Za-z]+"                          # \sigma with no delimiters
)


def _reject_ascii_math(text: str) -> None:
    """Fail on math that is not delimited, which the page would show as text.

    "n sigma^2" reads as prose to the renderer and as a mistake to the reader,
    and nothing errors in between. An unbalanced delimiter is the same failure
    from the other side: MathJax leaves the span untypeset, silently.
    """
    outside = _DELIMITED_MATH.sub(" ", text)
    stray = _STRAY_DELIMITER.search(outside)
    if stray:
        raise ValueError(
            f"unbalanced math delimiter {stray.group()!r} in prose; MathJax "
            "would leave that span untypeset."
        )
    found = _ASCII_MATH.search(outside)
    if found:
        raise ValueError(
            f"prose is typeset only inside \\(...\\), so {found.group()!r} would "
            "render as plain text. Wrap the expression in inline math "
            "delimiters, or move it to a math block."
        )


def _render_step(number: int, step: dict) -> str:
    row = (
        f'<div class="step"><span class="step-num">{number}</span>'
        f'<span>\\[{step["tex"]}\\]</span></div>'
    )
    why = step.get("why")
    if why:
        row += f'\n<div class="step-why">{_prose(why)}</div>'
    return row


def _render_formula(block: dict) -> str:
    """A cheat sheet entry: label, the formula displayed, an optional note.

    The meta slot carries the id and state on a review page so the user can
    name the entry back in a decision; the printable sheet leaves it out.
    """
    label = _prose(block["label"])
    meta = block.get("meta")
    if meta:
        label += f'<span class="formula-meta">{escape(meta)}</span>'
    html = (
        f'<div class="formula"><div class="formula-label">{label}</div>'
        f"\\[{block['tex']}\\]"
    )
    note = block.get("note")
    if note:
        html += f'<div class="formula-note">{_prose(note)}</div>'
    return html + "</div>"


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
    caption_html = f"\n<figcaption>{_prose(caption)}</figcaption>" if caption else ""
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
    caption_html = f"\n<figcaption>{_prose(caption)}</figcaption>" if caption else ""
    return (
        f'<figure><img src="data:image/png;base64,{encoded}" alt="">'
        f"{caption_html}</figure>"
    )


# matplotlib's HTML player links an icon font from a CDN for its nine control
# buttons and nothing else. The page is meant to be one artifact that opens
# offline (every image is a data URI for that reason), and a control bar that
# renders blank without network is not worth a third-party stylesheet, so the
# link goes and each icon becomes a character the reader can see.
_ICON_FONT_LINK = re.compile(r'<link\b[^>]*font-awesome[^>]*>', re.IGNORECASE)
_ICON = re.compile(r'<i class="fa (fa-[a-z-]+)( fa-flip-horizontal)?"></i>')
_ICON_GLYPHS = {
    "fa-fast-backward": "\u23ee",  # skip to start
    "fa-step-backward": "\u25c1",  # hollow: steps one frame, does not play
    "fa-pause": "\u23f8",
    "fa-play": "\u25b6",
    "fa-step-forward": "\u25b7",
    "fa-fast-forward": "\u23ed",  # skip to end
    "fa-minus": "\u2212",  # slower
    "fa-plus": "+",  # faster
}

# Frames are inlined as PNGs at roughly 17 KB each, so the page grows linearly
# with frame count and a long animation makes a pad that takes tens of seconds
# to open. The guard is on the output rather than on a frame count because the
# Animation object does not expose its length uniformly, and the bytes are
# what actually hurt.
_MAX_ANIMATION_BYTES = 8 * 1024 * 1024

# matplotlib caches the exported HTML on the Animation, so the same object
# rendered twice on one page arrives with the same element ids, and the second
# player's controls drive the first one's image. Every element, variable, and
# id in the export shares one hex token, so re-minting the token is the fix.
_PLAYER_TOKEN = re.compile(r'id="_anim_img([0-9a-f]{32})"')


def _icon_glyph(match: re.Match) -> str:
    # The reverse-play button is the play icon flipped, so mirror the glyph.
    if match.group(2):
        return "\u25c0" if match.group(1) == "fa-play" else match.group(1)
    return _ICON_GLYPHS.get(match.group(1), match.group(1))


def _render_animation(block: dict) -> str:
    player = block["animation"].to_jshtml()
    if len(player) > _MAX_ANIMATION_BYTES:
        raise ValueError(
            f"animation renders to {len(player) / 2**20:.1f} MB, over the "
            f"{_MAX_ANIMATION_BYTES // 2**20} MB limit; use fewer frames, "
            "a smaller figure, or a lower dpi"
        )

    token = _PLAYER_TOKEN.search(player)
    if token:
        player = player.replace(token.group(1), uuid.uuid4().hex)
    player = _ICON_FONT_LINK.sub("", player)
    player = _ICON.sub(_icon_glyph, player)

    caption = block.get("caption")
    caption_html = f"\n<figcaption>{_prose(caption)}</figcaption>" if caption else ""
    return f"<figure>{player}{caption_html}</figure>"


# Anki writes media as a plain filename in the field's HTML, which resolves
# only inside the collection. The pad has to inline the bytes instead.
# collection._IMG_SRC is deliberately the same shape: it extracts the
# filenames that get fetched and handed here, so the two must agree on what
# counts as a media reference -- a tag it misses is a broken image here.
_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]+)(")', re.IGNORECASE)

# The ordinal is comma-separated for the same reason cloze.py's is:
# {{c2,3::text}} is one deletion feeding two cards. Matching only c\d+
# here would leave that markup on the pad raw, which is the thing this
# reveal exists to prevent. The two modules must agree on the syntax
# even though they cannot share a regex -- cloze.py stops at the "::"
# because it only wants the ordinal, while this one spans the whole
# deletion in order to replace it.
#
# A hint containing a brace ({{c1::ans::a{b}}}) leaves a stray "}" behind:
# [^}]* cannot span one. Accepted rather than fixed -- hints are short
# recall prompts, the damage is one character on a display-only surface,
# and matching braces properly needs the real parser cloze.py declines to
# write for this same syntax.
_CLOZE = re.compile(r"\{\{c[\d,]+::(.*?)(?:::[^}]*)?\}\}", re.DOTALL)

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


def reveal_clozes(html: str) -> str:
    """Show a deletion's answer instead of its markup.

    The pad is for working through a card's content with the user, who is
    looking at it precisely because they want to see the answer. Hints are
    dropped: they exist to prompt recall, which is not what this surface does.

    Public because collection.py's search/read previews need the same reveal:
    a note pulled from anywhere in the collection can carry cloze markup, and
    a preview showing "{{c1::network}}" instead of "network" is unreadable.
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
    That scan also stops at a ">" inside an earlier attribute, so an <img> with
    alt="x > y" keeps its collection-local src and simply does not render, the
    same way an unresolvable tag does.
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
        rendered = _inline_media(reveal_clozes(value), media)
        parts.append(
            f'<section class="note-field">'
            f'<h3 class="field-name">{escape(name)}</h3>'
            f"<div>{rendered}</div></section>"
        )
    return "\n".join(parts)
