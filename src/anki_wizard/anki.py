# src/anki_wizard/anki.py
"""AnkiConnect HTTP client.

AnkiConnect runs inside the Anki desktop app, so a refused connection means
Anki is closed -- a routine condition, not a crash, and it gets its own
exception type. Protocol errors arrive in the JSON body with HTTP 200.
"""

from typing import Any

import requests

ANKI_CONNECT_VERSION = 6
NOTE_TYPE = "Basic with Why"

# Connecting is either instant or refused, so a long connect timeout only makes
# the "Anki is closed" case slow to report. Anki answers on its GUI thread and
# can stall behind a sync or a modal dialog, so reads get a generous budget.
CONNECT_TIMEOUT_SECONDS = 3
TIMEOUT_SECONDS = 30

# Enough of a non-AnkiConnect response to identify what is on the port.
_BODY_EXCERPT = 200


class AnkiError(RuntimeError):
    """AnkiConnect returned an error."""


class AnkiNotRunning(AnkiError):
    """Could not reach AnkiConnect: Anki is probably closed."""


class AnkiNotResponding(AnkiError):
    """Anki accepted the connection but did not answer in time.

    Distinct from AnkiNotRunning because the advice differs sharply: the
    request may have been applied server-side, so a blind retry can duplicate
    work. Callers pushing notes should check the collection before retrying.
    """


class AnkiClient:
    def __init__(self, url: str):
        self.url = url

    def _invoke(self, action: str, **params: Any) -> Any:
        payload = {"action": action, "version": ANKI_CONNECT_VERSION, "params": params}
        try:
            response = requests.post(
                self.url,
                json=payload,
                timeout=(CONNECT_TIMEOUT_SECONDS, TIMEOUT_SECONDS),
            )
        except requests.exceptions.Timeout as exc:
            raise AnkiNotResponding(
                f"{action} timed out after {TIMEOUT_SECONDS}s at {self.url}. Anki is "
                "running but did not answer; it may be syncing or showing a dialog. "
                "The request may already have been applied -- check the collection "
                "before retrying."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise AnkiNotRunning(
                "Anki is not running, or the AnkiConnect add-on is not installed. "
                f"Could not reach {self.url}."
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise AnkiError(f"{action} failed at {self.url}: {exc}") from exc

        # AnkiConnect answers 200 even for protocol errors, so any other status
        # means something that is not AnkiConnect is listening on this port.
        if response.status_code != 200:
            raise AnkiError(
                f"{action}: expected 200 from AnkiConnect at {self.url}, got "
                f"{response.status_code}. Is something else listening on that port?"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise AnkiError(
                f"{action}: {self.url} did not return JSON, so it is probably not "
                f"AnkiConnect. Response began: {response.text[:_BODY_EXCERPT]!r}"
            ) from exc
        if not isinstance(body, dict):
            raise AnkiError(
                f"{action}: expected a JSON object from AnkiConnect at {self.url}, "
                f"got {type(body).__name__}."
            )
        if body.get("error") is not None:
            raise AnkiError(f"{action} failed at {self.url}: {body['error']}")
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
        payload = []
        for index, note in enumerate(notes):
            missing = [key for key in ("front", "back") if not note.get(key)]
            if missing:
                raise AnkiError(
                    f"note at position {index} is missing {' and '.join(missing)}; "
                    "refusing to push an incomplete card"
                )
            payload.append(
                {
                    "deckName": deck,
                    "modelName": NOTE_TYPE,
                    "fields": {
                        "Front": note["front"],
                        "Back": note["back"],
                        # Declared even when empty: Anki rejects a field name it
                        # does not know, and an absent field is not a blank one.
                        "Why": note.get("why") or "",
                    },
                    "tags": note.get("tags", []),
                }
            )
        result = self._invoke("addNotes", notes=payload)
        # Positional correspondence is this method's entire contract: the caller
        # marks cards pushed by index. A length mismatch would silently shift
        # note ids onto the wrong cards.
        if not isinstance(result, list) or len(result) != len(notes):
            raise AnkiError(
                f"addNotes returned {result!r} for {len(notes)} notes; expected a "
                "list of the same length. Cannot match ids to cards."
            )
        return result

    def update_note_fields(
        self, note_id: int, front: str, back: str, why: str | None = None
    ) -> None:
        self._invoke(
            "updateNoteFields",
            note={
                "id": note_id,
                "fields": {"Front": front, "Back": back, "Why": why or ""},
            },
        )

    def note_exists(self, note_id: int) -> bool:
        """Whether this exact note is still in the collection.

        AnkiConnect returns an empty dict for a note that has been deleted,
        rather than reporting an error. The returned noteId is checked rather
        than merely the presence of a record: this call guards an overwrite, so
        answering True about some other note would edit a card the user studies
        from.
        """
        info = self._invoke("notesInfo", notes=[note_id])
        if not info or not info[0]:
            return False
        return info[0].get("noteId") == note_id
