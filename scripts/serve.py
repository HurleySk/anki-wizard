"""Start the pad server and print the home page's URL.

Usage:
    uv run python scripts/serve.py

For reading kept notes, cheat sheets, and problem sets in a browser with no
agent session open. The server stops itself once nothing has fetched a page
for `pad_server_timeout_minutes` (30 by default); browsing keeps it alive,
and scripts/stop_pad.py stops it early.
"""

import sys
from pathlib import Path

from anki_wizard.config import load_config
from anki_wizard.paths import Paths
from anki_wizard.tools import open_home


def main() -> int:
    paths = Paths(root=Path("."))
    config = load_config(paths.config_file())
    # The vscode viewer is the one that returns a URL without opening
    # anything, which is what a script that prints the URL wants.
    result = open_home(
        paths,
        viewer="vscode",
        server_timeout_minutes=config.pad_server_timeout_minutes,
    )
    print(result["url"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
