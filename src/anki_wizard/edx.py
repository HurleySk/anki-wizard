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
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from anki_wizard.atomic import write_text_atomic
from anki_wizard.cursor import load_cursor, save_cursor
from anki_wizard.models import Outline, Section
from anki_wizard.outline import save_outline

LOGIN_SCRIPT = "scripts/edx_login.py"
SEQUENCE_API = "/api/courseware/sequence/"
XBLOCK_PATH = "/xblock/"


def parse_course_url(url: str) -> tuple[str, str]:
    """The LMS origin and the sequential block id named by a course URL.

    The learning frontend and the LMS share an origin on the sites this is
    for, so the origin is the API base too. The vertical segment, when
    present, is ignored here; `parse_vertical` reads it for the callers that
    capture a single tab.
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


def parse_vertical(url: str) -> str | None:
    """The vertical block id a course URL names, or None when it names none.

    A sequential is a problem set or a lecture page and the site does not
    distinguish them, so nothing here infers which it is: the tab is read
    only because a caller asked for one tab.
    """
    for segment in urlsplit(url).path.split("/"):
        if "type@vertical" in segment:
            return segment
    return None


def required_vertical(url: str) -> str:
    """The vertical a URL names, refused when it names none.

    Its own function because both the early refusal in `ingest_edx` and the
    selection in `capture_set` make the same demand of the same URL.
    """
    vertical = parse_vertical(url)
    if vertical is None:
        raise ValueError(
            f"one tab was asked for, but {url!r} names none: "
            "expected a block-v1:...+type@vertical+block@<name> segment"
        )
    return vertical


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


class LoginRequired(RuntimeError):
    """The saved session is missing or no longer accepted by the course site.

    Raised before anything is captured, so a login page is never written down
    as a tab. The tool does not retry or prompt: the fix is the headed login
    script, which is the user's to run.
    """

    def __init__(self, url: str, detail: str):
        super().__init__(
            f"{detail}. Sign in once with\n\n"
            f"    uv run python {LOGIN_SCRIPT} '{url}'\n\n"
            "and run the ingest again."
        )


def _sent_to_sign_in(final_url: str, lms: str) -> str | None:
    """Why the final URL of a request looks like the sign-in wall, or None.

    The site sends an unauthenticated browser to its SSO host, so a request
    that ends on another origin is the wall whatever that host calls its
    path; a same-origin `/login` is the older, self-hosted form of it.
    """
    final, home = urlsplit(final_url), urlsplit(lms)
    if final.netloc and final.netloc != home.netloc:
        return f"the course site sent the request to sign in at {final.netloc}"
    if "/login" in final.path:
        return "the course site redirected to its login page"
    return None


def _login_wall(status: int, content_type: str, final_url: str, lms: str) -> str | None:
    """Why a sequence API response looks like the login wall, or None."""
    if status in (401, 403):
        return f"the course site answered {status}"
    redirected = _sent_to_sign_in(final_url, lms)
    if redirected:
        return redirected
    if "json" not in content_type:
        return f"the course site answered with {content_type or 'no content type'} rather than JSON"
    return None


def fetch_units(page, lms: str, sequential: str) -> list[dict]:
    """The tab list, fetched through the page so its cookies and routes apply.

    A navigation rather than a background request on purpose: Playwright's
    request context bypasses route interception, and the tests serve the API
    through routes. The response body is the raw JSON whatever the browser
    draws around it.
    """
    url = sequence_url(lms, sequential)
    response = page.goto(url)
    if response is None:
        raise LoginRequired(url, "the course site did not answer the sequence request")
    wall = _login_wall(response.status, response.headers.get("content-type", ""), response.url, lms)
    if wall:
        raise LoginRequired(url, wall)
    try:
        return units_from_sequence(response.json())
    except ValueError as exc:
        raise LoginRequired(url, str(exc)) from exc


BLOCK_SELECTOR = "div.vert-mod > div.vert"
SHOW_ANSWER_SELECTOR = "button.show"
# The solution edX inserts after Show Answer, in either markup generation:
# the classic `.detailed-solution` div, or content filled into `.solution-span`.
SOLUTION_SELECTOR = ".detailed-solution, .solution-span > *"
SKIPPED_BLOCK_TYPES = frozenset({"video", "discussion"})
SOLUTION_TIMEOUT_MS = 10_000
TYPESET_TIMEOUT_MS = 30_000

# MathJax 2 exposes its queue; a page without MathJax has nothing to wait for.
TYPESET_DONE_JS = """
() => {
  const mj = window.MathJax;
  if (!mj || !mj.Hub || !mj.Hub.queue) return true;
  return mj.Hub.queue.pending === 0 && mj.Hub.queue.running === 0;
}
"""

# One pass over the page's blocks, reporting each one's type, its text with
# every formula's TeX put back in place of the rendered spans, and whether a
# solution is on screen. Done in one evaluate rather than per-block calls so
# the page is read at a single instant. The Python string doubles every
# backslash once, so the JS sees `\\(`, which its literal yields as `\(`.
BLOCK_INFO_JS = """
(selectors) => {
  const [blockSelector, solutionSelector] = selectors;
  const visible = (el) => el.getClientRects().length > 0;
  return Array.from(document.querySelectorAll(blockSelector)).map((vert) => {
    const xblock = vert.querySelector("[data-block-type]");
    const type = xblock ? xblock.getAttribute("data-block-type") : "unknown";
    const solutionShown = Array.from(vert.querySelectorAll(solutionSelector)).some(visible);
    const clone = vert.cloneNode(true);
    clone.querySelectorAll("[hidden]").forEach((el) => el.remove());
    clone.querySelectorAll("script[type^='math/tex']").forEach((script) => {
      const display = (script.getAttribute("type") || "").includes("mode=display");
      const tex = script.textContent.trim();
      const text = display ? "\\\\[" + tex + "\\\\]" : "\\\\(" + tex + "\\\\)";
      script.replaceWith(document.createTextNode(text));
    });
    clone.querySelectorAll(
      ".MathJax, .MathJax_Display, .MathJax_Preview, .MathJax_CHTML, mjx-container, script, style, .sr-only"
    ).forEach((el) => el.remove());
    const text = clone.textContent
      .replace(/[ \\t]+/g, " ")
      .replace(/ *\\n */g, "\\n")
      .replace(/\\n{2,}/g, "\\n")
      .trim();
    return { type, text, solution_shown: solutionShown };
  });
}
"""


def _wait_for_typeset(page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_function(TYPESET_DONE_JS, timeout=TYPESET_TIMEOUT_MS)


def _reveal_solutions(page) -> None:
    """Click every Show Answer and wait for its solution, one problem at a time.

    A button that never yields a solution -- the course hides it, the
    deadline passed -- is left after the timeout; the hint records that no
    solution was shown, so the capture still goes through.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    buttons = page.locator(f"{BLOCK_SELECTOR} {SHOW_ANSWER_SELECTOR}")
    for index in range(buttons.count()):
        button = buttons.nth(index)
        if not button.is_visible() or button.is_disabled():
            continue
        button.click()
        block = button.locator(
            "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' vert ')][1]"
        )
        try:
            block.locator(SOLUTION_SELECTOR).first.wait_for(
                state="visible", timeout=SOLUTION_TIMEOUT_MS
            )
        except PlaywrightTimeout:
            continue


