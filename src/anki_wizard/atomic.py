"""Atomic file replacement.

The ledger and the cursor are the system's memory of what exists in Anki and
what has been covered. Writing them in place means a crash mid-write leaves a
truncated file -- and for the ledger that is worse than losing an edit, because
the note ids of cards that really are in the user's collection would be gone,
so a re-push would duplicate them. Writing to a sibling temp file and renaming
makes the swap atomic on POSIX: readers see either the old file or the new one.
"""

import os
import tempfile
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # The temp file must share a directory with the target: os.replace is only
    # atomic within a filesystem.
    handle, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
