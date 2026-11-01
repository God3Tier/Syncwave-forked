import json
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from upload_service.main import app
from upload_service.publisher import dispatch_one

from .conftest import FakePublisher, run

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


def test_produced_events_follow_shared_schema(client: TestClient, wav: bytes) -> None:
    schemas = [
        json.loads(path.read_text("utf-8")) for path in (CONTRACTS / "events").glob("*.schema.json")
    ]
    registry = Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )
    schema = json.loads((CONTRACTS / "events/song-uploaded.schema.json").read_text("utf-8"))
    validator = Draft202012Validator(
        schema, registry=registry, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    publisher = FakePublisher()
    for with_lyrics in (False, True):
        files = {"audio": ("song.wav", wav)}
        data = {"title": "T", "artist": "A"}
        if with_lyrics:
            files["lyrics"] = ("song.lrc", b"[00:01.00]Hello")
            data["mood"] = "calm"
        assert client.post("/uploads", data=data, files=files).status_code == 202
        assert run(client, dispatch_one, app.state.database.sessions, publisher)
    for event in publisher.events:
        validator.validate(event)