def capture_unit(page, slug: str, unit: dict, first_page: int, paths, response=None) -> dict:
    """Capture one tab, already navigated to in `page`, as pages from `first_page`.

    Returns the manifest entry for the unit. `response` is what `page.goto`
    returned; a failed status means the tab is recorded with an empty range
    and the reason rather than captured, so the outline stays honest about
    the set's shape and the run goes on.
    """
    entry = {"id": unit["id"], "title": unit["title"]}
    if response is not None and response.status >= 400:
        entry["pages"] = [first_page, first_page]
        entry["reason"] = f"unit page answered {response.status}"
        return entry

    _wait_for_typeset(page)
    _reveal_solutions(page)
    blocks = page.evaluate(BLOCK_INFO_JS, [BLOCK_SELECTOR, SOLUTION_SELECTOR])
    verts = page.locator(BLOCK_SELECTOR)

    number = first_page
    for index, block in enumerate(blocks):
        if block["type"] in SKIPPED_BLOCK_TYPES:
            continue
        verts.nth(index).screenshot(path=str(paths.page_image(slug, number)))
        paths.page_text(slug, number).write_text(block_hint(block))
        number += 1

    entry["pages"] = [first_page, number]
    if number == first_page:
        entry["reason"] = "no capturable blocks on this tab"
    return entry


