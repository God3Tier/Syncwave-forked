import time
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from sync_service.dependencies import (
    FakeCatalogueClient,
    FakeStreamingClient,
    SongProcessingStatus,
)
from sync_service.main import app, dependencies, manager
from sync_service.models import PlaybackState

INTERNAL_HEADERS = {"X-Internal-Token": "local-jam-to-sync-token"}
PARTICIPANT_TOKEN = "local-sync-participant-token"


def activate(client: TestClient, participant_count: int = 1) -> dict[str, str | list[str]]:
    participant_ids = [str(uuid4()) for _ in range(participant_count)]
    body = {
        "request_id": str(uuid4()),
        "jam_id": str(uuid4()),
        "queue_item_id": str(uuid4()),
        "song_id": str(uuid4()),
        "owner_id": participant_ids[0],
        "participant_ids": participant_ids,
    }
    response = client.post("/internal/v1/sessions", headers=INTERNAL_HEADERS, json=body)
    assert response.status_code == 201
    return body


def receive_handshake(websocket: object) -> tuple[dict[str, object], dict[str, object]]:
    joined = websocket.receive_json()
    prepare = websocket.receive_json()
    assert joined["type"] == "JOINED"
    assert prepare["type"] == "PREPARE"
    return joined, prepare


def test_jam_activation_requires_internal_token(client: TestClient) -> None:
    body = {
        "request_id": str(uuid4()),
        "jam_id": str(uuid4()),
        "queue_item_id": str(uuid4()),
        "song_id": str(uuid4()),
        "owner_id": str(uuid4()),
        "participant_ids": [str(uuid4())],
    }
    assert client.post("/internal/v1/sessions", json=body).status_code == 401


def test_jam_activation_rejects_song_that_is_not_ready(
    client: TestClient,
    monkeypatch: object,
) -> None:
    song_id = uuid4()
    catalogue = dependencies.catalogue
    assert isinstance(catalogue, FakeCatalogueClient)
    monkeypatch.setitem(catalogue.statuses, song_id, SongProcessingStatus.PROCESSING)
    participant_id = uuid4()
    body = {
        "request_id": str(uuid4()),
        "jam_id": str(uuid4()),
        "queue_item_id": str(uuid4()),
        "song_id": str(song_id),
        "owner_id": str(participant_id),
        "participant_ids": [str(participant_id)],
    }

    response = client.post("/internal/v1/sessions", headers=INTERNAL_HEADERS, json=body)

    assert response.status_code == 409
    assert response.json()["detail"] == "song is not ready: processing_status=PROCESSING"
    assert manager.get(UUID(body["jam_id"])) is None


def test_time_ping_returns_four_timestamp_exchange(client: TestClient) -> None:
    session = activate(client)
    jam_id = session["jam_id"]
    participant_id = session["participant_ids"][0]
    path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"

    with client.websocket_connect(path) as websocket:
        joined, prepare = receive_handshake(websocket)
        assert joined["payload"]["generation"] == 1
        assert prepare["payload"]["song_id"] == session["song_id"]

        sample_id = str(uuid4())
        websocket.send_json(
            {
                "type": "TIME_PING",
                "jam_id": jam_id,
                "seq": 0,
                "sent_at_ms": 1_000,
                "payload": {"sample_id": sample_id, "client_sent_ms": 1_000},
            }
        )
        pong = websocket.receive_json()

    assert pong["type"] == "TIME_PONG"
    assert pong["payload"]["sample_id"] == sample_id
    assert pong["payload"]["client_sent_ms"] == 1_000
    assert pong["payload"]["server_received_ms"] <= pong["payload"]["server_sent_ms"]


