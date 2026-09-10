"""Assign a lecture to a slug's cards and refile them into its subdeck.

Usage:
    uv run python scripts/assign_lecture.py <slug> "<lecture>" [--apply]

Without --apply this reports what it would do and changes nothing. Run it with
Anki open; cards already pushed are moved in Anki, and moving a card preserves
its scheduling because review history lives on the card, not on its deck.

Idempotent: a card already carrying the lecture and already in the right deck
is left alone, so an interrupted run can simply be repeated.
"""

import sys
from pathlib import Path

from anki_wizard.anki import AnkiClient, AnkiError, AnkiNotRunning
from anki_wizard.atomic import locked
from anki_wizard.config import load_config
from anki_wizard.ledger import cards_only, load_ledger, save_ledger
from anki_wizard.models import Card
from anki_wizard.paths import Paths
from anki_wizard.tools import deck_for


def main(argv: list[str]) -> int:
    args = [a for a in argv if a != "--apply"]
    apply = "--apply" in argv
    if len(args) != 2:
        print(__doc__)
        return 2
    slug, lecture = args
    lecture = lecture.strip()
    if not lecture:
        print("refusing an empty lecture name: it would target the base deck")
        return 2

    paths = Paths(root=Path("."))
    config = load_config(paths.config_file())
    client = AnkiClient(config.anki_connect_url)

    ledger_path = paths.ledger_file(slug)
    cards = load_ledger(ledger_path)
    if not cards:
        print(f"no ledger for {slug!r} at {ledger_path}")
        return 1

    target = deck_for(config.deck, lecture)
    # cards_only: an adopted note has no .state or .lecture, and this survey
    # only computes what to print and which ids to relabel below -- it is
    # never the list a save writes back, so narrowing it here is safe.
    # Rejected cards never reached Anki and never will, so refiling them would
    # only add noise to the ledger's history.
    live = [c for c in cards_only(cards) if c.state != "rejected"]
    to_move = [c for c in live if c.state == "pushed" and c.lecture != lecture]
    to_label = [c for c in live if c.lecture != lecture]

    print(f"slug:    {slug}")
    print(f"lecture: {lecture}")
    print(f"deck:    {target}")
    print(f"cards:   {len(live)} live ({len(cards) - len(live)} rejected, skipped)")
    print(f"  to label in the ledger: {len(to_label)}")
    print(f"  to move in Anki:        {len(to_move)}")
    if not apply:
        print("\ndry run -- nothing changed. Re-run with --apply to make it so.")
        return 0
    if not to_label and not to_move:
        print("\nnothing to do.")
        return 0

    try:
        client.version()
        if to_move:
            client.ensure_deck(target)
    except AnkiNotRunning as exc:
        print(f"\n{exc}")
        return 1

    moved = 0
    failures: list[str] = []
    failed_ids: set[str] = set()
    for card in to_move:
        try:
            card_ids = client.cards_of_note(card.anki_note_id)
            if not card_ids:
                failures.append(f"{card.id}: note {card.anki_note_id} is gone from Anki")
                failed_ids.add(card.id)
                continue
            client.change_deck(card_ids, target)
            moved += 1
        except AnkiError as exc:
            failures.append(f"{card.id}: {exc}")
            failed_ids.add(card.id)

    # The ledger is written after the moves so a card is never labelled with a
    # lecture its note did not actually reach. It is re-read under the lock
    # because the Anki round-trips above take long enough for a session working
    # the same slug to have written in the meantime.
    labelled = 0
    relabel = {c.id for c in to_label} - failed_ids
    with locked(ledger_path):
        # Not cards_only here: this list is the one save_ledger writes back,
        # and an adopted note has no .id to match against relabel, so it is
        # skipped by the isinstance check rather than dropped from the list.
        cards = load_ledger(ledger_path)
        for index, card in enumerate(cards):
            if isinstance(card, Card) and card.id in relabel and card.lecture != lecture:
                cards[index].lecture = lecture
                labelled += 1
        save_ledger(ledger_path, cards)

    print(f"\nmoved in Anki:      {moved}")
    print(f"labelled in ledger: {labelled}")
    if failures:
        print(f"\n{len(failures)} failed:")
        for line in failures:
            print(f"  {line}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
