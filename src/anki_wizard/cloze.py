"""Counting cloze deletions in note text.

Anki generates one card per distinct deletion number, so the set of numbers in
a field determines how many cards a note produces. An edit that drops a number
deletes that card and its scheduling history -- which is why this is a guard
and not a warning.

Pure string work: no Anki, no I/O, so the rules can be tested exhaustively.
"""

import re

# Matches the opening of a deletion and captures its number. The closing brace
# is deliberately not matched: deletions routinely contain MathJax, so their
# content has braces of its own and pairing them here would need a real parser
# for no gain -- the number is all this module needs.
_DELETION = re.compile(r"\{\{c(\d+)::")


def cloze_numbers(text: str) -> set[int]:
    """The distinct cloze deletion numbers in `text`.

    A number repeated across several deletions still generates one card, so the
    result is a set rather than a count.
    """
    return {int(match) for match in _DELETION.findall(text)}