def _result(slug: str, outline: Outline) -> dict:
    # The same shape ingest_source returns, so an agent reads both alike.
    return {
        "slug": slug,
        "pages": outline.pages,
        "structure": outline.structure,
        "sections": [asdict(s) for s in outline.sections],
    }


def selected_units(units: list[dict], url: str, one_tab: bool) -> list[dict]:
    """The tabs to capture: the one the URL names, or all of them.

    A vertical that the sequence does not list is a typo in the pasted URL.
    Refused by name rather than captured as an empty set, which would write a
    section with no pages and read as a tab that held nothing.
    """
    if not one_tab:
        return units
    vertical = required_vertical(url)
    chosen = [unit for unit in units if unit["id"] == vertical]
    if not chosen:
        listed = ", ".join(unit["id"] for unit in units) or "no tabs"
        raise ValueError(f"{vertical} is not a tab of this sequence, which lists {listed}")
    return chosen


def capture_set(context, url: str, slug: str, paths, one_tab: bool = False) -> dict:
    """Capture the set at `url` into `sources/<slug>/`, every tab or just one.

    Tabs already in the manifest are skipped, so a run interrupted partway
    resumes at the first tab not yet recorded, and a second `one_tab` run on
    the same slug appends the tab it names. After each tab the manifest and
    outline are rewritten, so a crash leaves a consistent source.
    """
    lms, sequential = parse_course_url(url)
    manifest_path = paths.source_manifest(slug)
    manifest = existing_manifest(manifest_path, sequential)

    page = context.new_page()
    units = selected_units(fetch_units(page, lms, sequential), url, one_tab)

    if manifest is None:
        manifest = new_manifest(url, lms, sequential)
    paths.ensure_source_dirs(slug)
    done = {entry["id"] for entry in manifest["units"]}

    for unit in units:
        if unit["id"] in done:
            continue
        first_page = manifest["units"][-1]["pages"][1] if manifest["units"] else 1
        response = page.goto(unit_url(lms, unit["id"]))
        # The tab list can be public while the pages are not, so this is the
        # first real check of the session as well as the mid-run one.
        # Everything recorded so far stays, and the next run after a fresh
        # login picks up here.
        wall = _sent_to_sign_in(response.url, lms) if response is not None else None
        if wall:
            raise LoginRequired(url, wall)
        entry = capture_unit(page, slug, unit, first_page, paths, response=response)
        manifest["units"].append(entry)
        save_manifest(manifest_path, manifest)
        save_outline(paths.outline_file(slug), outline_from_manifest(slug, manifest))

    outline = outline_from_manifest(slug, manifest)
    save_outline(paths.outline_file(slug), outline)
    save_manifest(manifest_path, manifest)
    cursor_path = paths.cursor_file(slug)
    if not cursor_path.exists():
        save_cursor(cursor_path, load_cursor(cursor_path))
    return _result(slug, outline)


class PlaywrightMissing(RuntimeError):
    """Playwright or its browser is not installed. Named before anything is written."""


SETUP_HINT = (
    "Install the web extra and its browser:\n\n"
    "    uv sync --extra web\n"
    "    uv run playwright install chromium\n"
)

VIEWPORT = {"width": 1100, "height": 900}


