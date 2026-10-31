"""Playlist -> Jam -> Sync playback with test WebSocket clients.

Two clients join a Jam built from a playlist, answer Sync's clock pings, send
READY and must receive the same PLAY_AT target time for the playlist's first
song. Then one client reconnects and a third joins late: neither may disturb the
first client. Test clients only: it changes nothing in Jam or Sync.

Runs inside the Jam container (it has `websockets` and reaches the gateway on the
Compose network). From the repo root, with the stack up:

    docker compose exec -T jam python - < tests/integration/playlist-sync-playback.py

Exit code 0 when every check passes, 1 otherwise. Deletes the playlist it makes.
"""

import asyncio
import json
import sys
import time
import urllib.request
import uuid

import websockets

GATEWAY = "http://gateway:8080/api"
SYNC_WS = "ws://gateway:8080/api/sync/ws"
SYNC_TOKEN = "local-sync-participant-token"
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


def now_ms() -> int:
    return int(time.time() * 1000)


class Client:
    """One participant's WebSocket connection to Sync."""

    def __init__(self, name: str, jam_id: str, participant_id: str) -> None:
        self.name = name
        self.jam_id = jam_id
        self.participant_id = participant_id
        self.seq = 0
        self.messages: list[dict] = []
        self._reader: asyncio.Task | None = None
        self.ws = None

    async def connect(self) -> None:
        url = f"{SYNC_WS}?jam_id={self.jam_id}&participant_id={self.participant_id}&token={SYNC_TOKEN}"
        self.ws = await websockets.connect(url)
        self.seq = 0
        self._reader = asyncio.create_task(self._read())

    async def _read(self) -> None:
        try:
            async for raw in self.ws:
                self.messages.append(json.loads(raw))
        except websockets.ConnectionClosed:
            pass

    async def send(self, message_type: str, payload: dict) -> None:
        frame = {
            "type": message_type,
            "jam_id": self.jam_id,
            "seq": self.seq,
            "sent_at_ms": now_ms(),
            "payload": payload,
        }
        self.seq += 1
        await self.ws.send(json.dumps(frame))

    async def wait_for(self, message_type: str, timeout: float = 8.0, after: int = 0) -> dict | None:
        """First message of this type at index >= `after` (also answers clock pings)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for message in self.messages[after:]:
                if message["type"] == message_type:
                    return message
            await asyncio.sleep(0.05)
        return None

    async def sample_clock(self, samples: int = 5) -> int:
        """Ping Sync `samples` times and count the TIME_PONGs that come back."""
        for _ in range(samples):
            before = len([m for m in self.messages if m["type"] == "TIME_PONG"])
            await self.send("TIME_PING", {"sample_id": str(uuid.uuid4()), "client_sent_ms": now_ms()})
            for _ in range(60):
                if len([m for m in self.messages if m["type"] == "TIME_PONG"]) > before:
                    break
                await asyncio.sleep(0.05)
        return len([m for m in self.messages if m["type"] == "TIME_PONG"])

    async def close(self) -> None:
        if self.ws is not None:
            await self.ws.close()
        if self._reader is not None:
            await self._reader


async def main() -> None:
    owner, second, late = (str(uuid.uuid4()) for _ in range(3))
    recommended = call("GET", f"{GATEWAY}/recommendation/recommendations?limit=3")
    ids = [item["song_id"] for item in recommended["items"]]
    if len(ids) < 3:
        check("need 3 READY songs", False, str(len(ids)))
        return
    playlist = call("POST", f"{GATEWAY}/playlist/playlists", {"owner_id": owner, "name": "sync playback"})
    playlist_id = playlist["playlist_id"]
    clients: list[Client] = []
    try:
        for song_id in ids:
            call("POST", f"{GATEWAY}/playlist/playlists/{playlist_id}/songs", {"song_id": song_id})
        order = [song["song_id"] for song in call("POST", f"{GATEWAY}/playlist/playlists/{playlist_id}/shuffle")["songs"]]
        jam = call("POST", f"{GATEWAY}/jam/jams", {"owner_id": owner, "playlist_id": playlist_id}, jam=True)
        jam_id = jam["jam_id"]
        call("POST", f"{GATEWAY}/jam/jams/{jam_id}/members", {"participant_id": second}, jam=True)
        started = call(
            "POST",
            f"{GATEWAY}/jam/jams/{jam_id}/playback/start",
            {"actor_id": owner, "request_id": str(uuid.uuid4())},
            jam=True,
        )
        check("jam starts playback (PREPARING)", started["state"] == "PREPARING", started["state"])

        a, b = Client("owner", jam_id, owner), Client("second", jam_id, second)
        clients = [a, b]
        await a.connect()
        await b.connect()
        for client in (a, b):
            joined = await client.wait_for("JOINED")
            check(f"{client.name}: JOINED", joined is not None)
            prepare = await client.wait_for("PREPARE")
            check(f"{client.name}: PREPARE names the first playlist song", prepare is not None and prepare["payload"]["song_id"] == order[0])
            if prepare is not None:
                check(f"{client.name}: PREPARE has a stream URL", bool(prepare["payload"].get("stream_url")))
            pongs = await client.sample_clock(5)
            check(f"{client.name}: 5 clock samples answered", pongs >= 5, str(pongs))

        generation = (await a.wait_for("PREPARE"))["payload"]["generation"]
        for client in (a, b):
            await client.send(
                "READY", {"generation": generation, "buffered_duration_ms": 5000, "media_duration_ms": 5000}
            )
        play_a = await a.wait_for("PLAY_AT", 10)
        play_b = await b.wait_for("PLAY_AT", 10)
        check("both clients get PLAY_AT", play_a is not None and play_b is not None)
        if play_a and play_b:
            target_a = play_a["payload"]["target_server_time_ms"]
            target_b = play_b["payload"]["target_server_time_ms"]
            check("both get the same target time", target_a == target_b, f"{target_a} vs {target_b}")
            check("target time was in the future when sent", target_a > play_a["sent_at_ms"])
            check("playback starts at position 0 of the first song", play_a["payload"]["start_position_ms"] == 0)

        # --- reconnect: the second client drops and comes back ---------------
        seen_by_owner = len(a.messages)
        await b.close()
        b = Client("second (reconnected)", jam_id, second)
        clients[1] = b
        await b.connect()
        check("reconnect: JOINED again", await b.wait_for("JOINED") is not None)
        check("reconnect: gets a PLAY_AT to resume with", await b.wait_for("PLAY_AT", 10) is not None)
        await asyncio.sleep(2)
        disturbed = [m["type"] for m in a.messages[seen_by_owner:] if m["type"] in ("PREPARE", "PLAY_AT", "SEEK_TO", "PAUSE_AT")]
        check("reconnect: the owner was not restarted or paused", not disturbed, str(disturbed))

        # --- late join: a third participant joins after playback started -----
        call("POST", f"{GATEWAY}/jam/jams/{jam_id}/members", {"participant_id": late}, jam=True)
        seen_by_owner = len(a.messages)
        c = Client("late joiner", jam_id, late)
        clients.append(c)
        await c.connect()
        check("late join: JOINED", await c.wait_for("JOINED") is not None)
        catch_up = await c.wait_for("PLAY_AT", 10)
        check("late join: gets a PLAY_AT to catch up with", catch_up is not None)
        if catch_up is not None:
            check(
                "late join: catch-up time is in the future",
                catch_up["payload"]["target_server_time_ms"] > catch_up["sent_at_ms"],
            )
        await asyncio.sleep(2)
        disturbed = [m["type"] for m in a.messages[seen_by_owner:] if m["type"] in ("PREPARE", "PLAY_AT", "SEEK_TO", "PAUSE_AT")]
        check("late join: the owner was not restarted or paused", not disturbed, str(disturbed))
    finally:
        for client in clients:
            await client.close()
        call("DELETE", f"{GATEWAY}/playlist/playlists/{playlist_id}")


asyncio.run(main())
print("all checks passed" if failures == 0 else f"{failures} check(s) failed")
sys.exit(1 if failures else 0)
