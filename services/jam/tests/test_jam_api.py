from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from jam_service.main import playlist_client, sync_client
from jam_service.models import JamState
from jam_service.sync_client import SyncSnapshot


def create_jam(client: TestClient, owner_id: str) -> dict:
    response = client.post("/jams", json={"owner_id": owner_id})
    assert response.status_code == 201
    return response.json()


def test_health_and_authentication(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "service": "jam"}
    assert client.get("/ready").status_code == 200
    assert TestClient(client.app).post("/jams", json={"owner_id": str(uuid4())}).status_code == 401


def test_create_jam_imports_playlist_in_saved_order(client: TestClient) -> None:
    owner_id = str(uuid4())
    playlist_id = uuid4()
    song_ids = [uuid4(), uuid4(), uuid4()]
    playlist_client.playlists[playlist_id] = song_ids

    response = client.post(
        "/jams",
        json={"owner_id": owner_id, "playlist_id": str(playlist_id)},
    )

    assert response.status_code == 201
    queue = response.json()["queue"]
    assert [item["song_id"] for item in queue] == [str(song_id) for song_id in song_ids]
    assert [item["position"] for item in queue] == [0, 1, 2]
    assert {item["added_by"] for item in queue} == {owner_id}


def test_create_jam_reports_missing_playlist(client: TestClient) -> None:
    response = client.post(
        "/jams",
        json={"owner_id": str(uuid4()), "playlist_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "playlist not found"}


def test_members_can_join_and_queue_but_only_owner_controls(client: TestClient) -> None:
    owner_id = str(uuid4())
    member_id = str(uuid4())
    jam = create_jam(client, owner_id)
    jam_id = jam["jam_id"]
    assert jam["member_token"] == "local-jam-member-token"

    joined = client.post(f"/jams/{jam_id}/members", json={"participant_id": member_id}).json()
    assert joined["participant_ids"] == [owner_id, member_id]

    queued = client.post(
        f"/jams/{jam_id}/queue", json={"actor_id": member_id, "song_id": str(uuid4())}
    ).json()
    assert queued["queue"][0]["added_by"] == member_id

    denied = client.post(
        f"/jams/{jam_id}/playback/start",
        json={"actor_id": member_id, "request_id": str(uuid4())},
    )
    assert denied.status_code == 403

    started = client.post(
        f"/jams/{jam_id}/playback/start",
        json={"actor_id": owner_id, "request_id": str(uuid4())},
    ).json()
    assert started["state"] == "PREPARING"
    assert started["sync_generation"] == 1

    late_member_id = str(uuid4())
    late_join = client.post(f"/jams/{jam_id}/members", json={"participant_id": late_member_id})
    assert late_join.status_code == 200
    assert late_member_id in late_join.json()["participant_ids"]

    paused = client.post(
        f"/jams/{jam_id}/playback/pause",
        json={"actor_id": owner_id, "request_id": str(uuid4())},
    ).json()
    assert paused["state"] == "PAUSED"


def test_owner_can_reorder_remove_and_skip(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    for _ in range(3):
        response = client.post(
            f"/jams/{jam_id}/queue",
            json={"actor_id": owner_id, "song_id": str(uuid4())},
        )
        assert response.status_code == 200
    queue = response.json()["queue"]

    reordered_ids = [
        queue[1]["queue_item_id"],
        queue[0]["queue_item_id"],
        queue[2]["queue_item_id"],
    ]
    reordered = client.put(
        f"/jams/{jam_id}/queue",
        json={"actor_id": owner_id, "queue_item_ids": reordered_ids},
    ).json()
    assert [item["queue_item_id"] for item in reordered["queue"]] == reordered_ids
    assert [item["position"] for item in reordered["queue"]] == [0, 1, 2]

    started = client.post(
        f"/jams/{jam_id}/playback/start",
        json={"actor_id": owner_id, "request_id": str(uuid4())},
    ).json()
    skipped = client.post(
        f"/jams/{jam_id}/playback/skip",
        json={"actor_id": owner_id, "request_id": str(uuid4())},
    ).json()
    assert skipped["current_queue_item_id"] == reordered_ids[1]
    assert skipped["sync_generation"] == started["sync_generation"] + 1

    removed = client.request(
        "DELETE",
        f"/jams/{jam_id}/queue/{reordered_ids[2]}",
        json={"actor_id": owner_id},
    )
    assert removed.status_code == 200
    assert len(removed.json()["queue"]) == 2


def test_queue_validation_and_owner_cannot_leave(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    song_id = str(uuid4())
    queue = client.post(
        f"/jams/{jam_id}/queue", json={"actor_id": owner_id, "song_id": song_id}
    ).json()["queue"]
    assert (
        client.put(
            f"/jams/{jam_id}/queue",
            json={
                "actor_id": owner_id,
                "queue_item_ids": [queue[0]["queue_item_id"], str(uuid4())],
            },
        ).status_code
        == 409
    )
    assert client.delete(f"/jams/{jam_id}/members/{owner_id}").status_code == 409


def test_websocket_receives_initial_and_updated_queue(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    path = f"/jams/{jam_id}/ws?participant_id={owner_id}&token=local-jam-member-token"
    with client.websocket_connect(path) as websocket:
        assert websocket.receive_json()["queue"] == []
        client.post(
            f"/jams/{jam_id}/queue",
            json={"actor_id": owner_id, "song_id": str(uuid4())},
        )
        assert len(websocket.receive_json()["queue"]) == 1


def test_get_reconciles_readiness_driven_sync_state(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    client.post(
        f"/jams/{jam_id}/queue",
        json={"actor_id": owner_id, "song_id": str(uuid4())},
    ).raise_for_status()
    started = client.post(
        f"/jams/{jam_id}/playback/start",
        json={"actor_id": owner_id, "request_id": str(uuid4())},
    )
    assert started.json()["state"] == "PREPARING"

    sync_client._snapshots[UUID(jam_id)] = SyncSnapshot(
        generation=1,
        state=JamState.SCHEDULED,
    )
    refreshed = client.get(f"/jams/{jam_id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["state"] == "SCHEDULED"
