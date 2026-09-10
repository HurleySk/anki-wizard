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

`tools.py` holds the eight tool functions. They take explicit arguments and have
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

**Card the concept, not the worked example.** Lecture slides teach general ideas
through a running example — a kissing study, a coin, one particular dataset. The
exam asks about the idea; the example is scaffolding. A front that reads "in the
kissing study, what is \(\hat{p}\)?" tests recall of that study, and the fact
does not transfer.

Lift each card one level of abstraction above the slide:

- name the general object, not the instance — *parameter vs. estimator*, not
  *\(p\) vs. \(\hat{p}\) for couples*
- use neutral symbols (\(X_i\), \(\theta\), \(n\)) unless the course has fixed a
  specific notation worth memorizing
- drop the example's numbers from the front; a concrete \(n = 124\) or
  \(p = 0.35\) belongs on the back as illustration, if at all

The example still earns a place on the back when it makes the abstraction
concrete. It just must not be the retrieval cue.

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

## The study pad

`render_pad` is for working mathematics with the user. **If the answer you are
about to write contains `\(`, `\[`, or more than one step of derivation, it
goes on the pad** — no exceptions for questions that feel like lookups rather
than teaching. Terminal LaTeX is unreadable, and the reader cannot tell which
activity you thought you were engaged in.

That trigger is deliberately about the *output*, not the activity. An earlier
version of this rule was written around "working a derivation with the user",
and it reliably failed to fire when an agent was doing something that felt like
retrieval — looking a card up, answering a question — and then emitted three
lines of LaTeX into the terminal anyway. Match on what you are about to write.

The pad shows whatever is useful, which includes a card's contents when a card
is what the user asked about: `note_blocks` renders one with its media inlined
and its cloze deletions revealed. What the pad is not is a deck browser — Anki
reviews cards, and a second, worse reviewer is not wanted. Working through
material is in scope; paging through it is not.

The pad is ephemeral by design. Do not treat replacing it as data loss, and do
not promote one to a note on the user's behalf: keeping is their call, the same
way approving a card is.

Under the default `vscode` viewer, `render_pad` returns a URL and opens nothing.
**Give the user that URL** -- clicking it is what puts the rendered page in a VS
Code tab, and a pad nobody was handed a link to is a pad nobody reads.

The URL is stable across renders and outlives the process that produced it, so
re-rendering does not invalidate a link already given. The server stops itself
once the pad goes unread; `scripts/stop_pad.py` stops one early.

**Hand over the link and stop.** The explanation belongs on the pad, not in the
terminal beside it. Restating the content in chat wastes the reader's attention
on the unreadable copy and answers the question twice; if something is worth
saying, it is worth saying on the pad where it renders. A sentence naming what
the pad holds is enough.

## The wider collection

Not every card in Anki came from here. Shared decks, imported courses, and
years of hand-made notes are all readable: `search_collection` finds them,
`read_note` opens one, `list_decks` shows the deck tree, and `note_blocks`
puts one on the pad with its images.

Use `list_decks` to confirm a deck name rather than trusting a remembered one.
The rule against inventing a subdeck name is above; this is how to check.

**Editing a note this harness did not author is a different act from revising
one it did.** A shared deck is work the user may not be able to regenerate, and
the ledger's usual guarantee — that it is the source of truth — does not hold
for a note it never created. So:

- Read the note first. `edit_note` needs the real field names, and a name that
  is not on the note is refused rather than guessed at.
- Show the diff and get agreement before writing. The tool returns one; put it
  in front of the user the way a card proposal goes in front of them.
- Never pass `force=True` on your own judgment. It exists to override the
  cloze guard, and past that guard an edit deletes cards and their review
  history irreversibly. That is the user's call, always.
- Editing adopts the note into `cards/<deck-slug>.yaml` as a reference entry.
  Adopted entries have no `front`/`back` — they record which note and which
  fields, never the content.

## Writing pad blocks

