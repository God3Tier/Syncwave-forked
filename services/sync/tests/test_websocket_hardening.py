from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import sync_service.main as main_module

INTERNAL_HEADERS = {"X-Internal-Token": "local-jam-to-sync-token"}


def activate(client: TestClient) -> tuple[str, str, str]:
    participant_id = str(uuid4())
    jam_id = str(uuid4())
    body = {
        "request_id": str(uuid4()),
        "jam_id": jam_id,
        "queue_item_id": str(uuid4()),
        "song_id": str(uuid4()),
        "owner_id": participant_id,
        "participant_ids": [participant_id],
    }
    response = client.post("/internal/v1/sessions", headers=INTERNAL_HEADERS, json=body)
    assert response.status_code == 201
    path = (
        f"/ws?jam_id={jam_id}&participant_id={participant_id}"
        "&token=local-sync-participant-token"
    )
    return jam_id, participant_id, path


def receive_handshake(websocket: object) -> None:
    assert websocket.receive_json()["type"] == "JOINED"
    assert websocket.receive_json()["type"] == "PREPARE"


def ping(jam_id: str, seq: int) -> dict[str, object]:
    return {
        "type": "TIME_PING",
        "jam_id": jam_id,
        "seq": seq,
        "sent_at_ms": 1_000 + seq,
        "payload": {"sample_id": str(uuid4()), "client_sent_ms": 1_000 + seq},
    }


def test_oversized_websocket_message_closes_with_1009(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, path = activate(client)
    configured = replace(main_module.settings, websocket_max_message_bytes=32)
    monkeypatch.setattr(main_module, "get_settings", lambda: configured)

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        websocket.send_text("x" * 33)
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_text()

    assert closed.value.code == 1009


def test_websocket_rate_limit_closes_with_retry_code(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jam_id, _, path = activate(client)
    configured = replace(
        main_module.settings,
        websocket_rate_limit_messages=1,
        websocket_rate_limit_window_ms=60_000,
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: configured)

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        websocket.send_json(ping(jam_id, 0))
        assert websocket.receive_json()["type"] == "TIME_PONG"
        websocket.send_json(ping(jam_id, 1))
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_text()

    assert closed.value.code == 1013


def test_idle_websocket_closes_with_heartbeat_timeout(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, path = activate(client)
    configured = replace(main_module.settings, websocket_idle_timeout_ms=10)
    monkeypatch.setattr(main_module, "get_settings", lambda: configured)

    with client.websocket_connect(path) as websocket:
        receive_handshake(websocket)
        with pytest.raises(WebSocketDisconnect) as closed:
            websocket.receive_text()

    assert closed.value.code == 1001


def test_new_connection_replaces_existing_connection(
    client: TestClient,
) -> None:
    _, _, path = activate(client)

    with client.websocket_connect(path) as first:
        receive_handshake(first)
        with client.websocket_connect(path) as second:
            receive_handshake(second)
            with pytest.raises(WebSocketDisconnect) as closed:
                first.receive_text()

    assert closed.value.code == 4001
