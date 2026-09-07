# src/anki_wizard/anki.py
"""AnkiConnect HTTP client.

AnkiConnect runs inside the Anki desktop app, so a refused connection means
Anki is closed -- a routine condition, not a crash, and it gets its own
exception type. Protocol errors arrive in the JSON body with HTTP 200.
"""

from typing import Any

import requests

ANKI_CONNECT_VERSION = 6
NOTE_TYPE = "Basic"
TIMEOUT_SECONDS = 30


class AnkiError(RuntimeError):
    """AnkiConnect returned an error."""


class AnkiNotRunning(AnkiError):
    """Could not reach AnkiConnect: Anki is probably closed."""


class AnkiClient:
    def __init__(self, url: str):
        self.url = url

    def _invoke(self, action: str, **params: Any) -> Any:
        payload = {"action": action, "version": ANKI_CONNECT_VERSION, "params": params}
        try:
            response = requests.post(self.url, json=payload, timeout=TIMEOUT_SECONDS)
        except requests.exceptions.ConnectionError as exc:
            raise AnkiNotRunning(
                "Anki is not running, or the AnkiConnect add-on is not installed. "
                f"Could not reach {self.url}."
            ) from exc
        response.raise_for_status()
        body = response.json()
        if body.get("error"):
            raise AnkiError(body["error"])
        return body.get("result")

    def version(self) -> int:
        return self._invoke("version")

    def ensure_deck(self, deck: str) -> None:
        """Create the deck if it does not exist. Existing decks are untouched."""
        self._invoke("createDeck", deck=deck)

    def add_notes(self, deck: str, notes: list[dict]) -> list[int | None]:
        """Add notes, returning one id per note.

        A null in the returned list means that note was rejected, almost always
        as a duplicate. Positions correspond to the input list.
        """
        payload = [
            {
                "deckName": deck,
                "modelName": NOTE_TYPE,
                "fields": {"Front": note["front"], "Back": note["back"]},
                "tags": note.get("tags", []),
            }
            for note in notes
        ]
        return self._invoke("addNotes", notes=payload)

    def update_note_fields(self, note_id: int, front: str, back: str) -> None:
        self._invoke(
            "updateNoteFields",
            note={"id": note_id, "fields": {"Front": front, "Back": back}},
        )

    def note_exists(self, note_id: int) -> bool:
        """Whether a note is still in the collection.

        AnkiConnect returns an empty dict for a note that has been deleted,
        rather than reporting an error.
        """
        info = self._invoke("notesInfo", notes=[note_id])
        return bool(info) and bool(info[0])
