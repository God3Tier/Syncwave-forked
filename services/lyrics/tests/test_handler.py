import uuid
from collections.abc import Callable
from typing import Any

import pytest

from lyrics_service.shared.db import LyricsRepository, Status
from lyrics_service.shared.events import QUEUE, previous_failures
from lyrics_service.worker.handler import LyricsHandler

from .conftest import MAX_BYTES, FakeMessage, FakePublisher, FakeStorage

pytestmark = pytest.mark.anyio

LRC = b"[ti:Example]\n[00:02.50]World\n[00:01.00]Hello\n"
SongUploaded = Callable[..., dict[str, Any]]
MakeMessage = Callable[..., FakeMessage]


async def test_processes_lyrics_and_announces_them(
    handler: LyricsHandler,
    repository: LyricsRepository,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["lyrics_reference"]] = LRC
    message = make_message(event)

    await handler(message)

    assert message.outcome == "ack"
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None
    assert record.status == Status.READY
    assert record.source_event_id == event["event_id"]
    assert record.lines == [{"time_ms": 1000, "text": "Hello"}, {"time_ms": 2500, "text": "World"}]
    [(routing_key, processed)] = publisher.events
    assert routing_key == "lyrics.processed"
    assert processed["event_type"] == "LyricsProcessed"
    assert processed["song_id"] == event["song_id"]
    assert processed["correlation_id"] == event["event_id"]
    assert processed["producer"] == "lyrics"
    assert processed["payload"] == {"line_count": 2}
    assert publisher.dead_lettered == []


