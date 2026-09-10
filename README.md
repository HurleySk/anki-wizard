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
| `propose_cards(slug, proposals, section_id, paths)` | Add proposed cards to the ledger. Pass `section_id=None` with an uningested slug for cards not from a document. |
| `review_cards(slug, decisions, paths)` | Approve, reject, or edit proposed cards. |
| `skip_section(slug, section_id, reason, paths)` | Cover a section that yields no cards, recording why. |
| `render_pad(blocks, paths, viewer)` | Render prose, math, derivations, and plots to a local HTML page, served for VS Code or opened in a browser. |
| `promote_pad(name, paths)` | Keep the current pad as a named note. |
| `push_to_anki(slug, client, deck, paths)` | Send approved cards to Anki, record note ids, advance the cursor. Cards carrying a lecture go to its subdeck. |
| `revise_card(slug, card_id, client, paths, ...)` | Edit a card, updating Anki in place if it was already pushed. |
| `search_collection(query, client, limit)` | Find notes anywhere in the collection, by Anki search syntax. |
| `read_note(note_id, client)` | One note in full: every field by its real name, its deck, tags, and media. |
| `list_decks(client)` | Every deck and subdeck in the collection. |
| `note_blocks(note_id, client)` | Pad blocks showing a note, with its media fetched and inlined. |
| `edit_note(note_id, changes, client, paths, force)` | Edit a note this harness did not create, behind field-name and cloze guards. |

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
    s.search('deck:"Intro to Probability" network')
    s.pad_note(1739985246842)              # the card, rendered, with its images
    s.edit_note(1739985246842, {"Answer": "..."})

## Cards from conversation

Not every card comes from a document. Working a problem with the agent and
carding what was hard is a first-class flow: pass `section_id=None` with a slug
that was never ingested.

    s.propose("pset-3", [{"front": ..., "back": ...}])

Any slug works. `conversation` is the conventional catch-all, but a narrower
name gives those cards their own ledger and keeps them findable once there are
hundreds. Such cards carry no section or pages and never advance a cursor.

## The study pad

Not everything is a card. Working a derivation with the agent needs rendered
mathematics, and LaTeX source in a terminal is unreadable.

    s.pad([
        {"type": "prose", "text": r"For an indicator, \(X^2 = X\):"},
        {"type": "steps", "steps": [
            {"tex": r"\mathbb{E}[X] = 0\cdot(1-p) + 1\cdot p"},
            {"tex": "= p", "why": "the zero branch contributes nothing"},
        ]},
    ])

This writes `pad/pad.html` and opens it. Block types are `prose`, `math`,
`steps`, `figure` (a matplotlib figure, embedded), `image` (bytes or a path,
embedded), and `note` (an Anki note, its cloze deletions revealed and its media
inlined).

Set `pad_viewer` in `config.yaml` to choose where it appears:

| `pad_viewer` | What happens |
| --- | --- |
| `vscode` (default) | Serves `pad/` on `127.0.0.1:8899` and returns the URL. Clicking it opens the rendered page in a VS Code tab. |
| `browser` | Opens the file directly in the default browser. |
| `none` | Neither; the result still carries the path. |

The `vscode` viewer returns a URL rather than opening anything, because nothing
reachable from a script opens a rendered tab: VS Code's Simple Browser and the
Live Preview extension both declare no URI handler, and there is no CLI flag to
run an editor command. An `http://` URL that VS Code turns into a link is the
one route that works, so the agent hands you the URL and you click it.

The server runs detached, so the URL still works after the process that
rendered the pad has exited, and a later render reuses it rather than starting
a second. It is bound to loopback and rooted at `pad/`, so the rest of the
repository is not exposed; kept notes under `pad/notes/` are reachable through
the same URL.

It shuts itself down once nothing has fetched the pad for
`pad_server_timeout_minutes` (30 by default), so a forgotten server does not run
indefinitely. To stop one early:

    uv run python scripts/stop_pad.py

The pad is **ephemeral**: every render replaces it. When one is worth keeping:

    s.keep("bernoulli-moments")      # -> pad/notes/bernoulli-moments.html

Or turn it into cards through the normal flow, which is `propose_cards` with a
topic slug. The pad is a study surface, not a second deck: it does not preview
cards or browse the ledger, because Anki and the terminal already do those.

## The wider collection

Most of a real collection is not from this harness: shared decks, imported
courses, notes made by hand over years. Those are readable and workable too.

    s.search('deck:"Intro to Probability" independence')
    s.note(1739985246842)
    s.pad_note(1739985246842)

A note this harness did not create can also be corrected. Editing one **adopts**
it: an entry appears in `cards/<deck-slug>.yaml` holding a reference — note id,
model, deck, field names, history — and never a copy of its content, so the
ledger cannot show you something Anki no longer holds.

    s.edit_note(1739985246842, {"Answer": "..."})

Two guards stand in front of every such write. A field name that is not on the
note is refused, so a typo cannot blank a field or invent one. And an edit that
removes a cloze deletion is refused, because Anki generates one card per
deletion and dropping one deletes that card together with its review history;
`force=True` is the way past it when that is genuinely intended.

## Lectures and subdecks

A card can carry a `lecture`, and push sends it to that subdeck of the
configured deck. The deck is the course; the field holds the path below it, so
a unit level costs nothing extra:

    # config.yaml -> deck: Fundamentals of Statistics

    s.propose("stats-ch1", [...], section_id="21",
              lecture="Unit I: Introduction to Statistics::L01 What is Statistics?")
    s.push("stats-ch1")
    # -> Fundamentals of Statistics
    #      -> Unit I: Introduction to Statistics
    #           -> L01 What is Statistics?

A card without a lecture goes to the base deck, so the field is optional and
existing ledgers keep working.

The lecture is recorded per card rather than per document. One PDF can span
several lectures, one lecture can draw on several PDFs, and conversation cards
-- which have no document -- can be filed alongside the lecture they came up in.

Moving a card between lectures preserves its review history, because Anki keeps
scheduling on the card rather than on the deck:

    s.revise("stats-ch1", "c-0007", lecture="Unit I: ...::L02 Parametric Inference")

To refile a whole slug at once:

    uv run python scripts/assign_lecture.py stats-ch1 \
        "Unit I: Introduction to Statistics::L01 What is Statistics?"
    # dry run; add --apply to make the change

## The why field

Cards carry an optional third field holding the reasoning behind the answer. It
renders collapsed behind a "Why?" toggle, so it never competes with the answer
you are grading yourself on, and a card without one shows no toggle at all.

    s.propose("pset-3", [{"front": ..., "back": ...,
                          "why": "Both sides are indicators, so squaring changes nothing."}])

Or add one to a card that already exists:

    s.revise("stats-ch1", "c-0007", why="...")

This needs the `Basic with Why` note type. `scripts/migrate_note_type.py`
creates it and moves existing notes onto it, preserving content, tags, and
review history; it is deck-scoped and safe to re-run.

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

Not every section earns a card. A title slide or a page of motivation holds
nothing worth recalling, and since coverage is derived from cards, such a section
could never settle and would block the cursor behind it. `skip_section` covers it
explicitly and records why, so a deliberate pass stays distinguishable from lost
work — `get_progress` reports the reasons under `skipped`.

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

## License

MIT. See `LICENSE`.
