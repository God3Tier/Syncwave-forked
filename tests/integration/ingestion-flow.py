#!/usr/bin/env python3
"""Item 2: upload, discovery, duplicate delivery, mood ranking and recovery.

Run inside Upload with upload-flow.py alongside, against a disposable stack
using ingestion.compose.yaml. The script never stops services or drains a DLQ.
"""

import argparse
import asyncio
import base64
import importlib.util
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

Json = dict[str, Any]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def passed(report: Json, label: str) -> None:
    report["checks"].append(label)
    print(f"PASS {label}", flush=True)


def load_upload_flow():
    path = Path(__file__).with_name("upload-flow.py")
    spec = importlib.util.spec_from_file_location("ingestion_upload_helpers", path)
    require(spec is not None and spec.loader is not None, "Cannot load sibling upload-flow.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def poll(check: Callable, seconds: float, label: str):
    """HTTP/management operations run off the AMQP event loop."""
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        done, last = await asyncio.to_thread(check)
        if done:
            return last
        await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
    raise RuntimeError(f"Timed out: {label}; last response: {last}")


class Observer:
    """Read only our exclusive copies; never consume from service queues."""

    def __init__(self, queue) -> None:
        self.queue = queue
        self.saved = []

    async def event(self, event_type: str, song_id: str, seconds: float):
        def matches(message) -> bool:
            event = json.loads(message.body)
            return event.get("event_type") == event_type and event.get("song_id") == song_id

        for index, message in enumerate(self.saved):
            if matches(message):
                return self.saved.pop(index)
        async with asyncio.timeout(seconds):
            while True:
                message = await self.queue.get(fail=False, timeout=5)
                if message is None:
                    await asyncio.sleep(0.2)
                    continue
                await message.ack()
                if matches(message):
                    return message
                self.saved.append(message)


class QueueMetrics:
    def __init__(self, request_seconds: float) -> None:
        host = os.getenv("AMQP_HOST", "rabbitmq")
        base = os.getenv("RABBITMQ_MANAGEMENT_URL", f"http://{host}:15672")
        vhost = quote(os.getenv("AMQP_VHOST", "/"), safe="")
        self.url = f"{base.rstrip('/')}/api/queues/{vhost}/search.song-ready"
        credentials = (
            f"{os.getenv('AMQP_USER', 'syncwave')}:{os.getenv('AMQP_PASSWORD', 'syncwave')}"
        )
        self.auth = "Basic " + base64.b64encode(credentials.encode()).decode()
        self.request_seconds = request_seconds

    def snapshot(self) -> Json:
        request = Request(self.url, headers={"Authorization": self.auth})
        with urlopen(request, timeout=self.request_seconds) as response:
            data = json.loads(response.read(1_000_001))
        stats = data.get("message_stats", {})
        return {
            "statistics_ready": (
                "publish" in stats
                and "ack" in stats
                and "messages_ready" in data
                and "messages_unacknowledged" in data
            ),
            "publish": stats.get("publish", 0),
            "ack": stats.get("ack", 0),
            "pending": data.get("messages_ready", 0) + data.get("messages_unacknowledged", 0),
            "consumers": data.get("consumers", 0),
        }


def search(api, query: str) -> Json:
    return api.json("/api/search/search?" + urlencode({"q": query, "limit": 100}))


async def discover(api, song: Json, seconds: float) -> Json:
    def check():
        result = search(api, song["title"].upper())
        ids = [item["song_id"] for item in result["items"]]
        if song["song_id"] not in ids:
            return False, result
        require(
            ids == [song["song_id"]] and result["next_cursor"] is None,
            "Search returned duplicate/unrelated results for a unique fixture title",
        )
        item = result["items"][0]
        require(
            item["title"] == song["title"] and item["artist"] == "Integration test",
            "Search metadata differs from the upload",
        )
        return True, result

    return await poll(check, seconds, "new song appears exactly once in Search")


async def replay(channel, message, queue: str) -> None:
    import aio_pika

    await channel.default_exchange.publish(
        aio_pika.Message(
            message.body,
            content_type=message.content_type,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=message.message_id,
            type=message.type,
            correlation_id=message.correlation_id,
            app_id=message.app_id,
        ),
        routing_key=queue,
        mandatory=True,
        timeout=15,
    )


async def duplicates(api, channel, observer, args, report: Json) -> None:
    metrics = QueueMetrics(args.request_timeout)

    # Let management statistics catch up with the initial SongReady deliveries.
    # Any extra publishing during this isolated test causes a failure, not a pass.
    previous = None
    stable_since = time.monotonic()

    def settled():
        nonlocal previous, stable_since
        current = metrics.snapshot()
        if current != previous or current["pending"]:
            stable_since = time.monotonic()
        previous = current
        return (
            current["statistics_ready"]
            and current["consumers"] > 0
            and current["pending"] == 0
            and time.monotonic() - stable_since >= 6
        ), current

    before = await poll(settled, args.timeout, "Search worker and queue statistics settle")
    page = await asyncio.to_thread(search, api, report["run_id"])
    require(
        {item["song_id"] for item in page["items"]}
        == {song["song_id"] for song in report["songs"]},
        "Missing generated Search entries",
    )
    # Replaying the older item also detects incorrect resetting of indexed_at:
    # its position must remain behind the newer item.
    song_id = page["items"][-1]["song_id"]
    original = await observer.event("SongReady", song_id, args.timeout)
    evidence = report["duplicate_delivery"] = {
        "song_id": song_id,
        "event_id": json.loads(original.body)["event_id"],
        "copies": 2,
        "queue_before": before,
        "search_before": page,
    }
    for _ in range(2):
        await replay(channel, original, "search.song-ready")

    def acknowledged():
        current = metrics.snapshot()
        evidence["queue_last"] = current
        require(current["statistics_ready"], "RabbitMQ queue statistics disappeared")
        published, acked = current["publish"] - before["publish"], current["ack"] - before["ack"]
        require(published >= 0 and acked >= 0, "RabbitMQ counters reset during duplicate check")
        require(
            published <= 2 and acked <= 2,
            "Unrelated Search traffic detected; run against a quiet disposable stack",
        )
        return (published == acked == 2 and current["pending"] == 0), current

    after = await poll(
        acknowledged, args.timeout, "both duplicate Search deliveries are acknowledged"
    )
    repeated = await asyncio.to_thread(search, api, report["run_id"])
    require(repeated == page, "Repeated SongReady changed Search results, order or metadata")
    evidence.update(queue_after=after, search_after=repeated)
    passed(
        report,
        "duplicate SongReady deliveries are acknowledged without duplicate results or reordering",
    )


def verify_ranking(api, report: Json) -> None:
    calm, upbeat = (song["song_id"] for song in report["songs"])
    baseline = api.json("/api/recommendation/recommendations?limit=50")
    rainy = api.json("/api/recommendation/recommendations?lat=1.35&lon=103.82&limit=50")
    report["recommendation"] = {"without_location": baseline, "rain": rainy}
    require(
        baseline["weather_used"] is False and baseline["weather"] is None,
        "Recommendations without a location unexpectedly used weather",
    )
    require(
        all(item["reason"] == "GENERAL" for item in baseline["items"]), "Invalid fallback reasons"
    )
    require(
        rainy["weather_used"] is True and rainy["weather"]["condition"] == "RAIN",
        "Use ingestion.compose.yaml: Recommendation must use fixed RAIN weather and real Catalogue",
    )
    base_ids = [item["song_id"] for item in baseline["items"]]
    rain_ids = [item["song_id"] for item in rainy["items"]]
    require(
        calm in base_ids and upbeat in base_ids and calm in rain_ids and upbeat in rain_ids,
        "Recommendation candidate pool omitted the newly generated fixtures",
    )
    require(base_ids.index(upbeat) < base_ids.index(calm), "Unexpected baseline creation order")
    require(rain_ids.index(calm) < rain_ids.index(upbeat), "RAIN did not promote the calm fixture")
    reasons = {item["song_id"]: item["reason"] for item in rainy["items"]}
    require(
        reasons[calm] == "WEATHER_MATCH" and reasons[upbeat] == "GENERAL",
        "Wrong mood match reasons",
    )
    passed(report, "uploaded mood reaches Catalogue and changes real Recommendation ordering")


def repair_lyrics(song: Json, lyrics: bytes) -> None:
    import boto3
    from botocore.config import Config

    # Only the key returned for THIS upload may be overwritten.
    expected = f"lyrics/{uuid.UUID(song['song_id'])}.lrc"
    require(song["lyrics_reference"] == expected, "Refusing to repair an unrelated S3 key")
    client = boto3.client(
        "s3",
        endpoint_url=os.getenv("S3_ENDPOINT_URL", "http://s3:9000"),
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        config=Config(
            connect_timeout=5,
            read_timeout=10,
            retries={"total_max_attempts": 2},
            s3={"addressing_style": "path"},
        ),
    )
    try:
        client.put_object(
            Bucket=os.getenv("S3_BUCKET", "syncwave-audio"),
            Key=expected,
            Body=lyrics,
            ContentType="text/plain; charset=utf-8",
        )
    finally:
        client.close()


async def recovery(api, upload, channel, observer, args, report: Json) -> None:
    song: Json = {"run_id": f"{report['run_id']}-recovery", "result": "FAIL"}
    report["recovery"] = song
    audio = upload.audio_fixture(880)
    title = f"upload-flow-{song['run_id']}"
    body, content_type = upload.multipart(title, audio, lyrics=b"Lyrics without any time tags\n")
    receipt = await asyncio.to_thread(
        api.json, "/api/upload/uploads", data=body, content_type=content_type, expected_status=202
    )
    song.update(
        {
            key: receipt[key]
            for key in ("song_id", "event_id", "title", "audio_reference", "lyrics_reference")
        }
    )
    song_id = str(uuid.UUID(song["song_id"]))

    def failed():
        result = api.json(f"/api/catalogue/songs/{song_id}", allow_missing=True)
        return result is not None and result["processing_status"] == "PARTIAL", result

    partial = await poll(failed, args.timeout, "failed lyrics are visible as Catalogue PARTIAL")
    require(
        partial["lyrics_status"] == "FAILED" and partial["waveform_status"] == "READY",
        "Bad lyrics unexpectedly blocked or failed audio processing",
    )
    failed_lyrics = await asyncio.to_thread(api.json, f"/api/lyrics/songs/{song_id}/lyrics")
    require(
        failed_lyrics["status"] == "FAILED"
        and failed_lyrics["error"]["code"] == "LYRICS_NOT_TIMESTAMPED"
        and bool(failed_lyrics["error"]["message"]),
        "Lyrics failure has no actionable error",
    )
    hidden = await asyncio.to_thread(search, api, title)
    require(hidden["items"] == [], "Search indexed a PARTIAL song")
    before = await asyncio.to_thread(api.json, f"/api/waveform/songs/{song_id}/waveform?points=32")
    original = await observer.event("SongUploaded", song_id, args.timeout)
    require(json.loads(original.body)["event_id"] == song["event_id"], "DLQ event ID differs")
    song["failure"] = {"catalogue": partial, "lyrics": failed_lyrics, "search": hidden}
    passed(
        report, "invalid lyrics expose a clear failure, leave waveform READY and stay out of Search"
    )

    await asyncio.to_thread(repair_lyrics, song, upload.LYRICS_FIXTURE)
    # Replay only this captured DLQ copy directly to the failed consumer.
    # The original dead letter remains available for inspection in the shared DLQ.
    await replay(channel, original, "lyrics.song-uploaded")

    def recovered():
        result = api.json(f"/api/catalogue/songs/{song_id}")
        return result["processing_status"] == "READY", result

    # PARTIAL is expected until the new LyricsProcessed arrives. The standard
    # happy-path verifier intentionally rejects PARTIAL, so wait for recovery first.
    await poll(recovered, args.timeout, "same Catalogue song recovers from PARTIAL to READY")
    await asyncio.to_thread(upload.verify, api, args.timeout, song, audio=audio)
    await discover(api, song, args.timeout)
    after = await asyncio.to_thread(api.json, f"/api/waveform/songs/{song_id}/waveform?points=32")
    require(after == before, "Lyrics-only recovery changed the successful waveform")
    song.update(
        result="PASS",
        replayed_event_id=song["event_id"],
        waveform_unchanged=True,
        dead_letter_retained=True,
    )
    passed(report, "repair and targeted replay recover the same song to READY and discoverable")


async def run(args, report: Json) -> None:
    import aio_pika

    upload = load_upload_flow()
    api = upload.Api(args.base_url, args.request_timeout)
    for path in ("/api/search/health", "/api/recommendation/health"):
        await asyncio.to_thread(api.request, path)
    connection = await aio_pika.connect(
        host=os.getenv("AMQP_HOST", "rabbitmq"),
        port=int(os.getenv("AMQP_PORT", "5672")),
        login=os.getenv("AMQP_USER", "syncwave"),
        password=os.getenv("AMQP_PASSWORD", "syncwave"),
        virtualhost=os.getenv("AMQP_VHOST", "/"),
        timeout=args.request_timeout,
    )
    try:
        channel = await connection.channel(publisher_confirms=True, on_return_raises=True)
        events = await channel.get_exchange("syncwave.events")
        dlx = await channel.get_exchange("syncwave.dlx")
        queue = await channel.declare_queue(exclusive=True, auto_delete=True)
        report["observer_queue"] = queue.name
        await queue.bind(events, routing_key="song.ready")
        await queue.bind(dlx, routing_key="lyrics.song-uploaded")
        observer = Observer(queue)
        for mood, frequency in (("calm", 440), ("upbeat", 660)):
            song = {"run_id": f"{report['run_id']}-{mood}", "result": "FAIL"}
            report["songs"].append(song)
            # Case/whitespace normalization is checked in both receipt and Catalogue.
            await asyncio.to_thread(
                upload.run,
                api,
                args.timeout,
                song,
                audio=upload.audio_fixture(frequency),
                mood=f" {mood.upper()} ",
            )
            song["search"] = await discover(api, song, args.timeout)
            song["result"] = "PASS"
        passed(
            report,
            "both uploaded songs are READY, playable and discoverable by case-insensitive title",
        )
        await duplicates(api, channel, observer, args, report)
        await asyncio.to_thread(verify_ranking, api, report)
        await recovery(api, upload, channel, observer, args, report)
    finally:
        async with asyncio.timeout(args.request_timeout):
            await connection.close()
        report["cleanup"]["observer_connection_closed"] = True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://gateway:8080")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--request-timeout", type=float, default=15)
    parser.add_argument("--report", type=Path, default=Path("/tmp/ingestion-flow-report.json"))
    args = parser.parse_args()
    if any(not 0 < value < float("inf") for value in (args.timeout, args.request_timeout)):
        parser.error("timeouts must be finite positive numbers")
    report: Json = {
        "run_id": uuid.uuid4().hex,
        "result": "FAIL",
        "checks": [],
        "songs": [],
        "cleanup": {"observer_connection_closed": False},
        "retained_data": (
            "Three songs/S3 objects and the recovery fixture's original lyrics DLQ entry"
        ),
    }
    started = time.monotonic()
    try:
        asyncio.run(run(args, report))
        report["result"] = "PASS"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"FAIL {report['error']}", file=sys.stderr, flush=True)
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    print(json.dumps(report, indent=2), flush=True)
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"FAIL writing report: {exc}", file=sys.stderr)
        return 1
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