async def test_song_without_lyrics_is_ready_with_no_lines(
    handler: LyricsHandler,
    repository: LyricsRepository,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded(lyrics_reference=None)
    message = make_message(event)

    await handler(message)

    assert message.outcome == "ack"
    assert storage.reads == []
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None and record.status == Status.READY and record.lines == []
    assert publisher.events[0][1]["payload"] == {"line_count": 0}


async def test_duplicate_delivery_re_announces_without_reprocessing(
    handler: LyricsHandler,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["lyrics_reference"]] = LRC

    first, second = make_message(event), make_message(event)
    await handler(first)
    await handler(second)

    assert (first.outcome, second.outcome) == ("ack", "ack")
    assert len(storage.reads) == 1
    assert [routing_key for routing_key, _ in publisher.events] == ["lyrics.processed"] * 2
    assert publisher.events[1][1]["payload"] == {"line_count": 2}


async def test_invalid_lyrics_fail_permanently_on_the_first_attempt(
    handler: LyricsHandler,
    repository: LyricsRepository,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["lyrics_reference"]] = b"no timestamps here"
    message = make_message(event)

    await handler(message)

    assert message.outcome == "ack"
    assert publisher.dead_lettered == [(QUEUE, message.body)]
    [(routing_key, failed)] = publisher.events
    assert routing_key == "lyrics.failed"
    assert failed["event_type"] == "LyricsProcessingFailed"
    assert failed["correlation_id"] == event["event_id"]
    assert failed["payload"]["error_code"] == "LYRICS_NOT_TIMESTAMPED"
    assert failed["payload"]["attempts"] == 1
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None and record.status == Status.FAILED
    assert record.error_code == "LYRICS_NOT_TIMESTAMPED"


async def test_too_large_lyrics_fail_permanently(
    handler: LyricsHandler,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["lyrics_reference"]] = b"[00:01.00]x\n" * MAX_BYTES

    await handler(make_message(event))

    assert publisher.events[0][1]["payload"]["error_code"] == "LYRICS_TOO_LARGE"


@pytest.mark.parametrize("failures", [0, 1])
async def test_missing_lyrics_file_is_retried(
    handler: LyricsHandler,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
    failures: int,
) -> None:
    message = make_message(song_uploaded(), failures=failures)

    await handler(message)

    assert message.outcome == "retry"
    assert publisher.events == []
    assert publisher.dead_lettered == []


async def test_gives_up_on_the_third_attempt(
    handler: LyricsHandler,
    repository: LyricsRepository,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    message = make_message(event, failures=2)

    await handler(message)

    assert message.outcome == "ack"
    assert publisher.dead_lettered == [(QUEUE, message.body)]
    [(routing_key, failed)] = publisher.events
    assert routing_key == "lyrics.failed"
    assert failed["payload"]["error_code"] == "LYRICS_FILE_NOT_FOUND"
    assert failed["payload"]["attempts"] == 3
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None and record.status == Status.FAILED


async def test_failed_song_is_reprocessed_when_the_event_is_replayed(
    handler: LyricsHandler,
    repository: LyricsRepository,
    storage: FakeStorage,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    await handler(make_message(event, failures=2))  # gives up: file missing
    storage.objects[event["payload"]["lyrics_reference"]] = LRC

    message = make_message(event)  # e.g. moved back from the DLQ by hand
    await handler(message)

    assert message.outcome == "ack"
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None and record.status == Status.READY
    assert record.error_code is None


async def test_unreadable_message_goes_to_the_dlq_without_an_event(
    handler: LyricsHandler, publisher: FakePublisher, make_message: MakeMessage
) -> None:
    message = make_message(b"not json")

    await handler(message)

    assert message.outcome == "ack"
    assert publisher.dead_lettered == [(QUEUE, b"not json")]
    assert publisher.events == []


async def test_invalid_event_with_a_song_id_reports_the_failure(
    handler: LyricsHandler,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    event["payload"]["lyrics_reference"] = 42

    await handler(make_message(event))

    assert len(publisher.dead_lettered) == 1
    [(_, failed)] = publisher.events
    assert failed["payload"]["error_code"] == "INVALID_EVENT"


async def test_a_failure_never_overwrites_ready_lyrics(
    handler: LyricsHandler,
    repository: LyricsRepository,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["lyrics_reference"]] = LRC
    await handler(make_message(event))
    publisher.events.clear()

    broken = dict(event, event_type="SomethingElse")
    message = make_message(broken)
    await handler(message)

    assert message.outcome == "ack"
    assert len(publisher.dead_lettered) == 1
    assert publisher.events == []
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None and record.status == Status.READY


class BrokenRepository:
    """A database that is down."""

    async def get(self, song_id: uuid.UUID) -> None:
        raise ConnectionError("database unavailable")

    async def mark_failed(self, *args: object) -> bool:
        raise ConnectionError("database unavailable")


async def test_database_outage_is_retried_then_reported(
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    handler = LyricsHandler(BrokenRepository(), storage, publisher, max_bytes=MAX_BYTES)
    event = song_uploaded()

    first = make_message(event)
    await handler(first)
    last = make_message(event, failures=2)
    await handler(last)

    assert first.outcome == "retry"
    assert last.outcome == "ack"
    [(_, failed)] = publisher.events
    assert failed["payload"]["error_code"] == "PROCESSING_ERROR"
    assert "database unavailable" in failed["payload"]["message"]


class BrokenPublisher(FakePublisher):
    async def dead_letter(self, message: FakeMessage, queue: str) -> None:
        raise ConnectionError("broker unavailable")


async def test_unexpected_errors_send_the_message_to_retry(
    repository: LyricsRepository, storage: FakeStorage, make_message: MakeMessage
) -> None:
    handler = LyricsHandler(repository, storage, BrokenPublisher(), max_bytes=MAX_BYTES)
    message = make_message(b"not json")

    await handler(message)

    assert message.outcome == "retry"


def test_previous_failures_reads_this_queues_rejections() -> None:
    assert previous_failures({}, QUEUE) == 0
    assert previous_failures(None, QUEUE) == 0
    headers = {
        "x-death": [
            {"queue": b"lyrics.song-uploaded.retry", "reason": b"expired", "count": 5},
            {"queue": b"lyrics.song-uploaded", "reason": b"rejected", "count": 2},
        ]
    }
    assert previous_failures(headers, QUEUE) == 2
    assert previous_failures(headers, "waveform.song-uploaded") == 0
