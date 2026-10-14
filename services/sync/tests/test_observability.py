import json
import logging
from uuid import uuid4

from fastapi.testclient import TestClient

from sync_service.observability import (
    JsonFormatter,
    bind_correlation_id,
    metrics,
    reset_correlation_id,
)


def test_json_log_includes_correlation_and_required_context() -> None:
    correlation, token = bind_correlation_id("test-correlation-123")
    try:
        record = logging.LogRecord(
            "sync_service",
            logging.INFO,
            __file__,
            1,
            "participant_ready",
            (),
            None,
        )
        record.jam_id = "jam-1"
        record.participant_id = "participant-1"
        record.generation = 3
        record.message_type = "READY"
        record.outcome = "waiting"
        document = json.loads(JsonFormatter().format(record))
    finally:
        reset_correlation_id(token)

    assert correlation == "test-correlation-123"
    assert document["correlation_id"] == correlation
    assert document["jam_id"] == "jam-1"
    assert document["participant_id"] == "participant-1"
    assert document["generation"] == 3
    assert document["message_type"] == "READY"
    assert document["outcome"] == "waiting"


def test_http_correlation_id_is_propagated(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Correlation-ID": "jam-request-42"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] == "jam-request-42"


def test_unsafe_http_correlation_id_is_replaced(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Correlation-ID": "token value\nunsafe"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] != "token value\nunsafe"
    assert len(response.headers["X-Correlation-ID"]) == 32


def test_metrics_endpoint_exposes_protocol_and_dependency_metrics(client: TestClient) -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "sync_websocket_connections" in response.text
    assert "sync_protocol_errors_total" in response.text
    assert "sync_dependency_duration_ms" in response.text


def test_protocol_error_counter_increments(client: TestClient) -> None:
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
    client.post(
        "/internal/v1/sessions",
        headers={"X-Internal-Token": "local-jam-to-sync-token"},
        json=body,
    )
    counter = metrics.protocol_errors_total.labels(code="INVALID_MESSAGE")
    before = counter._value.get()
    path = f"/ws?jam_id={jam_id}&participant_id={participant_id}&token=local-sync-participant-token"

    with client.websocket_connect(path) as websocket:
        websocket.receive_json()
        websocket.receive_json()
        websocket.send_text("not-json")
        assert websocket.receive_json()["type"] == "ERROR"

    assert counter._value.get() == before + 1
