import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update
from sqlalchemy.exc import SQLAlchemyError

from upload_service.backfill import backfill_hashes
from upload_service.db import Status, UploadRecord, now
from upload_service.main import app
from upload_service.publisher import dispatch_one

from .conftest import FakePublisher, FakeStorage, run


def submit(
    client: TestClient,
    wav: bytes,
    *,
    lyrics: bool = False,
    title: str = "  Test Song  ",
    artist: str = " Artist ",
):
    files = {"audio": ("../../my song.wav", wav, "audio/wav")}
    if lyrics:
        files["lyrics"] = ("song.lrc", b"[00:00.01]Hello", "text/plain")
    return client.post(
        "/uploads",
        data={"title": title, "artist": artist},
        files=files,
    )


def test_upload_stores_media_then_publishes_committed_event(
    client: TestClient, storage: FakeStorage, wav: bytes
) -> None:
    response = submit(client, wav, lyrics=True)
    assert response.status_code == 202, response.text
    receipt = response.json()
    song_id = receipt["song_id"]
    assert uuid.UUID(song_id).version == 4
    assert receipt["status"] == "PENDING"
    assert receipt["title"] == "Test Song"
    assert receipt["artist"] == "Artist"
    assert receipt["audio_reference"] == f"audio/{song_id}.wav"
    assert storage.objects[receipt["audio_reference"]] == wav
    assert storage.objects[receipt["lyrics_reference"]] == b"[00:00.01]Hello"
    assert response.headers["location"] == f"/api/upload/uploads/{song_id}"
    publisher = FakePublisher()
    assert run(client, dispatch_one, app.state.database.sessions, publisher)
    event = publisher.events[0]
    assert event["song_id"] == song_id
    assert event["event_id"] == receipt["event_id"]
    assert event["payload"]["title"] == "Test Song"
    assert event["payload"]["artist"] == "Artist"
    assert event["payload"]["audio_reference"] in storage.objects
    assert event["payload"]["lyrics_reference"] in storage.objects
    published = client.get(f"/uploads/{song_id}").json()
    assert published["status"] == "PUBLISHED"
    assert published["publish_attempts"] == 1
    assert published["published_at"] is not None
    assert not run(client, dispatch_one, app.state.database.sessions, publisher)


def test_upload_requires_a_signed_in_account(
    client: TestClient, storage: FakeStorage, wav: bytes
) -> None:
    client.cookies.clear()
    response = submit(client, wav)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "HTTP_ERROR"
    assert response.json()["error"]["message"] == "Sign in to upload music"
    assert not storage.objects


def test_upload_retains_uploader_in_receipt_and_event(client: TestClient, wav: bytes) -> None:
    uploader_id = "00000000-0000-4000-8000-000000000001"
    receipt = submit(client, wav).json()
    assert receipt["uploader_id"] == uploader_id
    assert len(receipt["content_sha256"]) == 64
    assert receipt["duplicate"] is False

    publisher = FakePublisher()
    assert run(client, dispatch_one, app.state.database.sessions, publisher)
    assert publisher.events[0]["payload"]["uploader_id"] == uploader_id


def test_exact_duplicate_returns_canonical_without_second_object_or_event(
    client: TestClient, storage: FakeStorage, wav: bytes
) -> None:
    owner = "00000000-0000-4000-8000-000000000001"
    first = submit(client, wav).json()
    client.cookies.set("syncwave_session", "second-account-token")
    duplicate = submit(
        client,
        wav,
        title="Different title",
        artist="Different artist",
    )

    assert duplicate.status_code == 200
    body = duplicate.json()
    assert body["duplicate"] is True
    assert body["song_id"] == first["song_id"]
    assert body["title"] == first["title"]
    assert body["artist"] == first["artist"]
    assert body["uploader_id"] == owner
    assert list(storage.objects) == [first["audio_reference"]]

    publisher = FakePublisher()
    assert run(client, dispatch_one, app.state.database.sessions, publisher)
    assert len(publisher.events) == 1
    assert not run(client, dispatch_one, app.state.database.sessions, publisher)


def test_concurrent_duplicates_share_one_canonical_upload(
    client: TestClient, storage: FakeStorage, wav: bytes
) -> None:
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: submit(client, wav), range(2)))

    assert sorted(response.status_code for response in responses) == [200, 202]
    bodies = [response.json() for response in responses]
    assert len({body["song_id"] for body in bodies}) == 1
    assert sorted(body["duplicate"] for body in bodies) == [False, True]
    assert len(storage.objects) == 1