def test_prepare_uses_dependency_resolved_stream_url(
    client: TestClient,
    monkeypatch: object,
) -> None:
    song_id = uuid4()
    participant_id = uuid4()
    stream_url = f"/api/audio/tracks/{song_id}/audio"
    streaming = dependencies.streaming
    assert isinstance(streaming, FakeStreamingClient)
    monkeypatch.setitem(streaming.stream_urls, song_id, stream_url)
    body = {
        "request_id": str(uuid4()),
        "jam_id": str(uuid4()),
        "queue_item_id": str(uuid4()),
        "song_id": str(song_id),
        "owner_id": str(participant_id),
        "participant_ids": [str(participant_id)],
    }
    assert (
        client.post(
            "/internal/v1/sessions",
            headers=INTERNAL_HEADERS,
            json=body,
        ).status_code
        == 201
    )
    path = f"/ws?jam_id={body['jam_id']}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"

    with client.websocket_connect(path) as websocket:
        _, prepare = receive_handshake(websocket)

    assert prepare["payload"]["stream_url"] == stream_url


def test_stale_sequence_is_rejected(client: TestClient) -> None:
    session = activate(client)
    jam_id = session["jam_id"]
    participant_id = session["participant_ids"][0]
    path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"
    frame = {
        "type": "TIME_PING",
        "jam_id": jam_id,
        "seq": 2,
        "sent_at_ms": 1_000,
        "payload": {"sample_id": str(uuid4()), "client_sent_ms": 1_000},
    }

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        websocket.send_json(frame)
        assert websocket.receive_json()["type"] == "TIME_PONG"
        websocket.send_json(frame)
        error = websocket.receive_json()

    assert error["type"] == "ERROR"
    assert error["payload"]["code"] == "STALE_SEQUENCE"


def test_malformed_json_returns_error_without_closing_connection(client: TestClient) -> None:
    session = activate(client)
    jam_id = session["jam_id"]
    participant_id = session["participant_ids"][0]
    path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        websocket.send_text("not-json")
        error = websocket.receive_json()
        websocket.send_json(
            {
                "type": "TIME_PING",
                "jam_id": jam_id,
                "seq": 0,
                "sent_at_ms": 1_000,
                "payload": {"sample_id": str(uuid4()), "client_sent_ms": 1_000},
            }
        )
        pong = websocket.receive_json()

    assert error["payload"]["code"] == "INVALID_MESSAGE"
    assert pong["type"] == "TIME_PONG"


def test_ready_for_stale_generation_is_rejected(client: TestClient) -> None:
    session = activate(client)
    jam_id = session["jam_id"]
    participant_id = session["participant_ids"][0]
    path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        websocket.send_json(
            {
                "type": "READY",
                "jam_id": jam_id,
                "seq": 0,
                "sent_at_ms": 1_000,
                "payload": {
                    "generation": 99,
                    "buffered_duration_ms": 5_000,
                    "media_duration_ms": 180_000,
                },
            }
        )
        error = websocket.receive_json()

    assert error["payload"]["code"] == "STALE_GENERATION"


def test_all_participants_ready_receive_same_scheduled_start(client: TestClient) -> None:
    session = activate(client, participant_count=2)
    jam_id = session["jam_id"]
    first_id, second_id = session["participant_ids"]
    first_path = f"/ws?jam_id={jam_id}&participant_id={first_id}&token={PARTICIPANT_TOKEN}"
    second_path = f"/ws?jam_id={jam_id}&participant_id={second_id}&token={PARTICIPANT_TOKEN}"

    with (
        client.websocket_connect(first_path) as first,
        client.websocket_connect(second_path) as second,
    ):
        receive_handshake(first)
        receive_handshake(second)

        first.send_json(
            {
                "type": "READY",
                "jam_id": jam_id,
                "seq": 0,
                "sent_at_ms": 1_000,
                "payload": {
                    "generation": 1,
                    "buffered_duration_ms": 5_000,
                    "media_duration_ms": 180_000,
                },
            }
        )
        assert first.receive_json()["type"] == "PARTICIPANT_STATE"
        assert second.receive_json()["type"] == "PARTICIPANT_STATE"

        second.send_json(
            {
                "type": "READY",
                "jam_id": jam_id,
                "seq": 0,
                "sent_at_ms": 1_001,
                "payload": {
                    "generation": 1,
                    "buffered_duration_ms": 5_000,
                    "media_duration_ms": 180_000,
                },
            }
        )
        assert first.receive_json()["type"] == "PARTICIPANT_STATE"
        assert second.receive_json()["type"] == "PARTICIPANT_STATE"
        first_play_at = first.receive_json()
        second_play_at = second.receive_json()

    assert first_play_at["type"] == "PLAY_AT"
    assert second_play_at["type"] == "PLAY_AT"
    assert first_play_at["payload"] == second_play_at["payload"]
    assert first_play_at["payload"]["target_server_time_ms"] > first_play_at["sent_at_ms"]


