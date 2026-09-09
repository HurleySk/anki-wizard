"""Durability and isolation of the writes the ledger depends on.

Atomicity keeps a reader from seeing a torn file; it does nothing about two
writers overwriting each other. Both matter here, because what is being written
is the note ids of cards that really exist in the user's Anki collection.
"""

import threading

from anki_wizard.atomic import locked, write_text_atomic


def test_writes_the_text(tmp_path):
    path = tmp_path / "state.yaml"
    write_text_atomic(path, "hello")
    assert path.read_text() == "hello"


def test_an_existing_file_keeps_its_permissions(tmp_path):
    """mkstemp creates at 0600, and os.replace would carry that onto the target.

    A user who made their state group-readable should not silently lose that on
    the next save.
    """
    path = tmp_path / "state.yaml"
    path.write_text("old")
    path.chmod(0o644)

    write_text_atomic(path, "new")

    assert oct(path.stat().st_mode & 0o777) == "0o644"


def test_no_temp_files_are_left_behind(tmp_path):
    path = tmp_path / "state.yaml"
    write_text_atomic(path, "x")
    assert [p.name for p in tmp_path.iterdir()] == ["state.yaml"]


def test_the_lock_serialises_read_modify_write(tmp_path):
    """The failure this exists to prevent: a lost update.

    Two writers that each load, append, and save will silently discard one
    another's card unless the whole sequence is held under one lock.
    """
    path = tmp_path / "state.txt"
    path.write_text("")
    start = threading.Barrier(2)

    def append(line: str):
        start.wait()
        with locked(path):
            current = path.read_text()
            # Widen the window the race needs; without the lock this loses one.
            threading.Event().wait(0.05)
            write_text_atomic(path, current + line + "\n")

    threads = [threading.Thread(target=append, args=(n,)) for n in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(path.read_text().split()) == ["A", "B"]


def test_the_lock_is_released_when_the_body_raises(tmp_path):
    """A crash mid-edit must not wedge every later write."""
    path = tmp_path / "state.txt"
    path.write_text("")
    try:
        with locked(path):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    with locked(path):
        write_text_atomic(path, "reached")
    assert path.read_text() == "reached"


def test_locking_works_before_the_file_exists(tmp_path):
    """append_cards locks a ledger that the first proposal is about to create."""
    path = tmp_path / "nested" / "state.yaml"
    with locked(path):
        write_text_atomic(path, "first")
    assert path.read_text() == "first"


def test_the_lock_is_reentrant(tmp_path):
    """A nested acquisition must not deadlock.

    flock is per open-file-description, so a second acquisition in the same
    thread blocks against the first and hangs forever with no error -- the
    worst failure available, since nothing reports it.
    """
    path = tmp_path / "state.yaml"
    reached = []

    def nest():
        with locked(path), locked(path):
            reached.append(True)

    worker = threading.Thread(target=nest, daemon=True)
    worker.start()
    worker.join(5)
    assert reached == [True], "nested locked() deadlocked"


def test_a_new_file_is_not_world_writable(tmp_path):
    """Preserving permissions must not mean inventing permissive ones."""
    path = tmp_path / "state.yaml"
    write_text_atomic(path, "x")
    assert not path.stat().st_mode & 0o022
