"""Generates the PDF fixtures on demand.

The fixtures are build artifacts rather than committed binaries, so the
repository stays text-only. Generating them here means a fresh clone can run
`pytest` straight away instead of failing until a separate command is found.
"""

import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
GENERATOR = FIXTURES / "make_fixtures.py"
EXPECTED = ("outlined.pdf", "slides.pdf", "unstructured.pdf", "scanned.pdf")


def pytest_configure(config):
    if all((FIXTURES / name).exists() for name in EXPECTED):
        return
    subprocess.run([sys.executable, str(GENERATOR)], check=True)
