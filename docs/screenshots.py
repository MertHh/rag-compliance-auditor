"""Takes the README screenshots from a running UI and API, so they can be retaken the same way.

Needs the demo documents uploaded and audited (see docs/demo.md), the API on :8000 and the UI
on :8501, and Playwright:  pip install -e ".[docs]" && python -m playwright install chromium

Run: python docs/screenshots.py                  every shot into docs/images/
     python docs/screenshots.py --only trace     shots whose name contains "trace"

Each page is laid out at 1280x720 and rendered at 2x, so the files are 2560x1440 and the text
stays sharp when GitHub scales the image down to the README width.
"""

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

OUT = Path(__file__).parent / "images"
VIEWPORT = {"width": 1280, "height": 720}
SCALE = 2
# Streamlit chrome that says nothing about the project: sidebar, toolbar, running indicator.
HIDE_CHROME = """
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stHeader"],
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"]
{ display: none !important; }
[data-testid="stMainBlockContainer"] { padding: 1.25rem 2rem 1rem !important; max-width: none !important; }
"""


@dataclass(frozen=True)
class Shot:
    name: str
    page: str                      # Streamlit page path: audit, trace, search
    document: str                  # filename of the uploaded PDF
    playbook: str | None = None    # opens the newest audit of this playbook on the document
    params: dict = field(default_factory=dict)
    scroll_to: str | None = None   # text that should sit at the top of the shot
    pdf: bool = True               # wait for the PDF viewer to draw


PAPER = "plos-one-data-availability.pdf"
SHOTS = [
    Shot("finding", "audit", PAPER, "research_paper", {"rule": "code_availability"}, scroll_to="Finding"),
    Shot("audit", "audit", PAPER, "research_paper", {"rule": "preregistration"}, scroll_to="Risk score",
         pdf=False),
    Shot("search", "search", PAPER, params={"q": "which repositories did authors use most"},
         scroll_to="Query"),
    Shot("trace", "trace", PAPER, "research_paper",
         {"rules": "preregistration,uncertainty_reported,funder_influence,code_availability,limitations"},
         scroll_to="Audit", pdf=False),
]


def resolve(api: httpx.Client, shot: Shot) -> dict:
    """The URL parameters for a shot: document and audit ids looked up through the API."""
    docs = [d for d in api.get("/documents").raise_for_status().json() if d["filename"] == shot.document]
    if not docs:
        raise SystemExit(f"{shot.name}: {shot.document} is not uploaded")
    params = {"document": docs[0]["document_id"], **shot.params}
    if shot.playbook:
        audits = api.get("/audits", params={"document_id": params["document"]}).raise_for_status().json()
        runs = sorted((a for a in audits if a["playbook"] == shot.playbook),
                      key=lambda a: a["created_at"], reverse=True)
        if not runs:
            raise SystemExit(f"{shot.name}: no {shot.playbook} audit of {shot.document}")
        params["audit"] = runs[0]["audit_id"]
    return params


def take(page: Page, ui: str, shot: Shot, params: dict) -> Path:
    page.goto(f"{ui}/{shot.page}?" + str(httpx.QueryParams(params)))
    page.wait_for_selector('[data-testid="stApp"][data-test-script-state="notRunning"]', timeout=60_000)
    page.add_style_tag(content=HIDE_CHROME)
    if shot.pdf:
        page.frame_locator("iframe").first.locator("canvas").first.wait_for(timeout=60_000)
    page.wait_for_timeout(2500)  # charts animate in; the PDF viewer scrolls to its first box, page too
    if shot.scroll_to:
        page.get_by_text(shot.scroll_to, exact=True).first.evaluate("e => e.scrollIntoView({block: 'start'})")
    page.evaluate("document.activeElement && document.activeElement.blur()")
    page.wait_for_timeout(500)
    path = OUT / f"{shot.name}.png"
    page.screenshot(path=path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="screenshots")
    parser.add_argument("--ui", default="http://localhost:8501")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--only", help="take only the shots whose name contains this text")
    parser.add_argument("--theme", choices=["light", "dark"], default="light")
    args = parser.parse_args(argv)
    shots = [s for s in SHOTS if not args.only or args.only in s.name]
    if not shots:
        print(f"no shot matches {args.only!r}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=args.api, timeout=30) as api, sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE,
                                      color_scheme=args.theme)
        for shot in shots:
            page = context.new_page()  # a fresh session, so one shot's choices do not leak into the next
            print(take(page, args.ui, shot, resolve(api, shot)))
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
