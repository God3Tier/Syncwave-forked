from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from jam_service.guest_names import is_guest_name, pick_guest_name
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
    return body, {"X-Jam-Token": body["member_token"]}


def join_account(client: TestClient, jam_id: str) -> dict:
    as_account(client, str(uuid4()))
    response = client.post(f"/jams/{jam_id}/members")
    assert response.status_code == 200, response.text
    return response.json()


def test_health_and_hosting_requires_an_account(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok", "service": "jam"}
    assert client.get("/ready").status_code == 200
    assert client.post("/jams", json={}).status_code == 401


def test_jam_has_unique_eight_digit_code_and_guests_can_join_with_it(
    client: TestClient,
) -> None:
    first = create_jam(client, str(uuid4()))
    second = create_jam(client, str(uuid4()))
    assert first["join_code"].isdigit() and len(first["join_code"]) == 8
    assert first["join_code"] != second["join_code"]

    as_guest(client)
    joined = client.post(f"/jams/by-code/{first['join_code']}/members")
    assert joined.status_code == 200
    assert joined.json()["jam_id"] == first["jam_id"]
    assert joined.json()["member_token"]
    assert client.post("/jams/by-code/123/members").status_code == 422


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
    assert joined["member_token"] is not None

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


def test_account_membership_is_scoped_to_one_room(client: TestClient) -> None:
    first_id = create_jam(client, str(uuid4()))["jam_id"]
    joined = join_account(client, first_id)
    member_id = joined["member_id"]
    second_id = create_jam(client, str(uuid4()))["jam_id"]
    as_account(client, member_id)
    response = client.get(f"/jams/{second_id}")
    assert response.status_code == 403


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


def test_ended_song_advances_to_the_next_queue_item(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    for _ in range(2):
        queued = client.post(f"/jams/{jam_id}/queue", json={"song_id": str(uuid4())})
        queued.raise_for_status()
    queue = queued.json()["queue"]
    started = client.post(f"/jams/{jam_id}/playback/start", json={"request_id": str(uuid4())})
    started.raise_for_status()
    sync_client._snapshots[UUID(jam_id)] = SyncSnapshot(generation=1, state=JamState.ENDED)

    refreshed = client.get(f"/jams/{jam_id}")

    assert refreshed.status_code == 200
    assert refreshed.json()["current_queue_item_id"] == queue[1]["queue_item_id"]
    assert refreshed.json()["state"] == "PREPARING"


def test_owner_can_transfer_leave_and_end_a_jam(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    joined = join_account(client, jam_id)
    next_owner_id = joined["member_id"]
    as_account(client, owner_id)

    transferred = client.post(
        f"/jams/{jam_id}/owner/transfer-and-leave",
        json={"participant_id": next_owner_id},
    )
    assert transferred.status_code == 200
    assert transferred.json()["owner_id"] == next_owner_id
    assert owner_id not in transferred.json()["participant_ids"]

    as_account(client, next_owner_id)
    ended = client.post(f"/jams/{jam_id}/end")
    assert ended.status_code == 200
    assert ended.json()["lifecycle_state"] == "ENDED"


def test_play_now_during_playback_keeps_the_sync_session(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    for _ in range(3):
        response = client.post(
            f"/jams/{jam_id}/queue",
            json={"song_id": str(uuid4())},
        )
    queue_ids = [item["queue_item_id"] for item in response.json()["queue"]]

    started = client.post(
        f"/jams/{jam_id}/playback/start",
        json={"request_id": str(uuid4())},
    ).json()
    client.post(
        f"/jams/{jam_id}/playback/readiness-decision",
        json={"request_id": str(uuid4()), "decision": "CONTINUE"},
    ).raise_for_status()

    # A new song moves the existing session on (next generation), like a skip,
    # instead of replacing it and stranding the devices connected to it.
    play_now = {"request_id": str(uuid4()), "queue_item_id": queue_ids[2]}
    switched = client.post(f"/jams/{jam_id}/playback/start", json=play_now).json()
    assert switched["current_queue_item_id"] == queue_ids[2]
    assert switched["sync_generation"] == started["sync_generation"] + 1
    assert switched["state"] == "PREPARING"


def test_play_now_starts_a_new_session_when_sync_lost_it(client: TestClient) -> None:
    owner_id = str(uuid4())
    jam_id = create_jam(client, owner_id)["jam_id"]
    client.post(f"/jams/{jam_id}/queue", json={"song_id": str(uuid4())}).raise_for_status()
    client.post(
        f"/jams/{jam_id}/playback/start",
        json={"request_id": str(uuid4())},
    ).raise_for_status()
    client.post(
        f"/jams/{jam_id}/playback/readiness-decision",
        json={"request_id": str(uuid4()), "decision": "CANCEL"},
    ).raise_for_status()
    sync_client._snapshots.clear()  # as if Sync restarted

    restarted = client.post(
        f"/jams/{jam_id}/playback/start",
        json={"request_id": str(uuid4())},
    )
    assert restarted.status_code == 200
    assert restarted.json()["state"] == "PREPARING"


def guest_names(jam: dict) -> list[str]:
    return [p["username"] for p in jam["participants"] if p["role"] == "MEMBER"]


def test_guests_get_a_readable_random_name(client: TestClient) -> None:
    jam = create_jam(client, str(uuid4()))
    joined, _ = join_guest(client, jam["jam_id"])

    (name,) = guest_names(joined)
    assert is_guest_name(name), name
    assert "Guest " not in name


def test_guest_keeps_the_name_its_browser_picked_unless_taken(client: TestClient) -> None:
    jam = create_jam(client, str(uuid4()))
    as_guest(client)
    first = client.post(f"/jams/{jam['jam_id']}/members", json={"guest_name": "SunnyOtter27"})
    assert first.status_code == 200, first.text
    assert guest_names(first.json()) == ["SunnyOtter27"]

    # Same name from another browser: that guest gets a different random name
    second = client.post(f"/jams/{jam['jam_id']}/members", json={"guest_name": "SunnyOtter27"})
    assert second.status_code == 200, second.text
    names = guest_names(second.json())
    assert len(names) == 2 and len({name.casefold() for name in names}) == 2


def test_guest_name_must_have_the_generated_shape(client: TestClient) -> None:
    jam = create_jam(client, str(uuid4()))
    as_guest(client)
    response = client.post(f"/jams/{jam['jam_id']}/members", json={"guest_name": "admin"})
    assert response.status_code == 422


def test_account_ignores_guest_name(client: TestClient) -> None:
    owner = str(uuid4())
    jam = create_jam(client, owner)
    as_account(client, str(uuid4()))
    response = client.post(f"/jams/{jam['jam_id']}/members", json={"guest_name": "SunnyOtter27"})
    assert response.status_code == 200, response.text
    assert "SunnyOtter27" not in guest_names(response.json())


def test_pick_guest_name_avoids_names_in_use() -> None:
    assert pick_guest_name("CalmFox01", []) == "CalmFox01"
    assert pick_guest_name("CalmFox01", ["calmfox01"]) != "CalmFox01"
    assert is_guest_name(pick_guest_name(None, []))
