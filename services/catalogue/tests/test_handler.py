import uuid
from collections.abc import Callable
from typing import Any

import pytest

from catalogue_service.shared.db import ProcessingStatus, StageStatus
from catalogue_service.shared.events import QUEUE_PROCESSING_RESULTS, QUEUE_SONG_UPLOADED
from catalogue_service.worker.handler import CatalogueHandler

from .conftest import (
    FakeMessage,
    FakePublisher,
)  # type aliases only; fixtures injected by pytest

pytestmark = pytest.mark.anyio

SongUploaded = Callable[..., dict[str, Any]]
MakeMessage = Callable[..., FakeMessage]


def processing_event(
    event_type: str,
    song_id: str,
    *,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "version": 1,
        "song_id": song_id,
        "timestamp": "2026-10-08T12:01:00.000Z",
        "producer": "lyrics",
        "correlation_id": correlation_id,
        "payload": payload or {},
    }


async def test_creates_song_from_uploaded_event(
    handler: CatalogueHandler,
    repository,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded(lyrics_reference="lyrics/song.lrc")
    message = make_message(event)

    await handler(message, QUEUE_SONG_UPLOADED)

    assert message.outcome == "ack"
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None
    assert record.title == event["payload"]["title"]
    assert record.artist == event["payload"]["artist"]
    assert record.audio_reference == event["payload"]["audio_reference"]
    assert record.lyrics_reference == event["payload"]["lyrics_reference"]
    assert record.lyrics_status == StageStatus.PROCESSING
    assert record.waveform_status == StageStatus.PROCESSING
    assert record.processing_status == ProcessingStatus.PROCESSING
    assert record.source_event_id == event["event_id"]
    assert publisher.events == []
    assert publisher.dead_lettered == []


async def test_song_without_lyrics_has_lyrics_ready(
    handler: CatalogueHandler,
    repository,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded(lyrics_reference=None)
    message = make_message(event)

    await handler(message, QUEUE_SONG_UPLOADED)

    assert message.outcome == "ack"
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None
    assert record.lyrics_status == StageStatus.READY
    assert record.lyrics_reference is None
    assert record.waveform_status == StageStatus.PROCESSING
    assert record.processing_status == ProcessingStatus.PROCESSING


async def test_song_uploaded_preserves_optional_uploader(
    handler: CatalogueHandler,
    repository,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    uploader_id = uuid.uuid4()
    event = song_uploaded(uploader_id=str(uploader_id))
    message = make_message(event)

    await handler(message, QUEUE_SONG_UPLOADED)

    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record is not None
    assert record.uploader_id == uploader_id


async def test_duplicate_upload_event_first_write_wins(
    handler: CatalogueHandler,
    repository,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded()
    first, second = make_message(event), make_message(event)

    await handler(first, QUEUE_SONG_UPLOADED)
    await handler(second, QUEUE_SONG_UPLOADED)

    assert (first.outcome, second.outcome) == ("ack", "ack")
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record.source_event_id == event["event_id"]
    assert publisher.events == []


async def test_lyrics_processed_makes_lyrics_ready(
    handler: CatalogueHandler,
    repository,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded(lyrics_reference="lyrics/song.lrc")
    await handler(make_message(event), QUEUE_SONG_UPLOADED)

    result = processing_event(
        "LyricsProcessed",
        event["song_id"],
        payload={"line_count": 2},
        correlation_id=event["event_id"],
    )
    await handler(make_message(result), QUEUE_PROCESSING_RESULTS)

    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record.lyrics_status == StageStatus.READY
    assert record.waveform_status == StageStatus.PROCESSING
    assert record.processing_status == ProcessingStatus.PROCESSING  # waveform not done
    assert publisher.events == []  # not fully ready yet


async def test_song_ready_published_when_both_stages_ready(
    handler: CatalogueHandler,
    repository,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded(lyrics_reference="lyrics/song.lrc")
    await handler(make_message(event), QUEUE_SONG_UPLOADED)

    await handler(
        make_message(
            processing_event(
                "LyricsProcessed",
                event["song_id"],
                payload={"line_count": 2},
                correlation_id=event["event_id"],
            )
        ),
        QUEUE_PROCESSING_RESULTS,
    )
    await handler(
        make_message(
            processing_event(
                "WaveformProcessed",
                event["song_id"],
                payload={"points": 1000, "duration_ms": 213000},
                correlation_id=event["event_id"],
            )
        ),
        QUEUE_PROCESSING_RESULTS,
    )

    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record.processing_status == ProcessingStatus.READY
    assert record.duration_ms == 213000
    [(routing_key, ready)] = publisher.events
    assert routing_key == "song.ready"
    assert ready["event_type"] == "SongReady"
    assert ready["payload"]["song_id"] == event["song_id"]
    assert ready["correlation_id"] == event["event_id"]


async def test_partial_when_one_stage_failed(
    handler: CatalogueHandler,
    repository,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded(lyrics_reference="lyrics/song.lrc")
    await handler(make_message(event), QUEUE_SONG_UPLOADED)

    await handler(
        make_message(
            processing_event(
                "LyricsProcessed",
                event["song_id"],
                payload={"line_count": 2},
                correlation_id=event["event_id"],
            )
        ),
        QUEUE_PROCESSING_RESULTS,
    )
    await handler(
        make_message(
            processing_event(
                "WaveformProcessingFailed",
                event["song_id"],
                payload={"error_code": "AUDIO_UNDECODABLE"},
                correlation_id=event["event_id"],
            )
        ),
        QUEUE_PROCESSING_RESULTS,
    )

    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record.lyrics_status == StageStatus.READY
    assert record.waveform_status == StageStatus.FAILED
    assert record.processing_status == ProcessingStatus.PARTIAL
    assert publisher.events == []  # PARTIAL is not published


async def test_failed_when_both_stages_failed(
    handler: CatalogueHandler,
    repository,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded(lyrics_reference="lyrics/song.lrc")
    await handler(make_message(event), QUEUE_SONG_UPLOADED)

    await handler(
        make_message(
            processing_event(
                "LyricsProcessingFailed",
                event["song_id"],
                payload={"error_code": "LYRICS_INVALID"},
                correlation_id=event["event_id"],
            )
        ),
        QUEUE_PROCESSING_RESULTS,
    )
    await handler(
        make_message(
            processing_event(
                "WaveformProcessingFailed",
                event["song_id"],
                payload={"error_code": "AUDIO_UNDECODABLE"},
                correlation_id=event["event_id"],
            )
        ),
        QUEUE_PROCESSING_RESULTS,
    )

    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record.processing_status == ProcessingStatus.FAILED


async def test_stale_failure_does_not_overwrite_ready(
    handler: CatalogueHandler,
    repository,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded(lyrics_reference="lyrics/song.lrc")
    await handler(make_message(event), QUEUE_SONG_UPLOADED)
    await handler(
        make_message(
            processing_event(
                "LyricsProcessed",
                event["song_id"],
                payload={"line_count": 2},
                correlation_id=event["event_id"],
            )
        ),
        QUEUE_PROCESSING_RESULTS,
    )

    broken = processing_event(
        "LyricsProcessingFailed",
        event["song_id"],
        payload={"error_code": "LYRICS_INVALID"},
        correlation_id=event["event_id"],
    )
    await handler(make_message(broken), QUEUE_PROCESSING_RESULTS)

    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record.lyrics_status == StageStatus.READY  # preserved


async def test_duplicate_processing_result_is_idempotent(
    handler: CatalogueHandler,
    repository,
    publisher: FakePublisher,
    song_uploaded: SongUploaded,
    make_message: MakeMessage,
) -> None:
    event = song_uploaded(lyrics_reference="lyrics/song.lrc")
    await handler(make_message(event), QUEUE_SONG_UPLOADED)
    # Make the song fully READY: both stages report success.
    await handler(
        make_message(
            processing_event(
                "LyricsProcessed",
                event["song_id"],
                payload={"line_count": 2},
                correlation_id=event["event_id"],
            )
        ),
        QUEUE_PROCESSING_RESULTS,
    )
    await handler(
        make_message(
            processing_event(
                "WaveformProcessed",
                event["song_id"],
                payload={"points": 1000, "duration_ms": 213000},
                correlation_id=event["event_id"],
            )
        ),
        QUEUE_PROCESSING_RESULTS,
    )
    publisher.events.clear()
    record = await repository.get(uuid.UUID(event["song_id"]))
    assert record.processing_status == ProcessingStatus.READY

    result = processing_event(
        "WaveformProcessed",
        event["song_id"],
        payload={"points": 1000, "duration_ms": 213000},
        correlation_id=event["event_id"],
    )
    first, second = make_message(result), make_message(result)
    await handler(first, QUEUE_PROCESSING_RESULTS)
    await handler(second, QUEUE_PROCESSING_RESULTS)

    assert (first.outcome, second.outcome) == ("ack", "ack")
    # Already READY: re-announced (crash-repair), idempotent for consumers.
    assert len(publisher.events) == 2
    assert all(event["event_type"] == "SongReady" for _, event in publisher.events)


async def test_unknown_song_is_transient_retry(
    handler: CatalogueHandler,
    publisher: FakePublisher,
    make_message: MakeMessage,
) -> None:
    unknown = str(uuid.uuid4())
    message = make_message(processing_event("LyricsProcessed", unknown, payload={"line_count": 1}))

    await handler(message, QUEUE_PROCESSING_RESULTS)

    assert message.outcome == "retry"
    assert publisher.events == []
    assert publisher.dead_lettered == []


async def test_invalid_event_is_dead_lettered(
    handler: CatalogueHandler,
    publisher: FakePublisher,
    make_message: MakeMessage,
) -> None:
    message = make_message(b"not json")

    await handler(message, QUEUE_SONG_UPLOADED)

    assert message.outcome == "ack"
    assert publisher.dead_lettered == [(QUEUE_SONG_UPLOADED, b"not json")]
    assert publisher.events == []
