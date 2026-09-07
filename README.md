# anki-wizard

A harness for Claude agents to create and manage Anki decks, aimed at
mathematical material.

Claude reads source PDFs page by page, proposes flashcards, and pushes the ones
you approve into your Anki collection. Nothing reaches Anki without your review.

## Requirements

- Python 3.11+
- [poppler](https://poppler.freedesktop.org/) — `brew install poppler`
- [Anki](https://apps.ankiweb.net/) with the
  [AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on (code
  `2055492159`), running when you push

## Setup

    uv sync --extra dev
    uv run pytest

Test fixtures are generated on first run, so `pytest` works from a fresh clone.

Optionally create `config.yaml`:

    anki_connect_url: http://localhost:8765
    deck: Math::Analysis
    default_tags: [auto]
    max_pages_per_read: 10

## The tools

| Tool | What it does |
| --- | --- |
| `ingest_source(pdf, slug, paths)` | Render pages, extract text, build a section map, start a cursor. Run once per document; safe to re-run after an interruption. |
| `get_progress(slug, paths)` | What has been covered and what is next. |
| `read_section(slug, section_id, paths)` | A section's page images and text. `section_id=None` reads the next uncovered section. |
| `propose_cards(slug, proposals, section_id, paths)` | Add proposed cards to the ledger. Use `slug="conversation"` for cards not from a document. |
| `review_cards(slug, decisions, paths)` | Approve, reject, or edit proposed cards. |
| `push_to_anki(slug, client, deck, paths)` | Send approved cards to Anki, record note ids, advance the cursor. |
| `revise_card(slug, card_id, client, paths, ...)` | Edit a card, updating Anki in place if it was already pushed. |

`Session` wraps all of these, reading `config.yaml` once so you do not pass
`paths`, `deck`, and page caps by hand:

    from anki_wizard.session import Session

    s = Session(root=".")
    s.ingest("~/Downloads/lecture.pdf", slug="lecture")
    s.progress("lecture")
    s.read("lecture")                      # next uncovered section
    s.propose("lecture", [...], section_id="1")
    s.review("lecture", {"c-0001": "approve"})
    s.push("lecture")                      # needs Anki running

## How math is handled

Cards use MathJax, which Anki renders natively: `\(x^2\)` inline and `\[...\]`
displayed. Cards stay as editable text, so revising one is a string change and
they render on AnkiMobile and AnkiDroid.

Claude reads **page images**, not extracted text. The text layer is kept as a
hint, but `pdftotext` mangles LaTeX list markers and displayed equations, so it
is never the basis for a card's mathematical content.

## Working through a document

Long documents are worked across many sessions, so progress is tracked on disk
rather than in a conversation. `ingest_source` builds a section map using the
first of these that fits:

- **`sections`** — the PDF's embedded outline, which most typeset textbooks have
- **`slides`** — one titled unit per page, for lecture decks
- **`pages`** — bare page numbers, when neither of the above is available

A cursor records which sections are covered. The next section is the first one
not yet covered, not "the one after the last" — sections get skipped and
returned to, and a high-water mark would lose that.

A section is covered once every card drawn from it has been pushed or rejected.
Coverage tracks outstanding work rather than push success, so a card Anki will
never accept does not strand its section: rejecting it settles the section.

## State on disk

    sources/<slug>/
      source.pdf      the original
      pages/*.png     rendered pages
      text/*.txt      text layer, where one exists
      outline.json    section map
      cursor.json     progress
    cards/<slug>.yaml the card ledger

The ledger is the source of truth. Every card records where it came from and,
once pushed, its Anki note id — which is what lets a card be revised later
without losing its review history. The ledger and cursor are written atomically,
so an interrupted write cannot truncate them.

Card lifecycle:

    proposed → approved → pushed
    proposed → rejected
    approved → rejected
    pushed   → orphaned    (note deleted in Anki)

## When things go wrong

Anki and the ledger are separate stores with no shared transaction, so the
failure modes are about keeping them consistent:

- **`AnkiNotRunning`** — Anki is closed, or AnkiConnect is not installed. Nothing
  was changed; start Anki and retry.
- **`AnkiNotResponding`** — Anki accepted the connection but did not answer in
  time, usually mid-sync or behind a dialog. The request may already have been
  applied, so check the collection before retrying rather than pushing again.
- **Partial push** — some notes were rejected, almost always as duplicates. Those
  cards stay `approved` and their section stays uncovered, so pushing again
  retries only what failed. Sections that fully succeeded are still covered.
  A duplicate will be rejected on every retry, so rejecting the card is how you
  settle the section and move on.
- **`LedgerNotSaved`** — notes reached Anki but their ids could not be written to
  disk. This is the one inconsistency the harness cannot repair itself, so the
  error carries the created note ids; record them before retrying, or a re-push
  will duplicate those notes.
- **`orphaned`** — a pushed note was deleted in Anki. The card is marked rather
  than silently recreated, since recreating it would lose the review history the
  note id exists to preserve.

## Development

    uv run pytest                                    # the full suite
    uv run python tests/fixtures/make_fixtures.py    # regenerate test PDFs by hand
    uv run python scripts/smoke.py <path-to.pdf>     # end-to-end, without Anki

Test fixtures are generated rather than committed, so the repository stays
text-only. The tests never contact a real Anki: `tests/fake_anki.py` serves the
AnkiConnect protocol over a real socket.
