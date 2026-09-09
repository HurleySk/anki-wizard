"""Every AnkiConnect action the client sends must actually exist.

fake_anki.py answers whatever action string it is handed, so a misspelled or
invented action produces a green suite and fails only against real Anki. That
is not hypothetical: an earlier version of the migration called
`changeNoteType`, which this AnkiConnect does not implement, and every test
passed.

The snapshot below came from `apiReflect` against AnkiConnect on 2026-09-08.
It cannot notice an action that Anki drops in a later release -- only a live
call could -- but it does catch the failure this suite is otherwise blind to:
a name that never existed. Refresh it with the command in the docstring below
when a new AnkiConnect action is genuinely needed.

This file also carries ordinary FakeAnki-backed tests for client methods, so
that the static name check above and the behavioral tests for the same client
live in one place rather than splitting `anki.py` coverage across files.
"""

import re
from pathlib import Path

from anki_wizard.anki import AnkiClient
from tests.fake_anki import FakeAnki

# uv run python -c "import json,urllib.request as u; \
#   print(sorted(json.load(u.urlopen(u.Request('http://localhost:8765', \
#   data=json.dumps({'action':'apiReflect','version':6, \
#   'params':{'scopes':['actions']}}).encode())))['result']['actions']))"
KNOWN_ACTIONS = {
    "addNote", "addNotes", "addTags", "answerCards", "apiReflect", "areDue",
    "areSuspended", "canAddNote", "canAddNoteWithErrorDetail",
    "canAddNotes", "canAddNotesWithErrorDetail", "cardReviews", "cardsInfo",
    "cardsModTime", "cardsToNotes", "changeDeck", "clearUnusedTags",
    "cloneDeckConfigId", "createDeck", "createModel", "deckNameFromId",
    "deckNames", "deckNamesAndIds", "deleteDecks", "deleteMediaFile",
    "deleteNotes", "exportPackage", "findAndReplaceInModels", "findCards",
    "findModelsById", "findModelsByName", "findNotes", "forgetCards",
    "getActiveProfile", "getCollectionStatsHTML", "getDeckConfig",
    "getDeckStats", "getDecks", "getEaseFactors", "getIntervals",
    "getLatestReviewID", "getMediaDirPath", "getMediaFilesNames",
    "getNoteTags", "getNumCardsReviewedByDay", "getNumCardsReviewedToday",
    "getProfiles", "getReviewsOfCards", "getTags", "guiAddCards",
    "guiAnswerCard", "guiBrowse", "guiCheckDatabase", "guiCurrentCard",
    "guiDeckBrowser", "guiDeckOverview", "guiDeckReview", "guiEditNote",
    "guiExitAnki", "guiImportFile", "guiPlayAudio", "guiReviewActive",
    "guiSelectCard", "guiSelectNote", "guiSelectedNotes", "guiShowAnswer",
    "guiShowQuestion", "guiStartCardTimer", "guiUndo", "importPackage",
    "insertReviews", "loadProfile", "modelFieldAdd",
    "modelFieldDescriptions", "modelFieldFonts", "modelFieldNames",
    "modelFieldRemove", "modelFieldRename", "modelFieldReposition",
    "modelFieldSetDescription", "modelFieldSetFont",
    "modelFieldSetFontSize", "modelFieldsOnTemplates", "modelNameFromId",
    "modelNames", "modelNamesAndIds", "modelStyling", "modelTemplateAdd",
    "modelTemplateRemove", "modelTemplateRename", "modelTemplateReposition",
    "modelTemplates", "multi", "notesInfo", "notesModTime", "relearnCards",
    "reloadCollection", "removeDeckConfigId", "removeEmptyNotes",
    "removeTags", "replaceTags", "replaceTagsInAllNotes",
    "requestPermission", "retrieveMediaFile", "saveDeckConfig",
    "setDeckConfigId", "setDueDate", "setEaseFactors",
    "setSpecificValueOfCard", "storeMediaFile", "suspend", "suspended",
    "sync", "unsuspend", "updateModelStyling", "updateModelTemplates",
    "updateNote", "updateNoteFields", "updateNoteModel", "updateNoteTags",
    "version",
}

# Matches the action string in `self._invoke("actionName"` even when the call
# is wrapped across lines, which several of them are.
_INVOKE = re.compile(r'_invoke\(\s*"([a-zA-Z]+)"')


def _actions_sent_by_the_client() -> set[str]:
    source = (Path(__file__).parent.parent / "src/anki_wizard/anki.py").read_text()
    return set(_INVOKE.findall(source))


def test_the_client_only_sends_actions_ankiconnect_implements():
    sent = _actions_sent_by_the_client()
    assert sent, "found no _invoke calls -- the regex has drifted from the source"
    unknown = sent - KNOWN_ACTIONS
    assert not unknown, (
        f"anki.py sends {sorted(unknown)}, which AnkiConnect does not implement. "
        "If the action is real and newer than the snapshot, refresh KNOWN_ACTIONS "
        "using the command in this file's header."
    )


def test_the_scan_finds_every_invoke_call():
    """Guards the guard: a regex that silently matched nothing would make the
    check above vacuous, and it passes while finding zero actions."""
    source = (Path(__file__).parent.parent / "src/anki_wizard/anki.py").read_text()
    assert len(_INVOKE.findall(source)) == source.count("._invoke(")


def test_deck_names_returns_the_tree():
    with FakeAnki() as fake:
        fake.set_response("deckNames", ["Default", "Stats", "Stats::Unit I"])
        client = AnkiClient(fake.url)
        assert client.deck_names() == ["Default", "Stats", "Stats::Unit I"]


def test_retrieve_media_file_decodes_base64():
    """AnkiConnect returns media base64-encoded; callers want the bytes."""
    import base64

    with FakeAnki() as fake:
        fake.set_response("retrieveMediaFile", base64.b64encode(b"PNGDATA").decode())
        client = AnkiClient(fake.url)
        assert client.retrieve_media_file("figure.png") == b"PNGDATA"


def test_retrieve_media_file_returns_none_when_absent():
    """A missing file comes back as False, not an error, so it must be checked."""
    with FakeAnki() as fake:
        fake.set_response("retrieveMediaFile", False)
        client = AnkiClient(fake.url)
        assert client.retrieve_media_file("gone.png") is None