def test_hash_backfill_keeps_oldest_canonical_and_is_idempotent(
    client: TestClient, storage: FakeStorage, wav: bytes
) -> None:
    submit(client, wav)
    second = submit(client, wav + b"\x00").json()
    storage.objects[second["audio_reference"]] = wav

    async def make_legacy_rows() -> None:
        async with app.state.database.sessions.begin() as session:
            await session.execute(
                update(UploadRecord).values(
                    status=Status.PUBLISHED,
                    content_sha256=None,
                )
            )

    run(client, make_legacy_rows)
    assert run(client, backfill_hashes, app.state.database.sessions, storage) == (1, 1)

    async def hashes() -> list[str | None]:
        async with app.state.database.sessions() as session:
            rows = (
                await session.scalars(select(UploadRecord).order_by(UploadRecord.created_at))
            ).all()
            return [row.content_sha256 for row in rows]

    first_pass = run(client, hashes)
    assert len([digest for digest in first_pass if digest is not None]) == 1
    assert run(client, backfill_hashes, app.state.database.sessions, storage) == (0, 1)
    assert run(client, hashes) == first_pass


def test_instrumental_and_optional_duration(client: TestClient, wav: bytes) -> None:
    response = client.post(
        "/uploads",
        data={"title": "Instrumental", "artist": "A", "duration_ms": "1000"},
        files={"audio": ("song.wav", wav, "audio/wav")},
    )
    assert response.status_code == 202
    assert response.json()["lyrics_reference"] is None
    assert response.json()["duration_ms"] == 1000


@pytest.mark.parametrize(("sent", "stored"), [(" Calm ", "calm"), ("  ", None), (None, None)])
def test_optional_mood_is_normalised_and_published(
    client: TestClient, wav: bytes, sent: str | None, stored: str | None
) -> None:
    data = {"title": "T", "artist": "A"}
    if sent is not None:
        data["mood"] = sent
    response = client.post("/uploads", data=data, files={"audio": ("song.wav", wav)})
    assert response.status_code == 202, response.text
    assert response.json()["mood"] == stored
    publisher = FakePublisher()
    assert run(client, dispatch_one, app.state.database.sessions, publisher)
    assert publisher.events[0]["payload"].get("mood") == stored
    assert ("mood" in publisher.events[0]["payload"]) == (stored is not None)


def test_broker_outage_retries_same_event_after_restart(client: TestClient, wav: bytes) -> None:
    receipt = submit(client, wav).json()
    publisher = FakePublisher(fail=True)
    assert run(client, dispatch_one, app.state.database.sessions, publisher)
    pending = client.get(f"/uploads/{receipt['song_id']}").json()
    assert pending["status"] == "PENDING"
    assert pending["last_error_code"] == "PUBLISH_RETRYING"
    assert pending["publish_attempts"] == 1
    assert not run(client, dispatch_one, app.state.database.sessions, publisher)

    async def due():
        async with app.state.database.sessions.begin() as session:
            await session.execute(update(UploadRecord).values(next_attempt_at=now()))

    run(client, due)
    # A new lifespan/Database simulates restarting the service, not an in-memory queue.
    with TestClient(app) as restarted:
        recovered = restarted.get(f"/uploads/{receipt['song_id']}").json()
        assert recovered["event_id"] == receipt["event_id"]
        publisher.fail = False
        assert run(restarted, dispatch_one, app.state.database.sessions, publisher)
        assert restarted.get(f"/uploads/{receipt['song_id']}").json()["status"] == "PUBLISHED"
    assert publisher.events[0]["event_id"] == receipt["event_id"]


def test_worker_crash_after_send_replays_the_same_event(client: TestClient, wav: bytes) -> None:
    receipt = submit(client, wav).json()
    publisher = FakePublisher()

    class InterruptedPublisher:
        async def publish(self, event):
            await publisher.publish(event)
            raise asyncio.CancelledError()

    async def interrupted_dispatch():
        try:
            await dispatch_one(app.state.database.sessions, InterruptedPublisher())
        except asyncio.CancelledError:
            pass

    run(client, interrupted_dispatch)
    assert client.get(f"/uploads/{receipt['song_id']}").json()["status"] == "PENDING"
    assert run(client, dispatch_one, app.state.database.sessions, publisher)
    assert len(publisher.events) == 2
    assert publisher.events[0] == publisher.events[1]