def test_large_reported_drift_returns_scheduled_seek(client: TestClient) -> None:
    session = activate(client)
    jam_id = session["jam_id"]
    participant_id = session["participant_ids"][0]
    path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        websocket.send_json(
            {
                "type": "READY",
                "jam_id": jam_id,
                "seq": 0,
                "sent_at_ms": 1_000,
                "payload": {
                    "generation": 1,
                    "buffered_duration_ms": 5_000,
                    "media_duration_ms": 180_000,
                },
            }
        )
        assert websocket.receive_json()["type"] == "PARTICIPANT_STATE"
        play_at = websocket.receive_json()
        target_ms = play_at["payload"]["target_server_time_ms"]

        websocket.send_json(
            {
                "type": "PLAYBACK_STATUS",
                "jam_id": jam_id,
                "seq": 1,
                "sent_at_ms": target_ms + 1_000,
                "payload": {
                    "generation": 1,
                    "measured_server_time_ms": target_ms + 1_000,
                    "position_ms": 1_500,
                    "buffering": False,
                },
            }
        )
        correction = websocket.receive_json()

    assert correction["type"] == "SYNC_CORRECTION"
    assert correction["payload"]["method"] == "SEEK"
    assert correction["payload"]["drift_ms"] == 500
    snapshot = client.get(f"/internal/v1/sessions/{jam_id}", headers=INTERNAL_HEADERS)
    assert snapshot.status_code == 200
    assert snapshot.json()["state"] == "PLAYING"


def test_scheduled_timeline_survives_service_restart() -> None:
    with TestClient(app) as first_process:
        session = activate(first_process)
        jam_id = session["jam_id"]
        participant_id = session["participant_ids"][0]
        path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"
        with first_process.websocket_connect(path) as websocket:
            receive_handshake(websocket)
            websocket.send_json(
                {
                    "type": "READY",
                    "jam_id": jam_id,
                    "seq": 0,
                    "sent_at_ms": 1_000,
                    "payload": {
                        "generation": 1,
                        "buffered_duration_ms": 5_000,
                        "media_duration_ms": 180_000,
                    },
                }
            )
            assert websocket.receive_json()["type"] == "PARTICIPANT_STATE"
            play_at = websocket.receive_json()

    with TestClient(app) as restarted_process:
        snapshot = restarted_process.get(
            f"/internal/v1/sessions/{jam_id}",
            headers=INTERNAL_HEADERS,
        )

    assert snapshot.status_code == 200
    assert snapshot.json()["state"] == "SCHEDULED"
    assert snapshot.json()["anchor_server_time_ms"] == play_at["payload"]["target_server_time_ms"]


