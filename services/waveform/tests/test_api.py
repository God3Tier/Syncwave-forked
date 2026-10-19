import base64
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from waveform_service.shared.db import Status, WaveformRecord

PEAKS = [0.1, 0.9, 0.2, 0.3, 0.8, 0.0]
EDGES = [50.0, 400.0, 3200.0, 11025.0]
LEVELS = bytes([0, 10, 20, 255, 128, 64, 30, 40, 50, 1, 2, 3])  # 4 frames of 3 bands


def seed(engine: Engine, status: Status, **fields: Any) -> uuid.UUID:
    song_id = uuid.uuid4()
    now = datetime(2026, 10, 8, 12, 0, 3, 500000, tzinfo=UTC)
    with Session(engine) as session, session.begin():
        session.add(
            WaveformRecord(song_id=song_id, status=status, created_at=now, updated_at=now, **fields)
        )
    return song_id


def seed_ready(engine: Engine) -> uuid.UUID:
    return seed(
        engine,
        Status.READY,
        peaks=PEAKS,
        points=6,
        duration_ms=215040,
        sample_rate=22050,
        bands=LEVELS,
        band_edges_hz=EDGES,
        band_frame_rate=25.0,
    )


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_waveform(client: TestClient, api_db: Engine) -> None:
    song_id = seed_ready(api_db)

    response = client.get(f"/songs/{song_id}/waveform")

    assert response.status_code == 200
    assert response.json() == {
        "song_id": str(song_id),
        "status": "READY",
        "points": 6,
        "duration_ms": 215040,
        "peaks": PEAKS,
        "updated_at": "2026-10-08T12:00:03.500000Z",
    }


def test_points_downsamples_for_a_narrower_display(client: TestClient, api_db: Engine) -> None:
    song_id = seed_ready(api_db)

    body = client.get(f"/songs/{song_id}/waveform", params={"points": 3}).json()

    assert body["points"] == 3
    assert body["peaks"] == [0.9, 0.3, 0.8]


def test_points_above_the_stored_count_returns_every_peak(
    client: TestClient, api_db: Engine
) -> None:
    song_id = seed_ready(api_db)

    body = client.get(f"/songs/{song_id}/waveform", params={"points": 5000}).json()

    assert body["peaks"] == PEAKS


def test_points_must_be_a_positive_integer(client: TestClient, api_db: Engine) -> None:
    song_id = seed_ready(api_db)

    for points in ("0", "-1", "wide"):
        response = client.get(f"/songs/{song_id}/waveform", params={"points": points})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_processing_waveform_has_no_peaks_yet(client: TestClient, api_db: Engine) -> None:
    song_id = seed(api_db, Status.PROCESSING, points=0)

    body = client.get(f"/songs/{song_id}/waveform").json()

    assert body["status"] == "PROCESSING"
    assert body["peaks"] == []
    assert body["points"] == 0
    assert body["duration_ms"] is None
    assert "error" not in body


def test_failed_waveform_includes_the_error(client: TestClient, api_db: Engine) -> None:
    song_id = seed(
        api_db,
        Status.FAILED,
        points=0,
        error_code="AUDIO_UNDECODABLE",
        error_message="ffmpeg could not decode the audio",
    )

    body = client.get(f"/songs/{song_id}/waveform").json()

    assert body["status"] == "FAILED"
    assert body["peaks"] == []
    assert body["error"] == {
        "code": "AUDIO_UNDECODABLE",
        "message": "ffmpeg could not decode the audio",
    }


def test_unknown_song_is_404(client: TestClient) -> None:
    response = client.get(f"/songs/{uuid.uuid4()}/waveform")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WAVEFORM_NOT_FOUND"


def test_song_id_must_be_a_uuid(client: TestClient) -> None:
    response = client.get("/songs/not-a-uuid/waveform")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_unknown_path_uses_the_shared_error_shape(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_ready_bands(client: TestClient, api_db: Engine) -> None:
    song_id = seed_ready(api_db)

    response = client.get(f"/songs/{song_id}/waveform/bands")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "song_id": str(song_id),
        "status": "READY",
        "frame_rate": 25.0,
        "frame_count": 4,
        "band_count": 3,
        "band_edges_hz": EDGES,
        "levels": base64.b64encode(LEVELS).decode(),
        "updated_at": "2026-10-08T12:00:03.500000Z",
    }
    assert base64.b64decode(body["levels"]) == LEVELS


def test_the_waveform_response_leaves_the_bands_out(client: TestClient, api_db: Engine) -> None:
    song_id = seed_ready(api_db)

    body = client.get(f"/songs/{song_id}/waveform").json()

    assert body["peaks"] == PEAKS
    assert not {"levels", "band_edges_hz", "frame_rate"} & body.keys()


def test_processing_song_has_no_bands_yet(client: TestClient, api_db: Engine) -> None:
    song_id = seed(api_db, Status.PROCESSING, points=0)

    body = client.get(f"/songs/{song_id}/waveform/bands").json()

    assert body["status"] == "PROCESSING"
    assert (body["frame_rate"], body["frame_count"], body["band_count"]) == (None, 0, 0)
    assert (body["band_edges_hz"], body["levels"]) == ([], "")
    assert "error" not in body


def test_failed_song_bands_include_the_error(client: TestClient, api_db: Engine) -> None:
    song_id = seed(
        api_db, Status.FAILED, points=0, error_code="AUDIO_EMPTY", error_message="no samples"
    )

    body = client.get(f"/songs/{song_id}/waveform/bands").json()

    assert body["status"] == "FAILED"
    assert body["levels"] == ""
    assert body["error"] == {"code": "AUDIO_EMPTY", "message": "no samples"}


def test_bands_of_an_unknown_song_is_404(client: TestClient) -> None:
    response = client.get(f"/songs/{uuid.uuid4()}/waveform/bands")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "WAVEFORM_NOT_FOUND"
