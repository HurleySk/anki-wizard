"""Atomic, durable, mutually-exclusive writes to the state files.

The ledger and the cursor are the system's memory of what exists in Anki and
what has been covered. Writing them in place means a crash mid-write leaves a
truncated file -- and for the ledger that is worse than losing an edit, because
the note ids of cards that really are in the user's collection would be gone,
so a re-push would duplicate them. Writing to a sibling temp file and renaming
makes the swap atomic on POSIX: readers see either the old file or the new one.

Atomicity is not isolation, though. Every mutation of the ledger or the cursor
is a read-modify-write, so two of them interleaving silently discards one side's
work. `locked` guards the whole sequence; nothing else prevents that. It leaves
a `.<name>.lock` sibling behind on purpose -- deleting it would race the next
writer that has already opened it.
"""

import contextlib
import os
import tempfile
import threading
from collections.abc import Iterator
from pathlib import Path

try:
    import fcntl
except ImportError:
    # Windows has no flock. Everything else here still works, so degrade to
    # single-process locking rather than making the package unimportable.
    fcntl = None

# flock is per open-file-description, so a second os.open in the same thread
# blocks against the first and hangs with no error. Counting the depth keeps a
# nested acquisition -- a helper that locks calling another that locks -- from
# wedging the process.
_held = threading.local()


@contextlib.contextmanager
def locked(path: Path) -> Iterator[None]:
    """Hold an exclusive lock covering one read-modify-write of `path`.

    The lock lives in a sibling file rather than the target: the target gets
    replaced by rename on every write, and a lock on a replaced inode guards
    nothing. Blocks until the other writer is done, and is reentrant.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f".{path.name}.lock"
    key = str(lock_path.resolve())

    depth = getattr(_held, "depth", None)
    if depth is None:
        depth = _held.depth = {}
    if key in depth:
        depth[key] += 1
        try:
            yield
        finally:
            depth[key] -= 1
            if not depth[key]:
                del depth[key]
        return

    handle = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o666)
    depth[key] = 1
    try:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        del depth[key]
        os.close(handle)


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
        # mkstemp creates at 0600, and the rename carries that onto the target,
        # so a permission the user set would be silently narrowed on every save.
        existing = _existing_mode(path)
        if existing is not None:
            with contextlib.suppress(OSError):
                os.chmod(temp_path, existing)
        os.replace(temp_path, path)
        _fsync_directory(path.parent)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def _existing_mode(path: Path) -> int | None:
    """The mode to preserve, or None when there is no file to preserve it from.

    Reading the umask would mean setting it first, and that is process-global:
    a concurrent thread creating a file in that window gets it world-writable.
    A brand-new file keeps mkstemp's private 0600 instead, which is the safe
    direction to be wrong in.
    """
    try:
        return path.stat().st_mode & 0o777
    except FileNotFoundError:
        return None


def _fsync_directory(directory: Path) -> None:
    """Make the rename itself durable, not just the bytes it points at."""
    try:
        handle = os.open(directory, os.O_RDONLY)
    except OSError:
        # Not permitted on every platform; the rename is still atomic.
        return
    try:
        os.fsync(handle)
    except OSError:
        pass
    finally:
        os.close(handle)
