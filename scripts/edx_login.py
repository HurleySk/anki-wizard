"""Sign in to the course site once, and save the session for ingest_edx.

Usage:
    uv run python scripts/edx_login.py <course-url>

Opens a browser window at the URL. Sign in there; the script notices when the
site starts answering the problem set's API, saves the session under
sources/.auth/, and closes the window. ingest_edx reuses that session
headlessly until the site stops accepting it, at which point it says to run
this again.
"""

import sys
from pathlib import Path

from anki_wizard.edx import login
from anki_wizard.paths import Paths


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    state = Paths(root=Path(".")).edx_auth_state()
    login(argv[1], state)
    print(f"session saved to {state}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
