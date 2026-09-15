"""Captures an Open edX problem set as an ordinary source.

A problem set on the course site is a *sequential*; its tabs are *verticals*
(units); each unit holds *xblocks* in order. The learning frontend lists a
sequential's units through the sequence API and renders each unit at the
LMS's xblock endpoint, and that is what this module drives: the tab list from
the API, each tab opened directly, one image per block. The result is written
in the same layout `ingest_source` produces, so every downstream tool reads it
unchanged.

Only the functions that touch a browser need Playwright, and they import it
lazily, so the rest of the package works without it installed.
"""

import json
from pathlib import Path
from urllib.parse import urlsplit

from anki_wizard.atomic import write_text_atomic
from anki_wizard.models import Outline, Section

LOGIN_SCRIPT = "scripts/edx_login.py"
SEQUENCE_API = "/api/courseware/sequence/"
XBLOCK_PATH = "/xblock/"


def parse_course_url(url: str) -> tuple[str, str]:
    """The LMS origin and the sequential block id named by a course URL.

    The learning frontend and the LMS share an origin on the sites this is
    for, so the origin is the API base too. The vertical segment, when
    present, is ignored: one run captures the whole sequential.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"expected an http(s) course URL, got {url!r}")
    for segment in parts.path.split("/"):
        if "type@sequential" in segment:
            return f"{parts.scheme}://{parts.netloc}", segment
    raise ValueError(
        f"no problem set in {url!r}: expected a path segment like "
        "block-v1:<org>+<course>+<run>+type@sequential+block@<name>"
    )


def sequence_url(lms: str, sequential: str) -> str:
    return f"{lms}{SEQUENCE_API}{sequential}"


def unit_url(lms: str, unit_id: str) -> str:
    return f"{lms}{XBLOCK_PATH}{unit_id}"


def units_from_sequence(payload: dict) -> list[dict]:
    """The ordered tabs of a sequential, as `{"id", "title"}` pairs.

    The sequence API answers with `items`, one per unit, each carrying its
    block id and a `page_title`. A response without `items` is not a
    sequence -- an error body, or a login page that parsed as JSON -- and is
    refused rather than read as an empty set.
    """
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"sequence response has no items: {payload!r}")
    units = []
    for item in items:
        unit_id = item["id"]
        title = (item.get("page_title") or "").strip() or unit_id.rsplit("@", 1)[-1]
        units.append({"id": unit_id, "title": title})
    return units


def new_manifest(url: str, lms: str, sequential: str) -> dict:
    """The manifest for a slug that has captured nothing yet.

    `units` fills in one entry per tab as each is captured, in the order the
    sequence API lists them; an entry holds the unit id, its title, and the
    `[start, end)` page range its blocks occupy, plus a `reason` when the
    range is empty because the tab could not be read.
    """
    return {"url": url, "lms": lms, "sequential": sequential, "units": []}


def save_manifest(path: Path, manifest: dict) -> None:
    # Atomic like the outline: a truncated manifest would make the next run
    # recapture from the start with the page numbers already handed out.
    write_text_atomic(path, json.dumps(manifest, indent=2))


def existing_manifest(path: Path, sequential: str) -> dict | None:
    """The slug's manifest, or None when the slug is new.

    One slug is one problem set. A manifest naming a different sequential
    means the slug is taken, and adding a second set's blocks after the first
    would give the outline pages from two sources under one name.
    """
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text())
        held = manifest["sequential"]
        manifest["units"]
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"{path} is not a readable source manifest: {exc}") from exc
    if held != sequential:
        raise ValueError(f"{path} already holds {held}; use a different slug for {sequential}")
    return manifest


def outline_from_manifest(slug: str, manifest: dict) -> Outline:
    """One section per captured tab, numbered in tab order."""
    units = manifest["units"]
    sections = [
        Section(id=str(n), title=unit["title"], pages=list(unit["pages"]))
        for n, unit in enumerate(units, start=1)
    ]
    pages = units[-1]["pages"][1] - 1 if units else 0
    return Outline(slug=slug, pages=pages, structure="units", sections=sections)


NO_SOLUTION_LINE = "(no solution was shown for this problem)"


def block_hint(block: dict) -> str:
    """The lossy text hint written beside a block's image.

    `block` is what the page reports for one xblock: its type, its rendered
    text with every formula's TeX source substituted back in, and whether a
    solution is visible. The last matters to the agent: a problem captured
    without its solution has no back to read off the image.
    """
    lines = [f"[{block['type']} block]", block["text"].strip()]
    if block["type"] == "problem" and not block["solution_shown"]:
        lines.append(NO_SOLUTION_LINE)
    return "\n".join(lines) + "\n"
