import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from catalogue_service.shared.db import ProcessingStatus, SongRecord, StageStatus


def seed(
    engine: Engine,
    *,
    processing_status: ProcessingStatus = ProcessingStatus.READY,
    lyrics_status: StageStatus = StageStatus.READY,
    waveform_status: StageStatus = StageStatus.READY,
    duration_ms: int | None = None,
    **fields: Any,
) -> uuid.UUID:
    song_id = uuid.uuid4()
    now = datetime(2026, 10, 8, 12, 0, 1, 250000, tzinfo=UTC)
    data = dict(
        title="Demo",
        artist="Artist",
        audio_reference=f"audio/{song_id}.mp3",
        lyrics_status=lyrics_status.value,
        waveform_status=waveform_status.value,
        processing_status=processing_status.value,
    )
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    data.update(fields)
    with Session(engine) as session, session.begin():
        session.add(SongRecord(song_id=song_id, created_at=now, updated_at=now, **data))
    return song_id


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_song(client: TestClient, api_db: Engine) -> None:
    song_id = seed(api_db, duration_ms=213000)

    response = client.get(f"/songs/{song_id}")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "song_id": str(song_id),
        "title": "Demo",
        "artist": "Artist",
        "duration_ms": 213000,
        "audio_reference": f"audio/{song_id}.mp3",
        "lyrics_status": "READY",
        "waveform_status": "READY",
        "processing_status": "READY",
        "created_at": "2026-10-08T12:00:01.250000Z",
        "updated_at": "2026-10-08T12:00:01.250000Z",
    }


def test_get_song_duration_null_when_unmeasured(client: TestClient, api_db: Engine) -> None:
    song_id = seed(api_db)

    body = client.get(f"/songs/{song_id}").json()
    assert body["duration_ms"] is None


def test_unknown_song_is_404(client: TestClient) -> None:
    response = client.get(f"/songs/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SONG_NOT_FOUND"


def test_song_id_must_be_a_uuid(client: TestClient) -> None:
    response = client.get("/songs/not-a-uuid")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_list_songs_returns_all(client: TestClient, api_db: Engine) -> None:
    ids = [seed(api_db) for _ in range(3)]

    body = client.get("/songs?limit=10").json()
    assert {item["song_id"] for item in body["items"]} == {str(item) for item in ids}
    assert body["next_cursor"] is None


def test_list_songs_limit(client: TestClient, api_db: Engine) -> None:
    seed(api_db)
    seed(api_db)
    seed(api_db)

    body = client.get("/songs?limit=1").json()
    assert len(body["items"]) == 1
    assert body["next_cursor"] is not None


def test_list_songs_cursor(client: TestClient, api_db: Engine) -> None:
    ids = [seed(api_db) for _ in range(3)]

    first = client.get("/songs?limit=1").json()
    assert len(first["items"]) == 1
    assert first["next_cursor"] is not None

    second = client.get(f"/songs?limit=1&cursor={first['next_cursor']}").json()
    assert len(second["items"]) == 1
    assert second["items"][0]["song_id"] != first["items"][0]["song_id"]

    third = client.get(f"/songs?limit=1&cursor={second['next_cursor']}").json()
    assert len(third["items"]) == 1
    assert third["next_cursor"] is None

    seen = {
        first["items"][0]["song_id"],
        second["items"][0]["song_id"],
        third["items"][0]["song_id"],
    }
    assert seen == {str(item) for item in ids}


def test_list_songs_filter_by_readiness(client: TestClient, api_db: Engine) -> None:
    ready_id = seed(api_db, processing_status=ProcessingStatus.READY)
    partial_id = seed(api_db, processing_status=ProcessingStatus.PARTIAL)

    body = client.get("/songs?processing_status=READY").json()
    song_ids = {item["song_id"] for item in body["items"]}
    assert str(ready_id) in song_ids
    assert str(partial_id) not in song_ids


def test_unknown_path_uses_the_shared_error_shape(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
