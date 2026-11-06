#!/usr/bin/env python3
"""Exercise real upload, AMQP processing, Catalogue and Streaming through the gateway.

Uses only Python's standard library. Run against a local/disposable stack.
No services are started and no existing songs or infrastructure are deleted.
"""

import argparse
import hashlib
import io
import json
import math
import struct
import sys
import time
import uuid
import wave
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

Json = dict[str, Any]
DURATION_MS = 4000
LYRICS_FIXTURE = b"[00:00.00]Integration line one\n[00:02.00]Integration line two\n"
EXPECTED_LINES = [
    {"time_ms": 0, "text": "Integration line one"},
    {"time_ms": 2000, "text": "Integration line two"},
]


class FlowError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FlowError(message)


class Api:
    def __init__(self, base_url: str, request_timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_timeout = request_timeout
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def request(
        self,
        path: str,
        *,
        data: bytes | None = None,
        content_type: str | None = None,
        expected_status: int = 200,
        allow_missing: bool = False,
    ) -> bytes | None:
        headers = {"Content-Type": content_type} if content_type else {}
        request = Request(self.base_url + path, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=self.request_timeout) as response:
                require(
                    response.status == expected_status,
                    f"{path}: expected HTTP {expected_status}, got {response.status}",
                )
                body = response.read(2_000_001)
                require(len(body) <= 2_000_000, f"{path}: response exceeded fixture limit")
                return body
        except HTTPError as exc:
            if allow_missing and exc.code == 404:
                exc.close()
                return None
            detail = exc.read(1000).decode("utf-8", errors="replace")
            exc.close()
            raise FlowError(f"{path}: HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise FlowError(f"{path}: request failed: {exc}") from exc

    def json(self, path: str, **kwargs: Any) -> Json | None:
        body = self.request(path, **kwargs)
        if body is None:
            return None
        try:
            value = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise FlowError(f"{path}: response was not valid JSON") from exc
        require(isinstance(value, dict), f"{path}: expected a JSON object")
        return value

    def authenticate(self) -> None:
        """Create an isolated integration account and retain its session cookie."""
        credentials = json.dumps(
            {
                "username": f"flow_{uuid.uuid4().hex[:12]}",
                "password": "syncwave-integration-password",
            }
        ).encode()
        self.json(
            "/api/auth/signup",
            data=credentials,
            content_type="application/json",
            expected_status=201,
        )
        self.json(
            "/api/auth/login",
            data=credentials,
            content_type="application/json",
            expected_status=200,
        )


def audio_fixture(
    frequency_hz: float = 440,
    duration_ms: int = DURATION_MS,
    *,
    nonce: str | None = None,
) -> bytes:
    rate = 22050
    pcm = b"".join(
        struct.pack("<h", round(8000 * math.sin(2 * math.pi * frequency_hz * sample / rate)))
        for sample in range(rate * duration_ms // 1000)
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        audio.writeframes(pcm)
    result = bytearray(buffer.getvalue())
    if nonce is not None:
        # Keep the WAV valid and audibly equivalent while making exact bytes
        # unique for integration scenarios that intentionally retain songs.
        data_offset = result.index(b"data") + 8
        marker = hashlib.sha256(nonce.encode()).digest()
        result[data_offset : data_offset + len(marker)] = marker
    return bytes(result)


def multipart(
    title: str, audio: bytes, *, lyrics: bytes = LYRICS_FIXTURE, mood: str | None = None
) -> tuple[bytes, str]:
    boundary = "syncwave-" + uuid.uuid4().hex
    fields = [
        ("title", None, "text/plain", title.encode()),
        ("artist", None, "text/plain", b"Integration test"),
        ("audio", "fixture.wav", "audio/wav", audio),
        (
            "lyrics",
            "fixture.lrc",
            "text/plain; charset=utf-8",
            lyrics,
        ),
    ]
    if mood is not None:
        fields.append(("mood", None, "text/plain", mood.encode()))
    parts = []
    for name, filename, content_type, value in fields:
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        parts.extend(
            [
                f"--{boundary}\r\n{disposition}\r\n".encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                value,
                b"\r\n",
            ]
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def wait_for(api: Api, path: str, key: str, target: str, deadline: float) -> Json:
    last_state = None
    last_response = None
    while time.monotonic() < deadline:
        response = api.json(path, allow_missing=True)
        state = response.get(key) if response else "NOT_FOUND"
        if state != last_state:
            print(f"WAIT {path}: {state}", flush=True)
            last_state = state
        if state in {"FAILED", "PARTIAL"}:
            raise FlowError(f"{path}: processing failed: {json.dumps(response)}")
        if state == target:
            return response
        last_response = response
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise FlowError(f"{path}: timed out waiting for {target}; last response: {last_response}")


def run(
    api: Api,
    timeout: float,
    report: Json,
    *,
    audio: bytes | None = None,
    mood: str | None = None,
    expected_duration_ms: int = DURATION_MS,
) -> None:
    print("Checking required services through the gateway...", flush=True)
    for path in (
        "/api/upload/ready",
        "/api/catalogue/health",
        "/api/lyrics/health",
        "/api/waveform/health",
        "/api/streaming/health",
    ):
        api.request(path)
        print(f"PASS {path}", flush=True)
    api.authenticate()
    print("PASS isolated upload account", flush=True)

    audio = audio_fixture() if audio is None else audio
    title = f"upload-flow-{report['run_id']}"
    body, content_type = multipart(title, audio, mood=mood)
    receipt = api.json(
        "/api/upload/uploads", data=body, content_type=content_type, expected_status=202
    )
    song_id = str(uuid.UUID(receipt["song_id"]))
    event_id = str(uuid.UUID(receipt["event_id"]))
    report.update(song_id=song_id, event_id=event_id, title=title)
    print(f"PASS upload accepted: song_id={song_id} event_id={event_id}", flush=True)
    require(receipt.get("title") == title, "Upload returned the wrong title")
    require(receipt.get("artist") == "Integration test", "Upload returned the wrong artist")
    require(receipt.get("audio_reference") == f"audio/{song_id}.wav", "Wrong audio key")
    require(receipt.get("lyrics_reference") == f"lyrics/{song_id}.lrc", "Wrong lyrics key")
    report.update(
        audio_reference=receipt["audio_reference"],
        lyrics_reference=receipt["lyrics_reference"],
    )
    if mood is not None:
        require(receipt.get("mood") == mood.strip().lower(), "Upload mood was not normalized")
    verify(
        api,
        timeout,
        report,
        audio=audio,
        mood=mood,
        expected_duration_ms=expected_duration_ms,
    )


def verify(
    api: Api,
    timeout: float,
    report: Json,
    *,
    audio: bytes,
    mood: str | None = None,
    expected_duration_ms: int = DURATION_MS,
) -> None:
    """Check an already submitted fixture, including one recovered from a failure."""
    song_id, event_id, title = report["song_id"], report["event_id"], report["title"]

    # All asynchronous stages share one deadline; missing rows are normal while
    # the event works through the independent consumers.
    deadline = time.monotonic() + timeout
    published = wait_for(api, f"/api/upload/uploads/{song_id}", "status", "PUBLISHED", deadline)
    require(published.get("event_id") == event_id, "Event ID changed during delivery")
    require(published.get("published_at") is not None, "Publication timestamp missing")
    require(published.get("publish_attempts", 0) >= 1, "No publish attempt recorded")
    print("PASS RabbitMQ delivery confirmed by upload receipt", flush=True)

    song = wait_for(api, f"/api/catalogue/songs/{song_id}", "processing_status", "READY", deadline)
    require(song.get("song_id") == song_id, "Catalogue returned the wrong song")
    require(song.get("title") == title, "Catalogue title does not match upload")
    require(song.get("artist") == "Integration test", "Catalogue artist does not match upload")
    require(song.get("audio_reference") == report["audio_reference"], "Catalogue S3 key differs")
    if mood is not None:
        require(song.get("mood") == mood.strip().lower(), "Catalogue lost the uploaded mood")
        report["mood"] = song["mood"]
    for field in ("lyrics_status", "waveform_status"):
        require(song.get(field) == "READY", f"Catalogue {field} is not READY")
    duration = song.get("duration_ms")
    require(
        isinstance(duration, int) and abs(duration - expected_duration_ms) <= 100,
        f"Catalogue duration should be about {expected_duration_ms} ms, got {duration}",
    )
    print("PASS Catalogue metadata, processing state and measured duration", flush=True)

    lyrics = wait_for(api, f"/api/lyrics/songs/{song_id}/lyrics", "status", "READY", deadline)
    require(lyrics.get("song_id") == song_id, "Lyrics returned the wrong song")
    require(lyrics.get("lines") == EXPECTED_LINES, "Processed lyric text/timestamps differ")
    require(lyrics.get("line_count") == len(EXPECTED_LINES), "Wrong lyric line count")
    print("PASS lyrics loaded from the uploaded LRC", flush=True)

    waveform = wait_for(
        api, f"/api/waveform/songs/{song_id}/waveform?points=32", "status", "READY", deadline
    )
    require(waveform.get("song_id") == song_id, "Waveform returned the wrong song")
    peaks = waveform.get("peaks")
    require(isinstance(peaks, list) and 0 < len(peaks) <= 32, "Waveform peaks missing/invalid")
    require(waveform.get("points") == len(peaks), "Waveform point count differs")
    require(
        all(
            isinstance(peak, (int, float)) and math.isfinite(peak) and 0 <= peak <= 1
            for peak in peaks
        )
        and any(peak > 0 for peak in peaks),
        "Waveform peaks are invalid or unexpectedly silent",
    )
    require(
        isinstance(waveform.get("duration_ms"), int)
        and abs(waveform["duration_ms"] - expected_duration_ms) <= 100,
        "Waveform duration does not match the generated audio",
    )
    print("PASS waveform generated from uploaded audio", flush=True)

    downloaded = api.request(f"/api/streaming/tracks/{song_id}/audio")
    require(downloaded == audio, "Streaming bytes differ from the uploaded WAV")
    report.update(
        processing_status=song["processing_status"],
        duration_ms=duration,
        audio_bytes=len(audio),
        audio_sha256=hashlib.sha256(audio).hexdigest(),
        publish_attempts=published["publish_attempts"],
    )
    print(f"PASS Streaming downloaded {len(audio):,} matching audio bytes", flush=True)


def positive(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8080")
    parser.add_argument(
        "--timeout", type=positive, default=180, help="Processing timeout in seconds"
    )
    parser.add_argument("--request-timeout", type=positive, default=10)
    parser.add_argument("--report", type=Path, help="Optional JSON evidence file")
    args = parser.parse_args()
    address = urlsplit(args.base_url)
    if address.scheme not in {"http", "https"} or not address.netloc:
        parser.error("--base-url must be an HTTP(S) gateway URL")

    report: Json = {"run_id": uuid.uuid4().hex, "base_url": args.base_url, "result": "FAIL"}
    started = time.monotonic()
    try:
        run(Api(args.base_url, args.request_timeout), args.timeout, report)
    except (FlowError, OSError, ValueError, KeyError, TypeError) as exc:
        report["error"] = str(exc)
        print(f"FAIL {exc}", file=sys.stderr, flush=True)
    else:
        report["result"] = "PASS"
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    print(json.dumps(report, indent=2), flush=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
