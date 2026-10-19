import uuid
from collections.abc import Callable
from typing import Any

import pytest

from waveform_service.shared.db import Status, WaveformRepository
from waveform_service.shared.events import QUEUE, previous_failures
from waveform_service.worker.handler import WaveformHandler

from .conftest import (
    BAND_COUNT,
    FRAME_RATE,
    MAX_BYTES,
    PCM,
    POINTS,
    SAMPLE_RATE,
    UNDECODABLE,
    FakeMessage,
    FakePublisher,
    FakeStorage,
    fake_decoder,
)

pytestmark = pytest.mark.anyio

SongUploaded = Callable[..., dict[str, Any]]
MakeMessage = Callable[..., FakeMessage]


async def test_generates_the_waveform_and_announces_it(
    handler: WaveformHandler,
    repository: WaveformRepository,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["audio_reference"]] = PCM
    message = make_message(event)

    await handler(message)

    assert message.outcome == "ack"
    record = await repository.get(uuid.UUID(event["song_id"]), with_bands=True)
    assert record is not None
    assert record.status == Status.READY
    assert record.peaks == [0.5, 1.0, 0.0, 0.003]
    assert (record.points, record.duration_ms, record.sample_rate) == (4, 1000, SAMPLE_RATE)
    assert record.band_frame_rate == FRAME_RATE
    assert len(record.band_edges_hz or []) == BAND_COUNT + 1
    assert len(record.bands or b"") == 4 * BAND_COUNT  # 4 frames in 1 second
    assert record.source_event_id == event["event_id"]
    [(routing_key, processed)] = publisher.events
    assert routing_key == "waveform.processed"
    assert processed["event_type"] == "WaveformProcessed"
    assert processed["song_id"] == event["song_id"]
    assert processed["correlation_id"] == event["event_id"]
    assert processed["producer"] == "waveform"
    assert processed["payload"] == {"points": POINTS, "duration_ms": 1000}
    assert publisher.dead_lettered == []


async def test_duplicate_delivery_re_announces_without_reprocessing(
    handler: WaveformHandler,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["audio_reference"]] = PCM

    first, second = make_message(event), make_message(event)
    await handler(first)
    await handler(second)

    assert (first.outcome, second.outcome) == ("ack", "ack")
    assert len(storage.downloads) == 1
    assert [routing_key for routing_key, _ in publisher.events] == ["waveform.processed"] * 2
    assert publisher.events[1][1]["payload"] == {"points": POINTS, "duration_ms": 1000}


async def test_undecodable_audio_fails_permanently_on_the_first_attempt(
    handler: WaveformHandler,
    repository: WaveformRepository,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["audio_reference"]] = UNDECODABLE
    message = make_message(event)

    await handler(message)

    assert message.outcome == "ack"
    assert publisher.dead_lettered == [(QUEUE, message.body)]
    [(routing_key, failed)] = publisher.events
    assert routing_key == "waveform.failed"
    assert failed["event_type"] == "WaveformProcessingFailed"
    assert failed["correlation_id"] == event["event_id"]
    assert failed["payload"]["error_code"] == "AUDIO_UNDECODABLE"
    assert failed["payload"]["attempts"] == 1
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None and record.status == Status.FAILED
    assert record.error_code == "AUDIO_UNDECODABLE"


@pytest.mark.parametrize(
    ("audio", "error_code"),
    [
        pytest.param(b"", "AUDIO_EMPTY", id="empty"),
        pytest.param(PCM * MAX_BYTES, "AUDIO_TOO_LARGE", id="too-large"),
    ],
)
async def test_empty_or_too_large_audio_fails_permanently(
    handler: WaveformHandler,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
    audio: bytes,
    error_code: str,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["audio_reference"]] = audio

    await handler(make_message(event))

    assert publisher.events[0][1]["payload"]["error_code"] == error_code


@pytest.mark.parametrize("failures", [0, 1])
async def test_missing_audio_is_retried(
    handler: WaveformHandler,
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
    handler: WaveformHandler,
    repository: WaveformRepository,
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
    assert routing_key == "waveform.failed"
    assert failed["payload"]["error_code"] == "AUDIO_NOT_FOUND"
    assert failed["payload"]["attempts"] == 3
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None and record.status == Status.FAILED


async def test_failed_song_is_reprocessed_when_the_event_is_replayed(
    handler: WaveformHandler,
    repository: WaveformRepository,
    storage: FakeStorage,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    await handler(make_message(event, failures=2))  # gives up: audio missing
    storage.objects[event["payload"]["audio_reference"]] = PCM

    message = make_message(event)  # e.g. moved back from the DLQ by hand
    await handler(message)

    assert message.outcome == "ack"
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None and record.status == Status.READY
    assert record.error_code is None


async def test_unreadable_message_goes_to_the_dlq_without_an_event(
    handler: WaveformHandler, publisher: FakePublisher, make_message: MakeMessage
) -> None:
    message = make_message(b"not json")

    await handler(message)

    assert message.outcome == "ack"
    assert publisher.dead_lettered == [(QUEUE, b"not json")]
    assert publisher.events == []


async def test_event_without_audio_reference_reports_the_failure(
    handler: WaveformHandler,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    del event["payload"]["audio_reference"]

    await handler(make_message(event))

    assert len(publisher.dead_lettered) == 1
    [(_, failed)] = publisher.events
    assert failed["payload"]["error_code"] == "INVALID_EVENT"


async def test_a_failure_never_overwrites_a_ready_waveform(
    handler: WaveformHandler,
    repository: WaveformRepository,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    storage.objects[event["payload"]["audio_reference"]] = PCM
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
    handler = WaveformHandler(
        BrokenRepository(),
        storage,
        publisher,
        decoder=fake_decoder,
        sample_rate=SAMPLE_RATE,
        points=POINTS,
        frame_rate=FRAME_RATE,
        band_count=BAND_COUNT,
        max_bytes=MAX_BYTES,
    )
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
    repository: WaveformRepository, storage: FakeStorage, make_message: MakeMessage
) -> None:
    handler = WaveformHandler(
        repository,
        storage,
        BrokenPublisher(),
        decoder=fake_decoder,
        sample_rate=SAMPLE_RATE,
        points=POINTS,
        frame_rate=FRAME_RATE,
        band_count=BAND_COUNT,
        max_bytes=MAX_BYTES,
    )
    message = make_message(b"not json")

    await handler(message)

    assert message.outcome == "retry"


def test_previous_failures_reads_this_queues_rejections() -> None:
    assert previous_failures({}, QUEUE) == 0
    assert previous_failures(None, QUEUE) == 0
    headers = {
        "x-death": [
            {"queue": b"waveform.song-uploaded.retry", "reason": b"expired", "count": 5},
            {"queue": b"waveform.song-uploaded", "reason": b"rejected", "count": 2},
        ]
    }
    assert previous_failures(headers, QUEUE) == 2
    assert previous_failures(headers, "lyrics.song-uploaded") == 0