Prose is **plain text, not HTML**. `render.py` escapes it, so `<b>bold</b>`
renders as literal `<b>bold</b>` and `&mdash;` as literal `&mdash;`. This is
deliberate -- a stray `<` in mathematical prose must not open a tag -- so reach
for the right block instead of marking prose up:

- emphasis: rewrite the sentence, or let a `steps` block's `why` carry the aside
- displayed math: a `math` block, never `\[...\]` hand-rolled into prose
- structure: separate blocks, or a `figure`; there is no heading block, so a
  short prose line naming the section is how a section gets named
- punctuation: type the character itself (-- and " and ...), never an entity

Inline `\(...\)` inside prose does survive escaping, since the delimiters are
backslashes. But keep it to a bare symbol or a short expression: entities and
escaped tags landing inside a math span are what silently break MathJax, and a
formula that fails to typeset disappears from the page rather than erroring.

Prefer a `steps` block over prose for a derivation, and use each step's `why` to
name the justification. A derivation whose steps are unjustified teaches the
manipulation without the reason, which is the failure mode the pad exists to fix.

## The why field

Cards have an optional third field, `why`, for the reasoning behind the answer.
It renders collapsed on the back; a card without one renders no toggle at all.

Use it where the answer alone would be memorised without being understood — a
formula whose derivation is the actual lesson, a condition whose necessity is
the point. Leave it empty otherwise. **An empty why is better than a filler
why:** once the field routinely carries nothing worth reading, it stops being
read at all, and the cards that genuinely need one lose their voice.

**A why that asserts is not yet a why.** "Independent variances add" or "a
linear combination of Gaussians is Gaussian" is another fact to memorise, not
a reason. When the why leans on a step like that, carry the step's own short
derivation: expand the square and show the cross term vanish, multiply the
MGFs, substitute into the definition of variance. Two or three lines of
displayed math is the right size — enough that the reader could reproduce the
result, not a textbook section. The step that gets asserted without proof is
usually the one that gets misapplied under exam pressure, which is exactly the
gap the field exists to close.

Set it at proposal time alongside `front` and `back`, or add one later with
`revise_card`.

Pushing requires the `Basic with Why` note type in Anki. `NOTE_TYPE` in
`anki.py` names it; `scripts/migrate_note_type.py` creates it and migrates
existing notes.

## Lectures and subdecks

Cards carry an optional `lecture`, and `push_to_anki` sends them to that
subdeck of the configured deck. The deck in `config.yaml` is the **course**;
the field holds everything below it:

    deck: Fundamentals of Statistics
    lecture: "Unit I: Introduction to Statistics::L01 What is Statistics?"
    -> Fundamentals of Statistics::Unit I: Introduction to Statistics::L01 What is Statistics?

The field is a **subdeck path, not a bare lecture name**. That is what lets the
unit level exist without a schema change, and what would let a further level be
added later. A card with no lecture goes to the base deck, so the field stays
optional.

The lecture lives on the card, not on the source. One PDF can span several
lectures, one lecture can gather cards from several PDFs, and a conversation
card with no document at all can still be filed. Nothing infers it from the
slug.

**Confirm course, unit, and lecture names with the user before proposing cards,
and never invent one.** An unrecognised name is a question, not a new subdeck:
Anki creates decks on demand, so a typo silently produces a near-duplicate that
splits reviews between them with no error to notice. Ask for the exact name, or
offer one and have it confirmed. The unit in particular is course-level
structure that lecture slides usually do not state.

Naming follows the convention already in this collection:

- course by title, not code -- `Fundamentals of Statistics`, with the code
  carried by the `18-6501x` tag instead
- unit as `Unit I: Introduction to Statistics` -- Roman numeral, colon, title
- lecture as `L01 What is Statistics?` -- zero-padded number, then the title

Pad the lecture number. Anki sorts deck names as text, so an unpadded scheme
gives `L1, L10, L2` past nine.

Refiling a pushed card is `revise_card(..., lecture=...)`, which moves it in
Anki with its scheduling intact -- review history lives on the card, not the
deck. `scripts/assign_lecture.py <slug> "<path>"` does a whole slug at once and
dry-runs unless passed `--apply`.

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
