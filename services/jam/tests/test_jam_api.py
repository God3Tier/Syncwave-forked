from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from jam_service.main import playlist_client, sync_client
from jam_service.models import JamState
from jam_service.sync_client import SyncSnapshot

COOKIE = "syncwave_session"


def as_account(client: TestClient, user_id: str) -> None:
    client.cookies.set(COOKIE, user_id)


def as_guest(client: TestClient) -> None:
    client.cookies.delete(COOKIE)


def create_jam(client: TestClient, owner_id: str) -> dict:
    as_account(client, owner_id)
    response = client.post("/jams", json={})
    assert response.status_code == 201, response.text
    return response.json()


def join_guest(client: TestClient, jam_id: str) -> tuple[dict, dict[str, str]]:
    as_guest(client)
    response = client.post(f"/jams/{jam_id}/members")
    assert response.status_code == 200, response.text
    body = response.json()
    return body, {"x-jam-token": body["member_token"]}


def test_health_and_hosting_requires_an_account(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "service": "jam"}
    assert client.get("/ready").status_code == 200
    assert client.post("/jams", json={}).status_code == 401


def test_create_jam_imports_playlist_in_saved_order(client: TestClient) -> None:
    owner_id = str(uuid4())
    playlist_id = uuid4()
    song_ids = [uuid4(), uuid4(), uuid4()]
    playlist_client.playlists[playlist_id] = song_ids
    create_jam(client, owner_id)

    response = client.post("/jams", json={"playlist_id": str(playlist_id)})

    assert response.status_code == 201
    body = response.json()
    assert body["owner_id"] == owner_id
    assert body["member_id"] == owner_id
    assert body["member_token"] is None
    assert [item["song_id"] for item in body["queue"]] == [str(song_id) for song_id in song_ids]
    assert [item["position"] for item in body["queue"]] == [0, 1, 2]
    assert {item["added_by"] for item in body["queue"]} == {owner_id}


def test_members_can_join_and_queue_but_only_account_owner_controls(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam = create_jam(client, owner_id)
    jam_id = jam["jam_id"]
    joined, guest_headers = join_guest(client, jam_id)
    member_id = joined["member_id"]
    assert member_id in joined["participant_ids"]
    assert joined["member_token"]

    queued = client.post(
        f"/jams/{jam_id}/queue", json={"song_id": str(uuid4())}, headers=guest_headers
    )
    assert queued.status_code == 200
    assert queued.json()["queue"][0]["added_by"] == member_id

    spoofed = client.post(
        f"/jams/{jam_id}/queue",
        json={"actor_id": owner_id, "song_id": str(uuid4())},
        headers=guest_headers,
    )
    assert spoofed.status_code == 422
    assert (
        client.post(
            f"/jams/{jam_id}/playback/start",
            json={"request_id": str(uuid4())},
            headers=guest_headers,
        ).status_code
        == 401
    )

    as_account(client, str(uuid4()))
    assert (
        client.post(f"/jams/{jam_id}/playback/start", json={"request_id": str(uuid4())}).status_code
        == 403
    )
    as_account(client, owner_id)
    started = client.post(f"/jams/{jam_id}/playback/start", json={"request_id": str(uuid4())})
    assert started.status_code == 200
    assert started.json()["state"] == "PREPARING"

    late, _ = join_guest(client, jam_id)
    assert late["member_id"] in late["participant_ids"]
    as_account(client, owner_id)
    paused = client.post(f"/jams/{jam_id}/playback/pause", json={"request_id": str(uuid4())})
    assert paused.json()["state"] == "PAUSED"


def test_room_token_is_scoped_to_one_room(client: TestClient) -> None:
    first_id = create_jam(client, str(uuid4()))["jam_id"]
    _, token = join_guest(client, first_id)
    second_id = create_jam(client, str(uuid4()))["jam_id"]

    response = client.get(f"/jams/{second_id}", headers=token)

    assert response.status_code == 401


def test_owner_queue_controls_and_websocket(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    queue = []
    for _ in range(3):
        response = client.post(f"/jams/{jam_id}/queue", json={"song_id": str(uuid4())})
        assert response.status_code == 200
        queue = response.json()["queue"]
    reordered_ids = [
        queue[1]["queue_item_id"],
        queue[0]["queue_item_id"],
        queue[2]["queue_item_id"],
    ]
    reordered = client.put(f"/jams/{jam_id}/queue", json={"queue_item_ids": reordered_ids})
    assert reordered.status_code == 200
    assert [item["queue_item_id"] for item in reordered.json()["queue"]] == reordered_ids

    started = client.post(f"/jams/{jam_id}/playback/start", json={"request_id": str(uuid4())})
    skipped = client.post(f"/jams/{jam_id}/playback/skip", json={"request_id": str(uuid4())})
    assert skipped.json()["current_queue_item_id"] == reordered_ids[1]
    assert skipped.json()["sync_generation"] == started.json()["sync_generation"] + 1
    assert client.delete(f"/jams/{jam_id}/members/{owner_id}").status_code == 409

    path = f"/jams/{jam_id}/ws?participant_id={owner_id}"
    with client.websocket_connect(path) as websocket:
        assert websocket.receive_json()["queue"] == reordered.json()["queue"]
        client.post(f"/jams/{jam_id}/queue", json={"song_id": str(uuid4())})
        assert len(websocket.receive_json()["queue"]) == 4


def test_get_reconciles_readiness_driven_sync_state(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    client.post(f"/jams/{jam_id}/queue", json={"song_id": str(uuid4())}).raise_for_status()
    started = client.post(f"/jams/{jam_id}/playback/start", json={"request_id": str(uuid4())})
    assert started.json()["state"] == "PREPARING"

    sync_client._snapshots[UUID(jam_id)] = SyncSnapshot(generation=1, state=JamState.SCHEDULED)
    refreshed = client.get(f"/jams/{jam_id}")
    assert refreshed.status_code == 200
    assert refreshed.json()["state"] == "SCHEDULED"
