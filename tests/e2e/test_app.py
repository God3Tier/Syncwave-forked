"""Browser smoke test for the three user journeys against a running stack."""

import argparse
import re
import time
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(__file__).with_name("artifacts")


def watch_errors(page: Page, errors: list[str]) -> None:
    page.on("pageerror", lambda error: errors.append(f"page: {error}"))

    def record_response(response) -> None:
        expected_upload_poll = (
            response.status == 404
            and "/api/catalogue/songs/" in response.url
            and page.url.endswith("/upload")
        )
        if response.status >= 400 and not expected_upload_poll:
            errors.append(f"HTTP {response.status}: {response.url}")

    page.on(
        "response",
        record_response,
    )


def run(base_url: str) -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    title = f"browser-e2e-{int(time.time())}"
    errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        owner_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        owner = owner_context.new_page()
        watch_errors(owner, errors)

        owner.goto(base_url, wait_until="networkidle")
        expect(owner.get_by_role("heading", name="For you right now")).to_be_visible()
        expect(owner.get_by_role("navigation", name="Main").first).to_be_visible()
        owner.screenshot(path=ARTIFACTS / "discover-desktop.png", full_page=True)
        print("PASS discover desktop")

        owner.get_by_role("link", name="Search", exact=True).click()
        owner.get_by_role("searchbox", name="Search songs or artists").fill("Integration check")
        expect(owner.get_by_text(re.compile(r"result.*Integration check", re.I))).to_be_visible()
        owner.locator('a[href^="/songs/"]').filter(has_text="Integration check").first.click()
        expect(owner.get_by_role("heading", name="Integration check")).to_be_visible()
        expect(owner.get_by_text("Lyrics READY", exact=True)).to_be_visible()
        expect(owner.get_by_text("Waveform READY", exact=True)).to_be_visible()
        owner.get_by_role("button", name="Play", exact=True).click()
        expect(owner.get_by_role("button", name="Pause", exact=True).first).to_be_visible()
        print("PASS discover, search and listen")

        owner.goto(f"{base_url}/upload", wait_until="networkidle")
        owner.get_by_label("Title").fill(title)
        owner.get_by_label("Artist").fill("Browser integration")
        files = owner.locator('input[type="file"]')
        files.nth(0).set_input_files(ROOT / "services/upload/samples/upload-test.mp3")
        files.nth(1).set_input_files(ROOT / "infrastructure/seed/daisy-bell.lrc")
        owner.get_by_role("button", name="Upload & process").click()
        expect(owner.get_by_text(re.compile(rf'Uploaded “{re.escape(title)}”'))).to_be_visible(timeout=20_000)
        expect(owner.get_by_role("link", name="Open song page")).to_be_visible(timeout=120_000)
        owner.get_by_role("link", name="Open song page").click()
        expect(owner.get_by_role("heading", name=title)).to_be_visible()
        expect(owner.get_by_text("Song READY", exact=True)).to_be_visible()
        print("PASS upload and process")

        owner.goto(f"{base_url}/jam", wait_until="networkidle")
        owner.get_by_role("button", name="Create Jam").click()
        owner.wait_for_url(re.compile(r"/jam/[0-9a-f-]{36}$"))
        expect(owner.get_by_text("OWNER", exact=True)).to_be_visible()
        jam_url = owner.url

        member_context = browser.new_context(viewport={"width": 390, "height": 844})
        member = member_context.new_page()
        watch_errors(member, errors)
        member.goto(f"{jam_url}?user=new", wait_until="networkidle")
        expect(member.get_by_text("MEMBER", exact=True)).to_be_visible()
        expect(member.get_by_text(re.compile(r"Participants \(2\)"))).to_be_visible(timeout=20_000)
        expect(owner.get_by_text(re.compile(r"Participants \(2\)"))).to_be_visible(timeout=20_000)
        assert member.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        member.screenshot(path=ARTIFACTS / "jam-mobile.png", full_page=True)
        print("PASS two-browser Jam join")

        member.goto(base_url, wait_until="networkidle")
        expect(member.get_by_role("navigation", name="Main")).to_be_visible()
        assert member.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        member.screenshot(path=ARTIFACTS / "discover-mobile.png", full_page=True)
        print("PASS mobile layout")

        member_context.close()
        owner_context.close()
        browser.close()

    if errors:
        raise AssertionError("Browser errors:\n" + "\n".join(errors))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080")
    args = parser.parse_args()
    run(args.base_url.rstrip("/"))
