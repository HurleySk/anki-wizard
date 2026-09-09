"""poppler subprocess wrappers.

Kept as a thin I/O leaf so that outline and ingest logic can be tested without
shelling out. Requires poppler on PATH (pdftoppm, pdftotext, pdfinfo).
"""

import subprocess
from pathlib import Path


class PopplerError(RuntimeError):
    """A poppler command failed."""


def _run(args: list[str]) -> str:
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, check=True, encoding="utf-8"
        )
    except FileNotFoundError as exc:
        raise PopplerError(
            f"{args[0]} not found. Install poppler (brew install poppler)."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise PopplerError(f"{args[0]} failed: {exc.stderr.strip()}") from exc
    return result.stdout


def page_count(pdf: Path) -> int:
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    for line in _run(["pdfinfo", str(pdf)]).splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1].strip())
    raise PopplerError(f"could not determine page count for {pdf}")


def extract_text(pdf: Path, page: int) -> str:
    """Extract the text layer for a single page.

    Returns an empty string for pages with no text layer, which is the normal
    case for scanned documents. The text layer is a hint only: it mangles
    LaTeX list markers and displayed math, so it must never be the sole basis
    for a card's mathematical content.
    """
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    return _run(["pdftotext", "-f", str(page), "-l", str(page), str(pdf), "-"])


def render_page(pdf: Path, page: int, target: Path, dpi: int = 150) -> Path:
    """Render one page to `target`, which the caller names.

    Already-rendered pages are skipped, which is what makes ingest resumable
    after an interrupted run. The target is passed in rather than derived here
    so this module stays free of the state layout, which paths.py owns.
    """
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "pdftoppm",
            "-png",
            "-r",
            str(dpi),
            "-f",
            str(page),
            "-l",
            str(page),
            "-singlefile",
            str(pdf),
            # pdftoppm appends the extension itself, so it wants the stem.
            str(target.with_suffix("")),
        ]
    )
    return target
