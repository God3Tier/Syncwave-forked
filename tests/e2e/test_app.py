"""Browser smoke test for the three user journeys against a running stack."""

import argparse
import math
import re
import struct
import uuid
import wave
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = Path(__file__).with_name("artifacts")


def short_audio_fixture(nonce: int) -> Path:
    """Create a deterministic track short enough to exercise instant autoplay."""
    path = ARTIFACTS / "seamless-autoplay.wav"
    sample_rate = 44_100
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        frames = b"".join(
            struct.pack(
                "<h",
                round(8_000 * math.sin(2 * math.pi * 440 * index / sample_rate)),
            )
            for index in range(sample_rate * 3)
        )
        audio.writeframes(frames + struct.pack("<h", nonce))
    return path


def watch_errors(page: Page, errors: list[str]) -> None:
    page.on("pageerror", lambda error: errors.append(f"page: {error}"))

    def record_response(response) -> None:
        expected_guest_session_check = (
            response.status == 401 and "/api/auth/me" in response.url
        )
        expected_upload_poll = (
            response.status == 404
            and "/api/catalogue/songs/" in response.url
            and page.url.endswith("/upload")
        )
        if (
            response.status >= 400
            and not expected_upload_poll
            and not expected_guest_session_check
        ):
            errors.append(f"HTTP {response.status}: {response.url}")

    page.on(
        "response",
        record_response,
    )


