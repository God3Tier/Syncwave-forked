"""Contract tests: the events this service consumes and publishes match the
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

from lyrics_service.shared.events import parse_song_uploaded
from lyrics_service.worker.handler import LyricsHandler

from .conftest import FakeMessage, FakePublisher, FakeStorage

EVENTS = Path(__file__).resolve().parents[3] / "contracts" / "events"
SCHEMA_FILES = {
    "SongUploaded": "song-uploaded.schema.json",
    "LyricsProcessed": "lyrics-processed.schema.json",
    "LyricsProcessingFailed": "lyrics-processing-failed.schema.json",
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

    assert event.lyrics_reference == "lyrics/0b6c2f4e-8d3a-4f7b-b1e2-9c5d7a3e1f20.lrc"


@pytest.mark.parametrize("lyrics_reference", ["", None])
def test_test_events_follow_the_song_uploaded_schema(
    song_uploaded: Callable[..., dict[str, Any]], lyrics_reference: str | None
) -> None:
    validator("SongUploaded").validate(song_uploaded(lyrics_reference=lyrics_reference))


@pytest.mark.anyio
async def test_every_published_event_matches_its_schema(
    handler: LyricsHandler,
    storage: FakeStorage,
    publisher: FakePublisher,
    song_uploaded: Callable[..., dict[str, Any]],
    make_message: Callable[..., FakeMessage],
) -> None:
    ready = song_uploaded()
    storage.objects[ready["payload"]["lyrics_reference"]] = b"[00:01.00]Hello"
    invalid = song_uploaded()
    storage.objects[invalid["payload"]["lyrics_reference"]] = b"no time tags"
    wrong_type = dict(song_uploaded(), event_type="Unexpected")
    for event in (ready, song_uploaded(lyrics_reference=None), invalid, wrong_type):
        await handler(make_message(event))
    await handler(make_message(song_uploaded(), failures=2))  # gives up: file missing

    published = [event for _, event in publisher.events]
    assert {event["event_type"] for event in published} == {
        "LyricsProcessed",
        "LyricsProcessingFailed",
    }
    for event in published:
        validator(event["event_type"]).validate(event)
        uuid.UUID(event["event_id"])


def test_the_schemas_reject_unknown_payload_fields() -> None:
    example = json.loads((EVENTS / "examples" / "lyrics-processed.json").read_text("utf-8"))
    example["payload"]["unexpected"] = True

    assert not validator("LyricsProcessed").is_valid(example)
