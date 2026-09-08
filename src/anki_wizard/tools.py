"""The tools a Claude agent calls.

Each returns a plain dict with no dependency on the calling conversation, so an
MCP server can wrap these functions unchanged.
"""

import shutil
import webbrowser
from dataclasses import asdict, replace
from pathlib import Path

from anki_wizard.anki import AnkiClient
from anki_wizard.atomic import write_text_atomic
from anki_wizard.cursor import advance, load_cursor, next_section, save_cursor
from anki_wizard.ledger import (
    _now,
    append_cards,
    edit_card,
    load_ledger,
    save_ledger,
    transition,
)
from anki_wizard.models import CardSource
from anki_wizard.outline import build_outline, load_outline, save_outline
from anki_wizard.paths import Paths
from anki_wizard.pdf import extract_text, render_pages
from anki_wizard.render import render_html


class LedgerNotSaved(RuntimeError):
    """Notes reached Anki but their ids could not be recorded.

    The one inconsistency this system cannot write its way out of: Anki and the
    ledger are separate stores with no shared transaction. Carries the created
    note ids so the state can be repaired by hand.
    """


DEFAULT_MAX_PAGES_PER_READ = 10

TEXT_LAYER_WARNING = (
    "Read the page image for all mathematical content. The extracted text is a "
    "lossy hint only: it mangles LaTeX list markers and displayed equations."
)


def _require_outline(slug: str, paths: Paths):
    path = paths.outline_file(slug)
    if not path.exists():
        raise FileNotFoundError(f"source {slug!r} is not ingested; run ingest_source")
    return load_outline(path)


def ingest_source(pdf: Path, slug: str, paths: Paths, dpi: int = 150) -> dict:
    """Render pages, extract text, build the section map, initialise the cursor.

    Safe to re-run: pages already rendered are skipped, which is what makes an
    interrupted ingest resumable.
    """
    pdf = Path(pdf).expanduser()
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    paths.ensure_source_dirs(slug)

    stored_pdf = paths.source_pdf(slug)
    if not stored_pdf.exists():
        shutil.copy2(pdf, stored_pdf)

    render_pages(stored_pdf, paths.pages_dir(slug), dpi=dpi)

    outline = build_outline(stored_pdf, slug=slug)
    save_outline(paths.outline_file(slug), outline)

    for page in range(1, outline.pages + 1):
        text = extract_text(stored_pdf, page)
        if text.strip():
            paths.page_text(slug, page).write_text(text)

    cursor_path = paths.cursor_file(slug)
    if not cursor_path.exists():
        save_cursor(cursor_path, load_cursor(cursor_path))

    return {
        "slug": slug,
        "pages": outline.pages,
        "structure": outline.structure,
        "sections": [asdict(s) for s in outline.sections],
    }


def get_progress(slug: str, paths: Paths) -> dict:
    outline = _require_outline(slug, paths)
    cursor = load_cursor(paths.cursor_file(slug))
    upcoming = next_section(outline, cursor)
    return {
        "slug": slug,
        "structure": outline.structure,
        "position": cursor.position,
        "covered": cursor.covered,
        "skipped": cursor.skipped,
        "remaining": len(outline.sections) - len(cursor.covered),
        "next": asdict(upcoming) if upcoming else None,
        "complete": upcoming is None,
    }


def read_section(
    slug: str,
    section_id: str | None,
    paths: Paths,
    max_pages: int = DEFAULT_MAX_PAGES_PER_READ,
) -> dict:
    """Return a section's page images and text for the agent to read.

    Passing section_id=None reads the next uncovered section.
    """
    outline = _require_outline(slug, paths)

    if section_id is None:
        section = next_section(outline, load_cursor(paths.cursor_file(slug)))
        if section is None:
            raise ValueError(f"source {slug!r} is fully covered")
    else:
        section = outline.section(section_id)
        if section is None:
            raise ValueError(f"no section {section_id!r} in source {slug!r}")

    page_numbers = list(range(section.start, min(section.end, outline.pages + 1)))
    truncated = len(page_numbers) > max_pages
    pages = []
    for number in page_numbers[:max_pages]:
        text_file = paths.page_text(slug, number)
        pages.append(
            {
                "number": number,
                "image": str(paths.page_image(slug, number)),
                "text": text_file.read_text() if text_file.exists() else "",
            }
        )

    return {
        "slug": slug,
        "section": asdict(section),
        "pages": pages,
        "truncated": truncated,
        "note": TEXT_LAYER_WARNING,
    }


