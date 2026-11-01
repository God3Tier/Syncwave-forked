#!/usr/bin/env python3
"""Upload the demo songs (songs.txt) through the Upload API of any stack.

The local stack seeds itself (seed.sh). Use this one for a stack without the
`seed` service, such as the AWS deployment (infrastructure/aws/RUNBOOK.md):

    python infrastructure/seed/upload-songs.py --base-url http://<alb dns name>

A song whose title and artist are already in the Catalogue is skipped, so it
is safe to run again. It then waits until every uploaded song is processed.
Uses only Python's standard library.
"""

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

SEED_DIR = Path(__file__).resolve().parent


def call(
    base_url: str, path: str, data: bytes | None = None, content_type: str | None = None
) -> Any:
    headers = {"Content-Type": content_type} if content_type else {}
    try:
        with urlopen(Request(base_url + path, data=data, headers=headers), timeout=120) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read(500).decode("utf-8", errors="replace")
        raise SystemExit(f"{path}: HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise SystemExit(f"{path}: request failed: {exc}") from exc


def read_songs() -> list[dict[str, str]]:
    songs = []
    for line in (SEED_DIR / "songs.txt").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            audio, lyrics, title, artist, mood, _song_id, _event_id = line.split("|")
            songs.append(
                {"audio": audio, "lyrics": lyrics, "title": title, "artist": artist, "mood": mood}
            )
    return songs


def catalogue_songs(base_url: str) -> set[tuple[str, str]]:
    found, cursor = set(), None
    while True:
        page = call(
            base_url,
            "/api/catalogue/songs?limit=100" + (f"&cursor={quote(cursor)}" if cursor else ""),
        )
        found.update((item["title"], item["artist"]) for item in page["items"])
        cursor = page.get("next_cursor")
        if not cursor:
            return found


def multipart(song: dict[str, str]) -> tuple[bytes, str]:
    boundary = "syncwave-" + uuid.uuid4().hex
    fields = [
        ("title", None, "text/plain", song["title"].encode()),
        ("artist", None, "text/plain", song["artist"].encode()),
    ]
    if song["mood"]:
        fields.append(("mood", None, "text/plain", song["mood"].encode()))
    fields.append(("audio", song["audio"], "audio/mpeg", (SEED_DIR / song["audio"]).read_bytes()))
    if song["lyrics"]:
        fields.append(
            (
                "lyrics",
                song["lyrics"],
                "text/plain; charset=utf-8",
                (SEED_DIR / song["lyrics"]).read_bytes(),
            )
        )
    parts = []
    for name, filename, content_type, value in fields:
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        parts += [
            f"--{boundary}\r\n{disposition}\r\nContent-Type: {content_type}\r\n\r\n".encode(),
            value,
            b"\r\n",
        ]
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base-url", required=True, help="the gateway or ALB, e.g. http://localhost:8080"
    )
    parser.add_argument("--timeout", type=float, default=600, help="seconds to wait for processing")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    existing = catalogue_songs(base_url)
    uploaded = {}
    for song in read_songs():
        if (song["title"], song["artist"]) in existing:
            print(f"SKIP {song['title']}: already in the catalogue", flush=True)
            continue
        body, content_type = multipart(song)
        receipt = call(base_url, "/api/upload/uploads", body, content_type)
        uploaded[receipt["song_id"]] = song["title"]
        print(
            f"UPLOADED {song['title']} ({song['mood'] or 'no mood'}): song_id={receipt['song_id']}",
            flush=True,
        )

    deadline = time.monotonic() + args.timeout
    pending = dict(uploaded)
    failed = []
    while pending and time.monotonic() < deadline:
        time.sleep(3)
        for song_id, title in list(pending.items()):
            try:
                status = call(base_url, f"/api/catalogue/songs/{song_id}")["processing_status"]
            except SystemExit:
                continue  # not in the Catalogue yet
            if status in {"READY", "PARTIAL", "FAILED"}:
                print(f"{status} {title}", flush=True)
                del pending[song_id]
                if status == "FAILED":
                    failed.append(title)
    for title in pending.values():
        print(f"TIMEOUT {title}: still processing after {args.timeout:.0f}s", flush=True)
    return 1 if failed or pending else 0


if __name__ == "__main__":
    sys.exit(main())