def test_reconnect_receives_existing_schedule_and_can_restart_sequence(client: TestClient) -> None:
    session = activate(client)
    jam_id = session["jam_id"]
    participant_id = session["participant_ids"][0]
    path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        websocket.send_json(
            {
                "type": "READY",
                "jam_id": jam_id,
                "seq": 8,
                "sent_at_ms": 1_000,
                "payload": {
                    "generation": 1,
                    "buffered_duration_ms": 5_000,
                    "media_duration_ms": 180_000,
                },
            }
        )
        assert websocket.receive_json()["type"] == "PARTICIPANT_STATE"
        original_play_at = websocket.receive_json()

    with client.websocket_connect(path) as reconnected:
        joined = reconnected.receive_json()
        replayed_play_at = reconnected.receive_json()
        reconnected.send_json(
            {
                "type": "TIME_PING",
                "jam_id": jam_id,
                "seq": 0,
                "sent_at_ms": 2_000,
                "payload": {"sample_id": str(uuid4()), "client_sent_ms": 2_000},
            }
        )
        pong = reconnected.receive_json()

    assert joined["payload"]["state"] == "SCHEDULED"
    assert replayed_play_at["type"] == "PLAY_AT"
    assert replayed_play_at["payload"] == original_play_at["payload"]
    assert pong["type"] == "TIME_PONG"


def test_late_joiner_receives_future_catch_up_position(client: TestClient) -> None:
    session = activate(client)
    jam_id = session["jam_id"]
    participant_id = session["participant_ids"][0]
    active_session = manager.get(UUID(jam_id))
    assert active_session is not None
    active_session.state = PlaybackState.PLAYING
    active_session.anchor_server_time_ms = time.time_ns() // 1_000_000 - 5_000
    path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"

    with client.websocket_connect(path) as websocket:
        joined = websocket.receive_json()
        catch_up = websocket.receive_json()

    assert joined["payload"]["state"] == "PLAYING"
    assert catch_up["type"] == "PLAY_AT"
    assert catch_up["payload"]["target_server_time_ms"] > catch_up["sent_at_ms"]
    assert catch_up["payload"]["start_position_ms"] >= 5_000


def test_jam_can_continue_without_unready_participant(client: TestClient) -> None:
    session = activate(client, participant_count=2)
    jam_id = session["jam_id"]
    ready_id, unready_id = session["participant_ids"]
    path = f"/ws?jam_id={jam_id}&participant_id={ready_id}&token={PARTICIPANT_TOKEN}"

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        websocket.send_json(
            {
                "type": "READY",
                "jam_id": jam_id,
                "seq": 0,
                "sent_at_ms": 1_000,
                "payload": {
                    "generation": 1,
                    "buffered_duration_ms": 5_000,
                    "media_duration_ms": 180_000,
                },
            }
        )
        assert websocket.receive_json()["type"] == "PARTICIPANT_STATE"

        active_session = manager.get(UUID(jam_id))
        assert active_session is not None
        active_session.prepare_deadline_ms = 0
        readiness = client.get(
            f"/internal/v1/sessions/{jam_id}/readiness",
            headers=INTERNAL_HEADERS,
        )
        assert readiness.status_code == 200
        assert readiness.json()["decision_required"] is True
        assert readiness.json()["ready_participant_ids"] == [ready_id]
        assert readiness.json()["unready_participant_ids"] == [unready_id]

        decision = client.post(
            f"/internal/v1/sessions/{jam_id}/readiness-decision",
            headers=INTERNAL_HEADERS,
            json={
                "request_id": str(uuid4()),
                "generation": 1,
                "decision": "CONTINUE",
            },
        )
        play_at = websocket.receive_json()

    assert decision.status_code == 200
    assert decision.json()["state"] == "SCHEDULED"
    assert play_at["type"] == "PLAY_AT"


def test_jam_can_wait_then_cancel_after_timeout(client: TestClient) -> None:
    session = activate(client, participant_count=2)
    jam_id = session["jam_id"]
    active_session = manager.get(UUID(jam_id))
    assert active_session is not None
    active_session.prepare_deadline_ms = 0

    wait_response = client.post(
        f"/internal/v1/sessions/{jam_id}/readiness-decision",
        headers=INTERNAL_HEADERS,
        json={
            "request_id": str(uuid4()),
            "generation": 1,
            "decision": "WAIT",
        },
    )
    assert wait_response.status_code == 200
    assert wait_response.json()["state"] == "PREPARING"
    assert active_session.prepare_deadline_ms > 0

    active_session.prepare_deadline_ms = 0
    cancel_response = client.post(
        f"/internal/v1/sessions/{jam_id}/readiness-decision",
        headers=INTERNAL_HEADERS,
        json={
            "request_id": str(uuid4()),
            "generation": 1,
            "decision": "CANCEL",
        },
    )
    assert cancel_response.status_code == 200
    assert cancel_response.json()["state"] == "ENDED"