def propose_cards(
    slug: str,
    proposals: list[dict],
    section_id: str | None,
    paths: Paths,
    default_tags: list[str] | None = None,
) -> dict:
    """Append proposed cards to the ledger.

    Pass section_id=None with a slug that was never ingested for cards not drawn
    from a document -- "conversation" is the conventional name, but any slug
    works, which is what lets conversation cards be grouped by topic instead of
    piling into one ledger. Nothing here touches Anki.
    """
    for proposal in proposals:
        if not (proposal.get("front") or "").strip() or not (
            proposal.get("back") or ""
        ).strip():
            raise ValueError("every card needs a non-empty front and back")

    if section_id is None and not paths.outline_file(slug).exists():
        source = CardSource(slug=slug)
    else:
        outline = _require_outline(slug, paths)
        section = outline.section(section_id) if section_id else None
        if section is None:
            raise ValueError(f"no section {section_id!r} in source {slug!r}")
        source = CardSource(
            slug=slug,
            section=section.id,
            pages=list(range(section.start, min(section.end, outline.pages + 1))),
        )

    tags = list(default_tags or [])
    enriched = [
        {**p, "tags": sorted(set(list(p.get("tags", [])) + tags))} for p in proposals
    ]

    added = append_cards(paths.ledger_file(slug), enriched, source)
    return {"added": len(added), "cards": [asdict(c) for c in added]}


def review_cards(slug: str, decisions: dict, paths: Paths) -> dict:
    """Apply approve, reject, and edit decisions to ledger entries.

    A decision is either the string "approve"/"reject", or a dict
    {"edit": {...}, "then": "approve"} to edit content and optionally
    transition in one call.
    """
    ledger_path = paths.ledger_file(slug)
    cards = load_ledger(ledger_path)
    by_id = {c.id: i for i, c in enumerate(cards)}

    updated: dict[str, str] = {}
    for card_id, decision in decisions.items():
        if card_id not in by_id:
            raise ValueError(f"no card {card_id!r} in ledger for {slug!r}")
        index = by_id[card_id]
        card = cards[index]

        if isinstance(decision, dict):
            edits = decision.get("edit") or {}
            if edits:
                card = edit_card(
                    card,
                    front=edits.get("front"),
                    back=edits.get("back"),
                    tags=edits.get("tags"),
                )
            follow_up = decision.get("then")
        else:
            follow_up = decision

        if follow_up == "approve":
            card = transition(card, "approved")
        elif follow_up == "reject":
            card = transition(card, "rejected")
        elif follow_up is not None:
            raise ValueError(f"unknown review action {follow_up!r}")

        cards[index] = card
        updated[card_id] = card.state

    save_ledger(ledger_path, cards)
    covered = _cover_settled_sections(slug, cards, paths)
    return {"updated": updated, "sections_covered": covered}


def skip_section(slug: str, section_id: str, reason: str, paths: Paths) -> dict:
    """Cover a section that yields no cards, recording why.

    Coverage is otherwise derived from cards, so a section holding nothing worth
    recalling -- a title slide, a section divider, a page of motivation -- could
    never settle and would block the cursor behind it. Skipping is a curation
    decision like rejecting a card, so it carries a reason rather than silently
    marking the section done.
    """
    if not reason or not reason.strip():
        raise ValueError("a skip needs a reason; without one it reads as lost work")

    outline = _require_outline(slug, paths)
    if outline.section(section_id) is None:
        raise ValueError(f"no section {section_id!r} in source {slug!r}")

    # Cards and a skip are contradictory claims about the same section. Skipping
    # anyway would strand proposals the user never got to review.
    ledger_path = paths.ledger_file(slug)
    if ledger_path.exists():
        live = [
            card
            for card in load_ledger(ledger_path)
            if card.source.section == section_id and card.state != "rejected"
        ]
        if live:
            raise ValueError(
                f"section {section_id!r} has cards; reject them before skipping"
            )

    cursor_path = paths.cursor_file(slug)
    cursor = load_cursor(cursor_path)
    cursor = advance(outline, cursor, section_id)
    cursor.skipped[section_id] = reason.strip()
    save_cursor(cursor_path, cursor)

    return {
        "slug": slug,
        "section": section_id,
        "reason": reason.strip(),
        "covered": cursor.covered,
    }


def render_pad(
    blocks: list[dict], paths: Paths, open_browser: bool = True, title: str = "Study pad"
) -> dict:
    """Write the scratch page and open it.

    The pad is deliberately ephemeral -- every render replaces it. Most
    derivations are worth one look, and an accumulating scratch file becomes
    something to manage. promote_pad is how a page that earned its keep escapes
    that.
    """
    html = render_html(blocks, title=title)

    pad = paths.pad_file()
    write_text_atomic(pad, html)

    if open_browser:
        webbrowser.open(pad.as_uri())

    return {"path": str(pad), "blocks": len(blocks)}


