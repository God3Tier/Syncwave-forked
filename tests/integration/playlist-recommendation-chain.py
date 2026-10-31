"""Recommendation -> Playlist -> Jam -> Sync, with one WebSocket client.

Checks that songs recommended by Recommendation, saved in a Playlist and shuffled
reach Jam's queue in the same order, and that Sync's PREPARE message names the
first of them. Runs inside the Jam container, which has `websockets` and reaches
the gateway on the Compose network (from the repo root, with the stack up):

    docker compose exec -T jam python - < tests/integration/playlist-recommendation-chain.py

Exit code 0 when every check passes, 1 otherwise. Deletes the playlist it makes.
"""

import asyncio
import json
import sys
import urllib.request
import uuid

import websockets

GATEWAY = "http://gateway:8080/api"
failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(("ok    " if ok else "FAIL  ") + label + (f"  ({detail})" if detail and not ok else ""))
    failures += 0 if ok else 1


def call(method: str, url: str, data: dict | None = None, jam: bool = False):
    headers = {"content-type": "application/json"}
    if jam:
        headers["X-Jam-Token"] = "local-jam-member-token"
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


async def main() -> None:
    owner = str(uuid.uuid4())
    recommended = call("GET", f"{GATEWAY}/recommendation/recommendations?lat=1.35&lon=103.82&limit=3")
    ids = [item["song_id"] for item in recommended["items"]]
    check("recommendation returns 3 songs", len(ids) == 3, str(len(ids)))
    if len(ids) < 3:
        return
    playlist = call("POST", f"{GATEWAY}/playlist/playlists", {"owner_id": owner, "name": "chain"})
    playlist_id = playlist["playlist_id"]
    try:
        for song_id in ids:
            call("POST", f"{GATEWAY}/playlist/playlists/{playlist_id}/songs", {"song_id": song_id})
        shuffled = call("POST", f"{GATEWAY}/playlist/playlists/{playlist_id}/shuffle")
        order = [song["song_id"] for song in shuffled["songs"]]
        check("playlist holds the recommended songs", sorted(order) == sorted(ids))

        jam = call("POST", f"{GATEWAY}/jam/jams", {"owner_id": owner, "playlist_id": playlist_id}, jam=True)
        check("jam queue matches the shuffled playlist", [q["song_id"] for q in jam["queue"]] == order)

        call(
            "POST",
            f"{GATEWAY}/jam/jams/{jam['jam_id']}/playback/start",
            {"actor_id": owner, "request_id": str(uuid.uuid4())},
            jam=True,
        )
        url = (
            f"ws://gateway:8080/api/sync/ws?jam_id={jam['jam_id']}"
            f"&participant_id={owner}&token=local-sync-participant-token"
        )
        async with websockets.connect(url) as websocket:
            seen = {}
            for _ in range(4):
                try:
                    message = json.loads(await asyncio.wait_for(websocket.recv(), 5))
                except TimeoutError:
                    break
                seen[message.get("type")] = message.get("payload", {})
            check("sync sends JOINED", "JOINED" in seen, str(list(seen)))
            check("sync sends PREPARE", "PREPARE" in seen, str(list(seen)))
            check(
                "PREPARE names the first song of the playlist",
                seen.get("PREPARE", {}).get("song_id") == order[0],
                str(seen.get("PREPARE", {}).get("song_id")),
            )
    finally:
        call("DELETE", f"{GATEWAY}/playlist/playlists/{playlist_id}")


asyncio.run(main())
print("all checks passed" if failures == 0 else f"{failures} check(s) failed")
sys.exit(1 if failures else 0)
