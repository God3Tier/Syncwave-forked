import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import OWNER_ID

Create = Callable[..., dict[str, Any]]
WithSongs = Callable[[int], tuple[str, list[str]]]


def order_of(playlist: dict[str, Any]) -> list[str]:
    return [song["song_id"] for song in playlist["songs"]]


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ── create / read ───────────────────────────────────────────────────────────


def test_create_returns_an_empty_playlist(client: TestClient) -> None:
    response = client.post("/playlists", json={"owner_id": OWNER_ID, "name": "Rainy day"})

    assert response.status_code == 201
    body = response.json()
    assert uuid.UUID(body["playlist_id"]).version == 4
    assert body["owner_id"] == OWNER_ID
    assert body["name"] == "Rainy day"
    assert body["songs"] == []
    assert body["song_count"] == 0
    assert body["created_at"].endswith("Z")


def test_create_trims_the_name(client: TestClient) -> None:
    response = client.post("/playlists", json={"owner_id": OWNER_ID, "name": "  Chill  "})
    assert response.json()["name"] == "Chill"


@pytest.mark.parametrize(
    "body",
    [
        {"owner_id": OWNER_ID, "name": ""},
        {"owner_id": OWNER_ID, "name": "   "},
        {"owner_id": OWNER_ID, "name": "x" * 101},
        {"owner_id": OWNER_ID},
        {"name": "No owner"},
        {"owner_id": "not-a-uuid", "name": "Bad owner"},
    ],
)
def test_create_rejects_an_invalid_body(client: TestClient, body: dict[str, Any]) -> None:
    response = client.post("/playlists", json=body)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_get_returns_what_was_created(client: TestClient, create_playlist: Create) -> None:
    created = create_playlist()
    response = client.get(f"/playlists/{created['playlist_id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_get_unknown_playlist_is_404(client: TestClient) -> None:
    response = client.get(f"/playlists/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLAYLIST_NOT_FOUND"


def test_playlist_id_must_be_a_uuid(client: TestClient) -> None:
    response = client.get("/playlists/not-a-uuid")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


# ── list ────────────────────────────────────────────────────────────────────


def test_list_returns_only_the_owners_playlists_newest_first(
    client: TestClient, create_playlist: Create
) -> None:
    other_owner = str(uuid.uuid4())
    first = create_playlist("First")
    second = create_playlist("Second")
    create_playlist("Someone else's", owner_id=other_owner)

    body = client.get("/playlists", params={"owner_id": OWNER_ID}).json()

    assert [item["playlist_id"] for item in body["items"]] == [
        second["playlist_id"],
        first["playlist_id"],
    ]
    assert body["next_cursor"] is None


def test_list_summaries_have_a_song_count_and_no_songs(
    client: TestClient, playlist_with_songs: WithSongs
) -> None:
    playlist_id, _ = playlist_with_songs(3)

    (item,) = client.get("/playlists", params={"owner_id": OWNER_ID}).json()["items"]

    assert item["playlist_id"] == playlist_id
    assert item["song_count"] == 3
    assert "songs" not in item


def test_list_pages_through_every_playlist(client: TestClient, create_playlist: Create) -> None:
    created = [create_playlist(f"Playlist {number}")["playlist_id"] for number in range(5)]

    seen: list[str] = []
    cursor = None
    for _ in range(10):
        params: dict[str, Any] = {"owner_id": OWNER_ID, "limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = client.get("/playlists", params=params).json()
        seen += [item["playlist_id"] for item in body["items"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert seen == list(reversed(created))


def test_list_requires_an_owner(client: TestClient) -> None:
    assert client.get("/playlists").status_code == 400


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"cursor": "!!!"}])
def test_list_rejects_bad_paging(client: TestClient, params: dict[str, Any]) -> None:
    response = client.get("/playlists", params={"owner_id": OWNER_ID, **params})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


# ── rename / delete ─────────────────────────────────────────────────────────


def test_rename(client: TestClient, create_playlist: Create) -> None:
    playlist_id = create_playlist("Old")["playlist_id"]

    response = client.patch(f"/playlists/{playlist_id}", json={"name": "New"})

    assert response.status_code == 200
    assert response.json()["name"] == "New"
    assert client.get(f"/playlists/{playlist_id}").json()["name"] == "New"


def test_rename_rejects_a_blank_name(client: TestClient, create_playlist: Create) -> None:
    playlist_id = create_playlist()["playlist_id"]
    assert client.patch(f"/playlists/{playlist_id}", json={"name": " "}).status_code == 400


def test_rename_unknown_playlist_is_404(client: TestClient) -> None:
    response = client.patch(f"/playlists/{uuid.uuid4()}", json={"name": "New"})
    assert response.status_code == 404


def test_delete_removes_the_playlist_and_its_songs(
    client: TestClient, playlist_with_songs: WithSongs
) -> None:
    playlist_id, _ = playlist_with_songs(2)

    response = client.delete(f"/playlists/{playlist_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get(f"/playlists/{playlist_id}").status_code == 404
    assert client.get("/playlists", params={"owner_id": OWNER_ID}).json()["items"] == []


def test_delete_unknown_playlist_is_404(client: TestClient) -> None:
    assert client.delete(f"/playlists/{uuid.uuid4()}").status_code == 404


# ── songs ───────────────────────────────────────────────────────────────────


def test_added_songs_get_contiguous_positions(
    client: TestClient, playlist_with_songs: WithSongs
) -> None:
    playlist_id, songs = playlist_with_songs(3)

    body = client.get(f"/playlists/{playlist_id}").json()

    assert body["songs"] == [
        {"song_id": songs[0], "position": 0},
        {"song_id": songs[1], "position": 1},
        {"song_id": songs[2], "position": 2},
    ]
    assert body["song_count"] == 3


def test_add_at_a_position(client: TestClient, playlist_with_songs: WithSongs) -> None:
    playlist_id, songs = playlist_with_songs(2)
    new_song = str(uuid.uuid4())

    response = client.post(
        f"/playlists/{playlist_id}/songs", json={"song_id": new_song, "position": 1}
    )

    assert response.status_code == 200
    assert order_of(response.json()) == [songs[0], new_song, songs[1]]


def test_add_a_duplicate_is_409(client: TestClient, playlist_with_songs: WithSongs) -> None:
    playlist_id, songs = playlist_with_songs(1)

    response = client.post(f"/playlists/{playlist_id}/songs", json={"song_id": songs[0]})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SONG_ALREADY_IN_PLAYLIST"


@pytest.mark.parametrize(
    "body",
    [{}, {"song_id": "not-a-uuid"}, {"song_id": str(uuid.uuid4()), "position": -1}],
)
def test_add_rejects_an_invalid_body(
    client: TestClient, create_playlist: Create, body: dict[str, Any]
) -> None:
    playlist_id = create_playlist()["playlist_id"]
    response = client.post(f"/playlists/{playlist_id}/songs", json=body)
    assert response.status_code == 400


def test_add_past_the_end_is_400(client: TestClient, playlist_with_songs: WithSongs) -> None:
    playlist_id, _ = playlist_with_songs(1)

    response = client.post(
        f"/playlists/{playlist_id}/songs", json={"song_id": str(uuid.uuid4()), "position": 5}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_add_to_unknown_playlist_is_404(client: TestClient) -> None:
    response = client.post(f"/playlists/{uuid.uuid4()}/songs", json={"song_id": str(uuid.uuid4())})
    assert response.status_code == 404


def test_remove_closes_the_gap(client: TestClient, playlist_with_songs: WithSongs) -> None:
    playlist_id, songs = playlist_with_songs(3)

    response = client.delete(f"/playlists/{playlist_id}/songs/{songs[1]}")

    assert response.status_code == 200
    assert response.json()["songs"] == [
        {"song_id": songs[0], "position": 0},
        {"song_id": songs[2], "position": 1},
    ]


def test_remove_a_song_that_is_not_there_is_404(
    client: TestClient, playlist_with_songs: WithSongs
) -> None:
    playlist_id, _ = playlist_with_songs(1)

    response = client.delete(f"/playlists/{playlist_id}/songs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SONG_NOT_IN_PLAYLIST"


def test_remove_from_unknown_playlist_is_404(client: TestClient) -> None:
    response = client.delete(f"/playlists/{uuid.uuid4()}/songs/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PLAYLIST_NOT_FOUND"


def test_reorder(client: TestClient, playlist_with_songs: WithSongs) -> None:
    playlist_id, songs = playlist_with_songs(3)
    new_order = [songs[2], songs[0], songs[1]]

    response = client.put(f"/playlists/{playlist_id}/songs", json={"song_ids": new_order})

    assert response.status_code == 200
    assert order_of(response.json()) == new_order
    assert order_of(client.get(f"/playlists/{playlist_id}").json()) == new_order


def test_reorder_cannot_drop_or_add_songs(
    client: TestClient, playlist_with_songs: WithSongs
) -> None:
    playlist_id, songs = playlist_with_songs(3)

    dropped = client.put(f"/playlists/{playlist_id}/songs", json={"song_ids": songs[:2]})
    added = client.put(
        f"/playlists/{playlist_id}/songs", json={"song_ids": [*songs, str(uuid.uuid4())]}
    )

    assert dropped.status_code == 400
    assert added.status_code == 400
    assert order_of(client.get(f"/playlists/{playlist_id}").json()) == songs


def test_reorder_unknown_playlist_is_404(client: TestClient) -> None:
    response = client.put(f"/playlists/{uuid.uuid4()}/songs", json={"song_ids": []})
    assert response.status_code == 404


# ── shuffle ─────────────────────────────────────────────────────────────────


def test_shuffle_saves_the_new_order(client: TestClient, playlist_with_songs: WithSongs) -> None:
    playlist_id, songs = playlist_with_songs(8)

    shuffled = client.post(f"/playlists/{playlist_id}/shuffle")

    assert shuffled.status_code == 200
    new_order = order_of(shuffled.json())
    assert sorted(new_order) == sorted(songs)
    assert new_order != songs
    # Persisted: reading again, any number of times, gives the same order.
    for _ in range(3):
        assert order_of(client.get(f"/playlists/{playlist_id}").json()) == new_order


def test_shuffle_keeps_positions_contiguous(
    client: TestClient, playlist_with_songs: WithSongs
) -> None:
    playlist_id, _ = playlist_with_songs(5)

    songs = client.post(f"/playlists/{playlist_id}/shuffle").json()["songs"]

    assert [song["position"] for song in songs] == [0, 1, 2, 3, 4]


def test_shuffle_of_an_empty_playlist_is_fine(client: TestClient, create_playlist: Create) -> None:
    playlist_id = create_playlist()["playlist_id"]
    response = client.post(f"/playlists/{playlist_id}/shuffle")
    assert response.status_code == 200
    assert response.json()["songs"] == []


def test_shuffle_unknown_playlist_is_404(client: TestClient) -> None:
    assert client.post(f"/playlists/{uuid.uuid4()}/shuffle").status_code == 404


def test_updated_at_moves_forward_when_songs_change(
    client: TestClient, create_playlist: Create
) -> None:
    created = create_playlist()
    changed = client.post(
        f"/playlists/{created['playlist_id']}/songs", json={"song_id": str(uuid.uuid4())}
    ).json()

    assert changed["created_at"] == created["created_at"]
    assert changed["updated_at"] >= created["updated_at"]


def test_unknown_path_uses_the_shared_error_shape(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
