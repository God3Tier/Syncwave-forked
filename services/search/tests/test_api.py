import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from search_service.shared.db import SearchRecord


def seed(engine: Engine, *, title: str = "Demo", artist: str = "Artist") -> uuid.UUID:
    song_id = uuid.uuid4()
    now = datetime(2026, 10, 8, 12, 0, 1, 250000, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(SearchRecord(song_id=song_id, title=title, artist=artist, indexed_at=now))
    return song_id


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_search_matches_title(client: TestClient, api_db: Engine) -> None:
    sid = seed(api_db, title="Hello World", artist="Someone")
    body = client.get("/search?q=hello").json()
    assert {item["song_id"] for item in body["items"]} == {str(sid)}
    assert body["items"][0]["title"] == "Hello World"


def test_search_matches_artist(client: TestClient, api_db: Engine) -> None:
    sid = seed(api_db, title="Track", artist="The Beatles")
    body = client.get("/search?q=beatles").json()
    assert {item["song_id"] for item in body["items"]} == {str(sid)}


def test_search_case_insensitive(client: TestClient, api_db: Engine) -> None:
    sid = seed(api_db, title="Demo", artist="Artist")
    body = client.get("/search?q=DEMO").json()
    assert {item["song_id"] for item in body["items"]} == {str(sid)}


def test_search_no_match(client: TestClient, api_db: Engine) -> None:
    seed(api_db, title="Demo", artist="Artist")
    body = client.get("/search?q=zzzzz").json()
    assert body["items"] == []
    assert body["next_cursor"] is None


def test_search_empty_q_returns_all(client: TestClient, api_db: Engine) -> None:
    ids = [seed(api_db) for _ in range(3)]
    body = client.get("/search").json()
    assert {item["song_id"] for item in body["items"]} == {str(i) for i in ids}


def test_search_limit_and_cursor(client: TestClient, api_db: Engine) -> None:
    for _ in range(3):
        seed(api_db)
    first = client.get("/search?limit=1").json()
    assert len(first["items"]) == 1
    assert first["next_cursor"] is not None
    second = client.get(f"/search?limit=1&cursor={first['next_cursor']}").json()
    assert len(second["items"]) == 1
    assert second["items"][0]["song_id"] != first["items"][0]["song_id"]


def test_search_invalid_limit(client: TestClient) -> None:
    response = client.get("/search?limit=0")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_search_invalid_cursor(client: TestClient) -> None:
    response = client.get("/search?cursor=not-a-cursor")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_CURSOR"
