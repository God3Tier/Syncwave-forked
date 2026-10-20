"""Contract tests: the events Catalogue consumes and publishes match the
shared schemas in contracts/events/. CI re-runs them when contracts change
(CONTRACT_PATHS in the root .gitlab-ci.yml)."""

import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from catalogue_service.shared.events import (
    QUEUE_PROCESSING_RESULTS,
    QUEUE_SONG_UPLOADED,
    parse_song_uploaded,
)
from catalogue_service.worker.handler import CatalogueHandler

from .conftest import (
    FakeMessage,
    FakePublisher,
)  # type aliases only; fixtures injected by pytest

EVENTS = Path(__file__).resolve().parents[3] / "contracts" / "events"
SCHEMA_FILES = {
    "SongUploaded": "song-uploaded.schema.json",
    "SongReady": "song-ready.schema.json",
    "LyricsProcessed": "lyrics-processed.schema.json",
    "WaveformProcessed": "waveform-processed.schema.json",
}

pytestmark = pytest.mark.skipif(not EVENTS.is_dir(), reason="contracts/ is not available")


def validator(event_type: str) -> Draft202012Validator:
    schemas = [json.loads(path.read_text("utf-8")) for path in EVENTS.glob("*.schema.json")]
    registry: Registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    schema = json.loads((EVENTS / SCHEMA_FILES[event_type]).read_text("utf-8"))
    return Draft202012Validator(
        schema, registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER
    )


def test_the_song_uploaded_example_is_understood() -> None:
    example = (EVENTS / "examples" / "song-uploaded.json").read_bytes()

    event = parse_song_uploaded(example)

    assert event.title == "Demo"
    assert event.artist == "SyncWave Artist"
    assert event.audio_reference == "audio/0b6c2f4e-8d3a-4f7b-b1e2-9c5d7a3e1f20.mp3"


def test_test_events_follow_the_song_uploaded_schema(
    song_uploaded: Callable[..., dict[str, Any]],
) -> None:
    validator("SongUploaded").validate(song_uploaded())


def test_test_events_follow_the_song_ready_schema() -> None:
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "SongReady",
        "version": 1,
        "song_id": str(uuid.uuid4()),
        "timestamp": "2026-10-08T12:05:00.000Z",
        "producer": "catalogue",
        "payload": {"song_id": "0b6c2f4e-8d3a-4f7b-b1e2-9c5d7a3e1f20"},
    }
    validator("SongReady").validate(event)


@pytest.mark.anyio
async def test_every_published_event_matches_its_schema(
    handler: CatalogueHandler,
    publisher: FakePublisher,
    song_uploaded: Callable[..., dict[str, Any]],
    make_message: Callable[..., FakeMessage],
) -> None:
    uploaded = song_uploaded(lyrics_reference="lyrics/song.lrc")
    lyrics_processed = {
        "event_id": str(uuid.uuid4()),
        "event_type": "LyricsProcessed",
        "version": 1,
        "song_id": uploaded["song_id"],
        "timestamp": "2026-10-08T12:01:00.000Z",
        "producer": "lyrics",
        "correlation_id": uploaded["event_id"],
        "payload": {"line_count": 2},
    }
    waveform_processed = {
        "event_id": str(uuid.uuid4()),
        "event_type": "WaveformProcessed",
        "version": 1,
        "song_id": uploaded["song_id"],
        "timestamp": "2026-10-08T12:02:00.000Z",
        "producer": "waveform",
        "correlation_id": uploaded["event_id"],
        "payload": {"points": 1000, "duration_ms": 213000},
    }
    # SongUploaded creates the record; the processing results derive readiness.
    await handler(make_message(uploaded), QUEUE_SONG_UPLOADED)
    await handler(make_message(lyrics_processed), QUEUE_PROCESSING_RESULTS)
    await handler(make_message(waveform_processed), QUEUE_PROCESSING_RESULTS)

    published = [event for _, event in publisher.events]
    assert {event["event_type"] for event in published} == {"SongReady"}
    for event in published:
        validator("SongReady").validate(event)
        uuid.UUID(event["event_id"])
        assert event["producer"] == "catalogue"
        assert event["payload"]["song_id"] == uploaded["song_id"]
        assert event["correlation_id"] == uploaded["event_id"]


@pytest.mark.anyio
async def test_invalid_event_is_dead_lettered_without_publishing(
    handler: CatalogueHandler,
    publisher: FakePublisher,
    make_message: Callable[..., FakeMessage],
) -> None:
    message = make_message(b"not json")
    await handler(message, QUEUE_SONG_UPLOADED)

    assert message.outcome == "ack"
    assert publisher.dead_lettered == [(QUEUE_SONG_UPLOADED, b"not json")]
    assert publisher.events == []


def test_the_schemas_reject_unknown_payload_fields() -> None:
    example = json.loads((EVENTS / "examples" / "song-ready.json").read_text("utf-8"))
    example["payload"]["unexpected"] = True

    assert not validator("SongReady").is_valid(example)