def test_jam_controls_pause_resume_seek_and_skip(client: TestClient) -> None:
    session = activate(client)
    jam_id = session["jam_id"]
    participant_id = session["participant_ids"][0]
    path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token={PARTICIPANT_TOKEN}"

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        websocket.send_json(
            {
                "type": "READY",
                "jam_id": jam_id,
                "seq": 0,
                "sent_at_ms": 1_000,
                "payload": {
                    "generation": 1,
                    "buffered_duration_ms": 5_000,
                    "media_duration_ms": 180_000,
                },
            }
        )
        assert websocket.receive_json()["type"] == "PARTICIPANT_STATE"
        assert websocket.receive_json()["type"] == "PLAY_AT"

        pause_request_id = str(uuid4())
        pause = client.post(
            f"/internal/v1/sessions/{jam_id}/pause",
            headers=INTERNAL_HEADERS,
            json={"request_id": pause_request_id, "generation": 1},
        )
        pause_at = websocket.receive_json()
        duplicate_pause = client.post(
            f"/internal/v1/sessions/{jam_id}/pause",
            headers=INTERNAL_HEADERS,
            json={"request_id": pause_request_id, "generation": 1},
        )

        resume = client.post(
            f"/internal/v1/sessions/{jam_id}/resume",
            headers=INTERNAL_HEADERS,
            json={"request_id": str(uuid4()), "generation": 1},
        )
        resume_at = websocket.receive_json()

        seek = client.post(
            f"/internal/v1/sessions/{jam_id}/seek",
            headers=INTERNAL_HEADERS,
            json={
                "request_id": str(uuid4()),
                "generation": 1,
                "position_ms": 42_000,
            },
        )
        seek_to = websocket.receive_json()

        next_queue_item_id = str(uuid4())
        next_song_id = str(uuid4())
        skip = client.post(
            f"/internal/v1/sessions/{jam_id}/skip",
            headers=INTERNAL_HEADERS,
            json={
                "request_id": str(uuid4()),
                "generation": 1,
                "queue_item_id": next_queue_item_id,
                "song_id": next_song_id,
            },
        )
        next_prepare = websocket.receive_json()

    assert pause.status_code == 200
    assert pause.json()["state"] == "PAUSED"
    assert pause_at["type"] == "PAUSE_AT"
    assert duplicate_pause.status_code == 200
    assert duplicate_pause.json() == pause.json()
    assert resume.status_code == 200
    assert resume.json()["state"] == "SCHEDULED"
    assert resume_at["type"] == "RESUME_AT"
    assert seek.status_code == 200
    assert seek.json()["anchor_position_ms"] == 42_000
    assert seek_to["type"] == "SEEK_TO"
    assert seek_to["payload"]["resume_playback"] is True
    assert skip.status_code == 200
    assert skip.json()["generation"] == 2
    assert skip.json()["state"] == "PREPARING"
    assert skip.json()["song_id"] == next_song_id
    assert next_prepare["type"] == "PREPARE"
    assert next_prepare["payload"]["generation"] == 2


def test_jam_control_rejects_stale_generation_and_missing_auth(client: TestClient) -> None:
    session = activate(client)
    jam_id = session["jam_id"]
    body = {"request_id": str(uuid4()), "generation": 99}

    unauthorized = client.post(f"/internal/v1/sessions/{jam_id}/pause", json=body)
    stale = client.post(
        f"/internal/v1/sessions/{jam_id}/pause",
        headers=INTERNAL_HEADERS,
        json=body,
    )

    assert unauthorized.status_code == 401
    assert stale.status_code == 409
    assert stale.json()["detail"] == "stale generation"
