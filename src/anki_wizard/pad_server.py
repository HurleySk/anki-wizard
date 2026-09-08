"""The detached pad server process.

Run as `python -m anki_wizard.pad_server <root>`. It writes a pidfile the
starting process polls for, then serves until left idle.
"""

import argparse
import json
import os
import signal
import sys
from pathlib import Path

from anki_wizard.viewer import (
    DEFAULT_HOST,
    DEFAULT_IDLE_TIMEOUT_MINUTES,
    DEFAULT_PORT,
    PadServer,
    pidfile,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--idle-timeout-minutes", type=float, default=DEFAULT_IDLE_TIMEOUT_MINUTES
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 2

    timeout = args.idle_timeout_minutes
    server = PadServer(
        root, args.host, args.port, idle_timeout=timeout * 60 if timeout > 0 else None
    )

    path = pidfile(root)
    path.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "host": server.host,
                "port": server.port,
                "root": str(root),
                "idle_timeout_minutes": timeout,
            }
        )
    )

    def stop_serving(signum, frame):
        server.request_stop()

    signal.signal(signal.SIGTERM, stop_serving)
    signal.signal(signal.SIGINT, stop_serving)

    try:
        server.serve_until_idle()
    finally:
        server.server_close()
        path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
