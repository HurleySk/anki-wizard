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


def render_pages(pdf: Path, out_dir: Path, dpi: int = 150) -> list[Path]:
    """Render every page to out_dir/page-NNN.png.

    Pages already rendered are skipped, which is what makes ingest resumable
    after an interrupted run.
    """
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    out_dir.mkdir(parents=True, exist_ok=True)
    total = page_count(pdf)
    written: list[Path] = []
    for page in range(1, total + 1):
        target = out_dir / f"page-{page:03d}.png"
        if not target.exists():
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
                    str(target.with_suffix("")),
                ]
            )
        written.append(target)
    return written
