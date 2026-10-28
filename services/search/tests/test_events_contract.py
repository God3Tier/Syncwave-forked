"""Contract tests: the events Search consumes match the shared schemas."""

import json
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from search_service.shared.events import parse_song_ready

EVENTS = Path(__file__).resolve().parents[3] / "contracts" / "events"
SCHEMA_FILES = {"SongReady": "song-ready.schema.json"}

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


def test_the_song_ready_example_is_understood() -> None:
    example = (EVENTS / "examples" / "song-ready.json").read_bytes()
    event = parse_song_ready(example)
    assert str(event.song_id) == "0b6c2f4e-8d3a-4f7b-b1e2-9c5d7a3e1f20"


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