def _cover_settled_sections(slug: str, cards: list, paths: Paths) -> list[str]:
    """Cover sections that have cards pushed and nothing left awaiting a push.

    Coverage cannot depend only on a push succeeding. Anki rejects a duplicate
    on every retry, so a card can be unpushable; rejecting it is how the user
    settles the section, and without this the section would stay "next"
    forever with no way to move past it.
    """
    # A source-less slug has no outline and so covers nothing. This subsumes
    # the "conversation" case: there is no section map to advance through.
    outline_path = paths.outline_file(slug)
    if not outline_path.exists():
        return []

    pending: set[str] = set()
    touched: set[str] = set()
    for card in cards:
        section = card.source.section
        if not section:
            continue
        touched.add(section)
        if card.state in ("proposed", "approved"):
            pending.add(section)

    # A section counts as settled once every card drawn from it has reached a
    # terminal or pushed state -- including the case where they were all
    # rejected, which is the user deciding the section yielded nothing worth
    # keeping. Requiring a pushed card would leave that section stuck.
    settled = touched - pending
    if not settled:
        return []

    outline = load_outline(outline_path)
    cursor_path = paths.cursor_file(slug)
    cursor = load_cursor(cursor_path)
    newly: list[str] = []
    for section_id in sorted(settled):
        if section_id in cursor.covered or outline.section(section_id) is None:
            continue
        cursor = advance(outline, cursor, section_id)
        newly.append(section_id)
    if newly:
        save_cursor(cursor_path, cursor)
    return newly


def push_to_anki(slug: str, client: AnkiClient, deck: str, paths: Paths) -> dict:
    """Send approved cards to Anki and record the resulting note ids.

    Preflights with a version call so a closed Anki fails before anything is
    mutated. On a partial failure the successful cards are marked pushed and the
    rest stay approved, so a re-push retries only what failed. Coverage is
    withheld from any section that had a failure; sections that fully succeeded
    are covered, since their cards will never be pending again.
    """
    client.version()

    ledger_path = paths.ledger_file(slug)
    cards = load_ledger(ledger_path)
    pending = [(i, c) for i, c in enumerate(cards) if c.state == "approved"]
    if not pending:
        return {"pushed": 0, "failed": 0, "message": "no approved cards to push"}

    client.ensure_deck(deck)
    note_ids = client.add_notes(
        deck,
        [{"front": c.front, "back": c.back, "tags": c.tags} for _, c in pending],
    )

    pushed_sections: set[str] = set()
    pushed = 0
    failed = 0
    for (index, card), note_id in zip(pending, note_ids):
        if note_id is None:
            failed += 1
            cards[index] = replace(
                card,
                history=card.history + [{"at": _now(), "action": "push-failed"}],
            )
            continue
        pushed += 1
        cards[index] = transition(card, "pushed", anki_note_id=note_id)
        # Conversation cards have no section and so cover nothing.
        if card.source.section:
            pushed_sections.add(card.source.section)

    try:
        save_ledger(ledger_path, cards)
    except Exception as exc:
        # The notes are already in Anki. If their ids are not recorded, the
        # cards stay approved and the next push duplicates them -- so fail
        # loudly with the ids in the message rather than letting the error
        # surface anonymously. The catch is deliberately broad: what matters
        # is that the ledger did not get written, not why.
        created = {
            card.id: note_id
            for (_, card), note_id in zip(pending, note_ids)
            if note_id is not None
        }
        raise LedgerNotSaved(
            f"{len(created)} notes were created in Anki but the ledger at "
            f"{ledger_path} could not be written ({exc}). Re-pushing will "
            "duplicate them. Record these ids before retrying: "
            f"{created}"
        ) from exc

    # A section is covered once it has cards in Anki and nothing left awaiting
    # a push -- the same rule review_cards applies, so a section blocked by an
    # unpushable duplicate is released when that card is finally rejected.
    advanced = _cover_settled_sections(slug, cards, paths)

    return {
        "pushed": pushed,
        "failed": failed,
        "sections_covered": advanced,
        "message": (
            "partial push: failed cards remain approved and will be retried"
            if failed
            else "all approved cards pushed"
        ),
    }


def revise_card(
    slug: str,
    card_id: str,
    client: AnkiClient,
    paths: Paths,
    front: str | None = None,
    back: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Edit a card, updating Anki in place when the card has been pushed.

    A pushed card keeps its scheduling and review history, which is the whole
    reason the note id is stored. If the note has been deleted in Anki the card
    is marked orphaned rather than silently recreated.
    """
    ledger_path = paths.ledger_file(slug)
    cards = load_ledger(ledger_path)
    index = next((i for i, c in enumerate(cards) if c.id == card_id), None)
    if index is None:
        raise ValueError(f"no card {card_id!r} in ledger for {slug!r}")
    card = cards[index]

    if card.state == "pushed":
        if not client.note_exists(card.anki_note_id):
            cards[index] = transition(card, "orphaned")
            save_ledger(ledger_path, cards)
            return {
                "id": card_id,
                "state": "orphaned",
                "message": "note no longer exists in Anki; card marked orphaned",
            }

    card = edit_card(card, front=front, back=back, tags=tags)

    if card.state == "pushed":
        client.update_note_fields(card.anki_note_id, card.front, card.back)

    cards[index] = card
    save_ledger(ledger_path, cards)
    return {"id": card_id, "state": card.state, "message": "card revised"}
