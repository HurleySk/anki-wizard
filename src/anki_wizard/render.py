"""Content blocks to a self-contained HTML page.

Pure: blocks in, HTML string out. No filesystem, no browser, no matplotlib
import at module level. That purity is what lets the rendering rules be tested
exhaustively without a display.

The page uses the same MathJax delimiters as the cards -- \\(...\\) and \\[...\\]
-- so a formula that renders here renders in Anki.
"""

from html import escape

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
        return f"<p>{escape(block['text'])}</p>"
    if kind == "math":
        return f"<p>\\[{block['tex']}\\]</p>"
    if kind == "steps":
        steps = block["steps"]
        if not steps:
            raise ValueError("a steps block needs at least one step")
        return "\n".join(_render_step(i, s) for i, s in enumerate(steps, 1))
    raise ValueError(f"unknown block type: {kind!r}")


def _render_step(number: int, step: dict) -> str:
    row = (
        f'<div class="step"><span class="step-num">{number}</span>'
        f'<span>\\[{step["tex"]}\\]</span></div>'
    )
    why = step.get("why")
    if why:
        row += f'\n<div class="step-why">{escape(why)}</div>'
    return row
