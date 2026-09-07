"""End-to-end check against a real PDF, without touching Anki.

Usage: uv run python scripts/smoke.py <path-to.pdf> [slug]
"""

import sys
import tempfile
from pathlib import Path

from anki_wizard.paths import Paths
from anki_wizard.tools import get_progress, ingest_source, propose_cards, read_section


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: smoke.py <path-to.pdf> [slug]")
    pdf = Path(sys.argv[1]).expanduser()
    if not pdf.exists():
        sys.exit(f"no such file: {pdf}")
    slug = sys.argv[2] if len(sys.argv) > 2 else pdf.stem[:40]

    with tempfile.TemporaryDirectory() as tmp:
        paths = Paths(root=Path(tmp))

        print(f"ingesting {pdf.name} ...")
        ingested = ingest_source(pdf, slug=slug, paths=paths, dpi=100)
        print(f"  pages:     {ingested['pages']}")
        print(f"  structure: {ingested['structure']}")
        print(f"  sections:  {len(ingested['sections'])}")
        for section in ingested["sections"][:5]:
            print(f"    {section['id']}: {section['title']}")

        progress = get_progress(slug, paths=paths)
        print(f"next up: {progress['next']['id']} - {progress['next']['title']}")

        section = read_section(slug, None, paths=paths)
        print(f"read {len(section['pages'])} page(s); first image:")
        print(f"  {section['pages'][0]['image']}")

        propose_cards(
            slug,
            [{"front": "smoke test front", "back": "smoke test back"}],
            section_id=section["section"]["id"],
            paths=paths,
        )
        print("proposed 1 card; ledger at", paths.ledger_file(slug))
        print("\nOK")


if __name__ == "__main__":
    main()
