"""Counting cloze deletions in note text.

Anki generates one card per distinct deletion number, so the set of numbers in
a field determines how many cards a note produces. An edit that drops a number
deletes that card and its scheduling history -- which is why this is a guard
and not a warning.

Pure string work: no Anki, no I/O, so the rules can be tested exhaustively.
"""

import re

# Matches the opening of a deletion and captures its ordinal. The closing brace
# is deliberately not matched: deletions routinely contain MathJax, so their
# content has braces of its own and pairing them here would need a real parser
# for no gain -- the ordinal is all this module needs.
#
# The ordinal is comma-separated because one deletion can feed several cards:
# {{c2,3::text}} generates both card 2 and card 3. Missing that form would be
# the one failure this module cannot afford, since an unseen number in the text
# before an edit reads as nothing lost when the edit removes it.
_DELETION = re.compile(r"\{\{c([\d,]+)::")


def cloze_numbers(text: str) -> set[int]:
    """The distinct cloze deletion numbers in `text`.

    A number repeated across several deletions still generates one card, so the
    result is a set rather than a count.
    """
    return {
        int(part)
        for ordinal in _DELETION.findall(text)
        for part in ordinal.split(",")
        # Anki drops a part that is not a number rather than rejecting the
        # marker, so "{{c1,::x}}" is still card 1.
        if part.isdigit()
    }