def run(base_url: str) -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    run_token = uuid.uuid4().hex
    audio_fixture = short_audio_fixture(int(run_token[:4], 16) - 32_768)
    title = f"browser-e2e-{run_token[:12]}"
    errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        owner_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        owner = owner_context.new_page()
        watch_errors(owner, errors)

        owner.goto(base_url, wait_until="networkidle")
        expect(owner.get_by_role("heading", name="For you right now")).to_be_visible()
        expect(owner.get_by_role("navigation", name="Main").first).to_be_visible()
        expect(
            owner.get_by_role("link", name=re.compile(r"^Open .+")).first
        ).to_be_visible()
        owner.screenshot(path=ARTIFACTS / "discover-desktop.png", full_page=True)
        print("PASS discover desktop")

        owner.goto(f"{base_url}/jam", wait_until="networkidle")
        expect(owner.get_by_role("heading", name="Join a Jam")).to_be_visible()
        owner.get_by_role("button", name="Sign in to host a Jam").click()
        expect(owner).to_have_url(re.compile(r"/signup\?returnTo=.*intent=host"))
        owner.goto(f"{base_url}/upload", wait_until="networkidle")
        expect(owner).to_have_url(re.compile(r"/login\?returnTo=%2Fupload"))
        owner.get_by_role("link", name="Create an account").click()
        owner.screenshot(path=ARTIFACTS / "signup-desktop.png", full_page=True)
        username = f"browser_{uuid.uuid4().hex[:12]}"
        password = "syncwave-browser-password"
        owner.get_by_label("Username").fill(username)
        owner.get_by_label("Password", exact=True).fill(password)
        owner.get_by_label("Confirm password").fill(password)
        owner.get_by_role("button", name="Create account").click()
        expect(owner.get_by_role("status")).to_contain_text("Account created.")
        owner.get_by_label("Password", exact=True).fill(password)
        owner.get_by_role("button", name="Log in").click()
        expect(owner).to_have_url(f"{base_url}/upload")
        print("PASS protected Upload and Jam hosting")

        owner.get_by_label("Title").fill(title)
        owner.get_by_label("Artist").fill("Browser integration")
        files = owner.locator('input[type="file"]')
        files.nth(0).set_input_files(audio_fixture)
        files.nth(1).set_input_files(ROOT / "infrastructure/seed/daisy-bell.lrc")
        owner.get_by_role("button", name="Upload & process").click()
        expect(
            owner.get_by_text(re.compile(rf"Uploaded “{re.escape(title)}”"))
        ).to_be_visible(timeout=20_000)
        expect(owner.get_by_role("link", name="Open song page")).to_be_visible(
            timeout=120_000
        )
        owner.get_by_role("link", name="Open song page").click()
        expect(owner.get_by_role("heading", name=title)).to_be_visible()
        expect(owner.get_by_text("Song READY", exact=True)).to_be_visible()
        print("PASS upload and process")

        owner.get_by_role("link", name="Search", exact=True).click()
        owner.get_by_role("searchbox", name="Search songs or artists").fill(title)
        song_link = owner.locator('a[href^="/songs/"]').filter(has_text=title).first
        expect(song_link).to_be_visible(timeout=20_000)
        song_link.click()
        expect(owner.get_by_role("heading", name=title)).to_be_visible()
        expect(owner.get_by_text("Lyrics READY", exact=True)).to_be_visible()
        expect(owner.get_by_text("Waveform READY", exact=True)).to_be_visible()
        owner.get_by_role("button", name="Play", exact=True).click()
        expect(
            owner.get_by_role("button", name="Pause", exact=True).first
        ).to_be_visible()
        print("PASS discover, search and listen")

        owner.goto(f"{base_url}/jam", wait_until="networkidle")
        owner.get_by_role("button", name="Create Jam").click()
        owner.wait_for_url(re.compile(r"/jam/[0-9a-f-]{36}$"))
        expect(owner.get_by_text("OWNER", exact=True)).to_be_visible()
        jam_code_label = owner.get_by_label(re.compile(r"Jam code \d{8}"))
        expect(jam_code_label).to_be_visible()
        jam_code = jam_code_label.get_attribute("aria-label").rsplit(" ", 1)[-1]
        assert re.fullmatch(r"\d{8}", jam_code)
        expect(owner.get_by_role("button", name="Copy invite link")).to_be_visible()
        print("PASS authenticated Jam hosting")
        jam_url = owner.url
        owner.goto(f"{base_url}/playlists", wait_until="networkidle")
        owner.get_by_role("button", name="New playlist").click()
        owner.get_by_label("Playlist name").fill(f"E2E {title}")
        owner.get_by_role("button", name="Create", exact=True).click()
        expect(owner.get_by_text(f"E2E {title}", exact=True)).to_be_visible()
        print("PASS authenticated playlist creation")
        owner.goto(jam_url, wait_until="networkidle")
        owner.get_by_role("searchbox", name="Search songs to add").fill(title)
        owner.get_by_role("button", name="Add", exact=True).click()
        expect(owner.get_by_text(title, exact=True).first).to_be_visible()

        member_context = browser.new_context(viewport={"width": 390, "height": 844})
        member = member_context.new_page()
        watch_errors(member, errors)
        member.goto(jam_url, wait_until="networkidle")
        expect(member.get_by_text("MEMBER", exact=True)).to_be_visible()
        member.get_by_role("tab", name="People").click()
        expect(member.get_by_text(re.compile(r"Participants \(2\)"))).to_be_visible(
            timeout=20_000
        )
        expect(owner.get_by_text(re.compile(r"Participants \(2\)"))).to_be_visible(
            timeout=20_000
        )
        owner.get_by_role("button", name="Join playback").click()
        member.get_by_role("button", name="Join playback").click()
        owner.get_by_role("button", name="Start", exact=True).click()
        expect(owner.get_by_text("PLAYING", exact=True)).to_be_visible(timeout=30_000)
        expect(member.get_by_text("PLAYING", exact=True)).to_be_visible(timeout=30_000)
        expect(owner.get_by_label("Connected to live playback")).to_have_count(2)
        expect(owner.get_by_label("Audio running, buffered and ready")).to_have_count(2)
        expect(owner.get_by_text(re.compile(r"Shared queue\s*\(6\)"))).to_be_visible(
            timeout=20_000
        )
        expect(owner.get_by_role("heading", name=title, exact=True)).to_have_count(
            0, timeout=30_000
        )
        assert member.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        member.screenshot(path=ARTIFACTS / "jam-mobile.png", full_page=True)
        print("PASS two-browser gapless transition and Top Hits default autoplay")

        member.get_by_role("button", name="Leave").click()
        expect(member).to_have_url(f"{base_url}/jam")
        expect(owner.get_by_text(re.compile(r"Participants \(1\)"))).to_be_visible(
            timeout=20_000
        )
        member.get_by_label("Jam code or invite link").fill(jam_code)
        member.get_by_role("button", name="Join", exact=True).click()
        expect(member).to_have_url(jam_url)
        expect(member.get_by_text("MEMBER", exact=True)).to_be_visible()
        member.get_by_role("button", name="Join playback").click()
        member.get_by_role("tab", name="People").click()
        expect(member.get_by_text(re.compile(r"Participants \(2\)"))).to_be_visible(
            timeout=20_000
        )
        expect(member.get_by_text("PLAYING", exact=True)).to_be_visible(timeout=30_000)
        print("PASS member leaves, rejoins by 8-digit code and catches up")

        member.goto(base_url, wait_until="networkidle")
        expect(member.get_by_role("navigation", name="Main")).to_be_visible()
        assert member.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        member.screenshot(path=ARTIFACTS / "discover-mobile.png", full_page=True)
        print("PASS mobile layout")

        member.set_viewport_size({"width": 768, "height": 1024})
        member.goto(base_url, wait_until="networkidle")
        assert member.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        member.screenshot(path=ARTIFACTS / "discover-tablet.png", full_page=True)
        print("PASS tablet layout")

        owner.get_by_role("button", name="Log out").click()
        owner.goto(f"{base_url}/login", wait_until="networkidle")
        owner.get_by_label("Username").fill(username)
        owner.get_by_label("Password", exact=True).fill(password)
        owner.get_by_role("button", name="Log in").click()
        expect(owner.get_by_title(username)).to_be_visible()
        print("PASS login and logout")

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
