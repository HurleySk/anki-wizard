"""Create the three-field note type and move existing notes onto it.

Usage: uv run python scripts/migrate_note_type.py [deck]

Run once, with Anki open. Idempotent: creating an existing model and migrating
an already-migrated note are both no-ops, so a partial run can be repeated.

Review history lives on the card rather than the note type, so notes keep their
scheduling across the change.
"""

import sys
from pathlib import Path

from anki_wizard.anki import NOTE_TYPE, AnkiClient, AnkiError
from anki_wizard.config import load_config
from anki_wizard.paths import Paths

FRONT_TEMPLATE = "{{Front}}"

# Collapsed by default: a long derivation must not compete with the answer the
# user is grading themselves on. <details> needs no JavaScript, which matters
# because AnkiMobile and AnkiDroid render the same template.
BACK_TEMPLATE = """{{FrontSide}}

<hr id=answer>

{{Back}}

{{#Why}}
<details class="why">
  <summary>Why?</summary>
  <div>{{Why}}</div>
</details>
{{/Why}}
"""

CSS = """.card {
  font-family: -apple-system, system-ui, sans-serif;
  font-size: 20px;
  text-align: center;
  color: black;
  background-color: white;
}
.why {
  margin-top: 1.2em;
  text-align: left;
  font-size: 16px;
}
.why summary {
  cursor: pointer;
  color: #666;
  font-size: 14px;
}
.why div { margin-top: 0.6em; }
"""


def main() -> int:
    paths = Paths(root=Path("."))
    config = load_config(paths.config_file())
    # A whole-collection query would drag every unrelated Basic note along, so
    # the deck bounds the migration. The command line overrides config for a
    # collection whose cards were pushed elsewhere.
    deck = sys.argv[1] if len(sys.argv) > 1 else config.deck
    if not deck:
        print("usage: migrate_note_type.py [deck]", file=sys.stderr)
        print("no deck given and none configured in config.yaml", file=sys.stderr)
        return 2

    client = AnkiClient(config.anki_connect_url)
    print(f"anki:  {config.anki_connect_url}")
    print(f"deck:  {deck}")
    print(f"model: {NOTE_TYPE}")

    if NOTE_TYPE in client.model_names():
        print(f"\nnote type {NOTE_TYPE!r} already exists; leaving it alone")
    else:
        print(f"\ncreating note type {NOTE_TYPE!r} ...")
        client.create_model(
            NOTE_TYPE,
            ["Front", "Back", "Why"],
            front=FRONT_TEMPLATE,
            back=BACK_TEMPLATE,
            css=CSS,
        )
        print("  created")

    query = f'note:Basic deck:"{deck}"'
    print(f"\nsearching for notes to migrate: {query}")
    note_ids = client.find_notes(query)
    if not note_ids:
        print("  none found; nothing to migrate")
        return 0

    # updateNoteModel rewrites one note's content wholesale, so each note's
    # existing fields and tags have to be read back and passed through -- there
    # is no batch form and no field-mapping shorthand.
    print(f"  found {len(note_ids)} note(s); reading their current content ...")
    records = client.notes_info(note_ids)

    migrated = 0
    failed: list[tuple[int, str]] = []
    for note_id, record in zip(note_ids, records):
        if not record:
            failed.append((note_id, "note no longer exists"))
            continue
        fields = record.get("fields") or {}
        front = (fields.get("Front") or {}).get("value", "")
        back = (fields.get("Back") or {}).get("value", "")
        if not front:
            # Every field is overwritten by this call, so a note whose content
            # did not come back would be blanked rather than converted.
            failed.append((note_id, "could not read its Front field"))
            continue
        try:
            client.update_note_model(
                note_id,
                NOTE_TYPE,
                {"Front": front, "Back": back, "Why": ""},
                list(record.get("tags") or []),
            )
        except AnkiError as exc:
            # One bad note must not strand the other 31 half-migrated.
            failed.append((note_id, str(exc)))
            continue
        migrated += 1

    print(f"\nmigrated {migrated} of {len(note_ids)} note(s); Why is empty on each")
    if failed:
        print(f"{len(failed)} note(s) failed:")
        for note_id, reason in failed:
            print(f"  {note_id}: {reason}")
        print("Re-running is safe: migrated notes are no longer note:Basic.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
