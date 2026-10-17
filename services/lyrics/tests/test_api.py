import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from lyrics_service.shared.db import LyricsRecord, Status


def seed(engine: Engine, status: Status, **fields: Any) -> uuid.UUID:
    song_id = uuid.uuid4()
    now = datetime(2026, 10, 8, 12, 0, 1, 250000, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(
            LyricsRecord(song_id=song_id, status=status, created_at=now, updated_at=now, **fields)
        )
    return song_id


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_lyrics(client: TestClient, api_db: Engine) -> None:
    lines = [{"time_ms": 1000, "text": "Hello"}, {"time_ms": 2500, "text": ""}]
    song_id = seed(api_db, Status.READY, lines=lines, line_count=2)

    response = client.get(f"/songs/{song_id}/lyrics")

    assert response.status_code == 200
    assert response.json() == {
        "song_id": str(song_id),
        "status": "READY",
        "line_count": 2,
        "lines": lines,
        "updated_at": "2026-10-08T12:00:01.250000Z",
    }


def test_processing_lyrics_have_no_lines_yet(client: TestClient, api_db: Engine) -> None:
    song_id = seed(api_db, Status.PROCESSING, line_count=0)

    body = client.get(f"/songs/{song_id}/lyrics").json()

    assert body["status"] == "PROCESSING"
    assert body["lines"] == []
    assert "error" not in body


def test_failed_lyrics_include_the_error(client: TestClient, api_db: Engine) -> None:
    song_id = seed(
        api_db,
        Status.FAILED,
        line_count=0,
        error_code="LYRICS_NOT_TIMESTAMPED",
        error_message="the lyrics file has no [mm:ss.xx] time tags",
    )

    body = client.get(f"/songs/{song_id}/lyrics").json()

    assert body["status"] == "FAILED"
    assert body["lines"] == []
    assert body["error"] == {
        "code": "LYRICS_NOT_TIMESTAMPED",
        "message": "the lyrics file has no [mm:ss.xx] time tags",
    }


def test_unknown_song_is_404(client: TestClient) -> None:
    response = client.get(f"/songs/{uuid.uuid4()}/lyrics")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "LYRICS_NOT_FOUND"


def test_song_id_must_be_a_uuid(client: TestClient) -> None:
    response = client.get("/songs/not-a-uuid/lyrics")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_path_uses_the_shared_error_shape(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
