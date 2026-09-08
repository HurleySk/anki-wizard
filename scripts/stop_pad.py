"""Stop the pad server.

Usage:
    uv run python scripts/stop_pad.py

The server also stops itself once nothing has fetched the pad for
`pad_server_timeout_minutes` (30 by default), so this is for stopping one early
rather than routine cleanup.
"""

import sys
from pathlib import Path

from anki_wizard import viewer
from anki_wizard.paths import Paths


def main() -> int:
    pad = Paths(root=Path(".")).pad_dir()
    if not pad.exists():
        print("no pad directory; nothing to stop")
        return 0
    if viewer.stop(pad):
        print(f"stopped the pad server for {pad}")
    else:
        print("no pad server was running")
    return 0


if __name__ == "__main__":
    sys.exit(main())
