# anki-wizard

A harness for Claude agents to turn mathematical PDFs into Anki decks. Claude
reads rendered page images, proposes cards, and pushes approved ones through
AnkiConnect.

**Read `README.md` first.** It documents the tools, the on-disk layout, the card
lifecycle, and the failure modes. This file covers only what the README does not:
conventions and judgment calls.

## Commands

    uv sync --extra dev                              # install
    uv run pytest                                    # full suite
    uv run python scripts/smoke.py <path-to.pdf>     # end-to-end, no Anki needed

Test fixtures are generated on first run, so `pytest` works from a fresh clone.

## Architecture in one pass

`tools.py` holds the seven tool functions. They take explicit arguments and have
no dependency on the calling conversation, so an MCP server can wrap them
unchanged — keep them that way. `session.py` is the convenience layer that reads
`config.yaml` once and supplies those arguments; it is where you add ergonomics,
not behavior.

`paths.py` is the single source of truth for the state layout. Never build a
state path by string concatenation anywhere else.

The ledger (`cards/<slug>.yaml`) is the source of truth, not Anki. It is YAML,
not JSON — `outline.json` and `cursor.json` are JSON, which is easy to trip on.

## Curation is the point

Nothing reaches Anki without the user's review. `propose_cards` writes to the
ledger only; `push_to_anki` is a separate, explicit step.

Propose cards and stop. Do not approve your own proposals and do not push unless
the user asks. Approving on the user's behalf defeats the entire design.

## Reading source material

**Read the page images. The text layer is a lossy hint, never the basis for a
card's mathematical content.** This is not a stylistic preference — on a real
lecture deck `pdftotext` dropped a σ entirely, rendered `√n` as the letter `p`,
turned `→` into `!`, and tore the exponent off an inequality. Cards built from
that text are silently wrong.

**Handwritten annotations are content.** Lecture PDFs are often annotated, and
those notes exist only in the image — no text layer contains them. Treat a
margin note, a highlighted term, or a worked example in the instructor's hand
exactly as you would printed material on the same slide: card it if it carries a
fact worth recalling.

## What deserves a card

**Be parsimonious. A slide is not a card quota.** Most slides in a lecture deck
earn nothing: title pages, section dividers, motivating press clippings, course
logistics, a figure that illustrates a point made better elsewhere. Walking the
deck and emitting a card per slide produces a deck that is expensive to review
and teaches little.

The test is not "is this true?" but **"would not knowing this cost me on an
exam?"** Card the load-bearing content:

- definitions a later result quotes by name
- theorem statements, and their hypotheses as a separate card
- the conditions under which a method applies or fails
- formulas that must be reproduced from memory, not looked up
- distinctions the course itself draws (estimator vs. estimate, probability vs.
  statistics) — these are exam questions in the way that prose summaries are not

Skip the rest. Prefer few, sharp cards over broad coverage; ten cards that carry
a chapter beat forty that transcribe it. When a section genuinely holds nothing
worth recalling, call `skip_section` with a reason rather than proposing a weak
card to make the cursor move — coverage is derived from cards, so a card-less
section cannot settle any other way.

Nuance matters more than volume. When a slide states a result with a caveat, the
caveat is usually the card — the bare result is often already intuitive, and the
condition attached to it is what gets missed under exam pressure.

## Cards from conversation

Reviewing a problem and carding what was hard is a first-class flow, not a
fallback. Pass `section_id=None` with a slug that was never ingested; use a
topic slug (`pset-3`) rather than the catch-all `conversation` whenever the
cards share a subject, since the slug is the only grouping those cards get.

Cards drawn from a mistake are worth more than cards drawn from what was already
understood. Prefer the former.

Expect overlap with document cards — the same theorem carded from a slide weeks
earlier will be rejected by Anki as a duplicate and stay `approved`. That is a
curation question for the user: revise the original, or reject the new one.
Do not silently pick one.

## Section boundaries

A section's `pages` is `[start, end)` — start inclusive, end **exclusive**. For
`structure="slides"` and `structure="pages"` a section is exactly one page, so
`pages: [29, 30]` means page 29 alone. `read_section` already returns only the
section's own pages; it does not hand you the neighbor. Read `[start, end)` as a
range and there is nothing to guard against.

Card only what `read_section` returned. Reaching into an adjacent page by hand
duplicates cards across sections and strands coverage.

## Card conventions

- **Math is MathJax:** `\(...\)` inline, `\[...\]` displayed. Not `$...$`.
- **Fields are HTML.** `<br>`, `<b>`, `<i>` work; a bare newline does not.
- **Tags:** lowercase, hyphenated. Every card gets the source slug (`stats-ch1`)
  plus topic tags (`clt`, `hoeffding`). Put shared tags in `config.yaml` under
  `default_tags` rather than repeating them on every proposal.
- Cards made from conversation rather than a document also get the tag
  `from-conversation`, so they can be told apart in Anki, where the ledger's
  provenance is not visible.
- One retrievable fact per card. A theorem's statement and its hypotheses are
  usually separate cards — forgetting the hypotheses is the common failure, so
  it deserves its own retrieval path.
- The front must be answerable with the back hidden. "State the CLT" works;
  "CLT" does not.

## Repo conventions

- `docs/superpowers/` is gitignored and must stay that way. The repo is public;
  specs and plans are local only.
- `sources/`, `cards/`, and `config.yaml` are gitignored — user state, never
  committed.
- Tests never contact a real Anki. `tests/fake_anki.py` serves the AnkiConnect
  protocol over a real socket; use it rather than mocking `requests`.
- Comments explain *why*, not *what*. The existing source is consistent about
  this; match it.