def test_database_failure_after_s3_preserves_media_without_publishing(
    client: TestClient, storage: FakeStorage, wav: bytes
) -> None:
    def fail_update(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("UPDATE uploads"):
            raise SQLAlchemyError("simulated failed outbox write")

    engine = app.state.database.engine.sync_engine
    event.listen(engine, "before_cursor_execute", fail_update)
    try:
        response = submit(client, wav)
    finally:
        event.remove(engine, "before_cursor_execute", fail_update)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert len(storage.objects) == 1
    assert not run(client, dispatch_one, app.state.database.sessions, FakePublisher())


@pytest.mark.parametrize("extension", [".wav", ".lrc"])
def test_storage_failure_cleans_objects_and_never_queues_event(
    client: TestClient, storage: FakeStorage, wav: bytes, extension: str
) -> None:
    storage.fail_extension = extension
    response = submit(client, wav, lyrics=True)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert not storage.objects

    async def failed_record():
        async with app.state.database.sessions() as session:
            return await session.scalar(select(UploadRecord))

    record = run(client, failed_record)
    assert record.status == Status.FAILED
    assert record.event is None
    assert record.content_sha256 is None
    assert client.get(f"/uploads/{record.song_id}").json()["status"] == "FAILED"
    assert not run(client, dispatch_one, app.state.database.sessions, FakePublisher())

    storage.fail_extension = None
    retry = submit(client, wav, lyrics=True)
    assert retry.status_code == 202
    assert retry.json()["duplicate"] is False


@pytest.mark.parametrize(
    ("name", "body", "expected", "code"),
    [
        ("song.exe", b"anything", 415, "UNSUPPORTED_FILE_TYPE"),
        ("song.wav", b"", 400, "EMPTY_FILE"),
        ("song.wav", b"not wave", 415, "INVALID_AUDIO"),
        ("song.wav", b"x" * 4097, 413, "FILE_TOO_LARGE"),
    ],
)
def test_rejects_invalid_audio_without_writing(
    client: TestClient, storage: FakeStorage, name: str, body: bytes, expected: int, code: str
) -> None:
    response = client.post(
        "/uploads",
        data={"title": "T", "artist": "A"},
        files={"audio": (name, body, "application/octet-stream")},
    )
    assert response.status_code == expected
    assert response.json()["error"]["code"] == code
    assert not storage.objects


@pytest.mark.parametrize(
    "data",
    [
        {"title": " ", "artist": "A"},
        {"title": "T"},
        {"title": "T", "artist": "A", "duration_ms": "-1"},
        {"title": "T", "artist": "A", "duration_ms": "1.2"},
        {"title": "T", "artist": "A", "duration_ms": "2147483648"},
        {"title": "T\x00", "artist": "A"},
        {"title": "x" * 201, "artist": "A"},
        {"title": "T", "artist": "A", "mood": "x" * 65},
        {"title": "T", "artist": "A", "mood": "calm\x00"},
    ],
)
def test_rejects_invalid_metadata(client: TestClient, storage: FakeStorage, wav: bytes, data):
    response = client.post("/uploads", data=data, files={"audio": ("song.wav", wav)})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert not storage.objects


@pytest.mark.parametrize(
    ("name", "body", "status"),
    [
        ("song.txt", b"hello", 415),
        ("song.lrc", b"\xff", 400),
        ("song.lrc", b"x" * 257, 413),
        ("song.lrc", b"", 400),
    ],
)
def test_rejects_invalid_lyrics_before_uploading_audio(
    client: TestClient, storage: FakeStorage, wav: bytes, name, body, status
):
    response = client.post(
        "/uploads",
        data={"title": "T", "artist": "A"},
        files={"audio": ("song.wav", wav), "lyrics": (name, body)},
    )
    assert response.status_code == status
    assert not storage.objects


def test_health_readiness_and_missing_receipt(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").status_code == 200
    assert client.get(f"/uploads/{uuid.uuid4()}").status_code == 404
    assert client.get("/uploads/not-a-uuid").status_code == 400
    assert client.post("/uploads", data={"title": "T", "artist": "A"}).status_code == 400


def test_location_works_with_gateway_prefix(client: TestClient, wav: bytes) -> None:
    response = submit(client, wav)
    assert client.get(response.headers["location"]).status_code == 200