def _playwright():
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as exc:
        raise PlaywrightMissing(f"playwright is not installed. {SETUP_HINT}") from exc
    return sync_playwright, Error


def ingest_edx(url: str, slug: str, paths, headless: bool = True, one_tab: bool = False) -> dict:
    """Capture the sequence at `url` into `sources/<slug>/`.

    Captures every tab by default, which is what a problem set wants. With
    `one_tab`, captures only the vertical the URL names and appends it to the
    slug, which is what a lecture page wants: its tabs are worth carding one
    at a time, and they share a slug so one lecture's cards group together.

    Everything that can be refused is refused before the browser starts: a
    URL that names no problem set, a URL naming no tab when one was asked
    for, a slug holding a different set, a missing session. The browser
    itself opens headless on the saved session; the headed login is
    `scripts/edx_login.py`, run by the user, never here. Whether the named
    tab is one this sequence lists needs the tab list, so that is checked
    once the browser has it.
    """
    _, sequential = parse_course_url(url)
    if one_tab:
        required_vertical(url)
    existing_manifest(paths.source_manifest(slug), sequential)
    state = paths.edx_auth_state()
    if not state.exists():
        raise LoginRequired(url, f"no saved session at {state}")

    sync_playwright, Error = _playwright()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=headless)
        except Error as exc:
            raise PlaywrightMissing(f"chromium could not start: {exc}. {SETUP_HINT}") from exc
        try:
            # Scale 2 so small subscripts survive; a fixed width so a block's
            # line breaks match what the reader saw on the site.
            context = browser.new_context(
                storage_state=str(state), viewport=VIEWPORT, device_scale_factor=2
            )
            return capture_set(context, url, slug, paths, one_tab=one_tab)
        finally:
            browser.close()


LOGIN_TIMEOUT_S = 600
LOGIN_POLL_S = 2


def session_ready(status: int, final_url: str, lms: str) -> bool:
    """Whether a unit page's answer shows the browser is signed in.

    Judged on a unit page, not the sequence API: on the sites this is for
    the API lists a set's tabs to anyone, and a poll on it would call the
    session ready before the user had typed a password.
    """
    return status == 200 and _sent_to_sign_in(final_url, lms) is None


def login(url: str, state_path: Path, timeout_s: float = LOGIN_TIMEOUT_S) -> None:
    """Open a headed browser at `url`, wait for the user to sign in, save the session.

    Polls the set's first unit page through the context's request client
    rather than by navigating, so the tab the user is typing into is never
    touched. The request client shares the context's cookies, which is all a
    poll needs.
    """
    import time

    lms, sequential = parse_course_url(url)
    sync_playwright, Error = _playwright()
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=False)
        except Error as exc:
            raise PlaywrightMissing(f"chromium could not start: {exc}. {SETUP_HINT}") from exc
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(url)
            deadline = time.monotonic() + timeout_s
            probe_url = None
            while time.monotonic() < deadline:
                if probe_url is None:
                    probe_url = _first_unit_url(context, lms, sequential)
                if probe_url is not None:
                    answer = context.request.get(probe_url)
                    if session_ready(answer.status, answer.url, lms):
                        state_path.parent.mkdir(parents=True, exist_ok=True)
                        context.storage_state(path=str(state_path))
                        return
                time.sleep(LOGIN_POLL_S)
            raise LoginRequired(url, f"no sign-in seen within {int(timeout_s)} seconds")
        finally:
            browser.close()


def _first_unit_url(context, lms: str, sequential: str) -> str | None:
    """The page to probe for a signed-in session, or None until the API answers.

    The tab list itself may sit behind the wall on some sites, so a refusal
    here is not an error, just not yet.
    """
    answer = context.request.get(sequence_url(lms, sequential))
    if _login_wall(answer.status, answer.headers.get("content-type", ""), answer.url, lms):
        return None
    try:
        units = units_from_sequence(answer.json())
    except ValueError:
        return None
    return unit_url(lms, units[0]["id"]) if units else None
