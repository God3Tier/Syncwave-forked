#!/usr/bin/env python3
"""Generate two songs, verify ingestion, then test Auth -> Playlist -> Jam -> Sync.

Run inside the Jam container or from a host against a deployed gateway.
Clients exercise the backend protocol; they do not play audible browser audio.
"""

import argparse
import asyncio
import importlib.util
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

Json = dict[str, Any]
BACKEND_FIXTURE_DURATION_MS = 15_000


class FlowError(Exception):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FlowError(message)


def load_upload_flow():
    path = Path(__file__).with_name("upload-flow.py")
    require(path.is_file(), f"Copy upload-flow.py alongside this script: {path}")
    spec = importlib.util.spec_from_file_location("syncwave_upload_flow_helpers", path)
    require(spec is not None and spec.loader is not None, "Cannot load upload-flow.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Api:
    def __init__(self, base_url: str, timeout: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(
        self,
        method: str,
        path: str,
        data: Json | None = None,
        *,
        expected: int = 200,
    ) -> Json | None:
        headers = {"Accept": "application/json"}
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        request = Request(self.base_url + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                require(response.status == expected, f"{method} {path}: HTTP {response.status}")
                raw = response.read(1_000_001)
                require(len(raw) <= 1_000_000, f"{path}: unexpectedly large response")
        except HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            exc.close()
            raise FlowError(f"{method} {path}: HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise FlowError(f"{method} {path}: request failed: {exc}") from exc
        if not raw:
            return None
        result = json.loads(raw)
        require(isinstance(result, dict), f"{path}: expected a JSON object")
        return result


class Client:
    def __init__(
        self, sdk, base_url: str, jam_id: str, participant_id: str, name: str, timeout: float
    ) -> None:
        address = urlsplit(base_url)
        scheme = "wss" if address.scheme == "https" else "ws"
        query = urlencode(
            {
                "jam_id": jam_id,
                "participant_id": participant_id,
                "token": os.getenv("SYNC_PARTICIPANT_TOKEN", "local-sync-participant-token"),
            }
        )
        self.url = f"{scheme}://{address.netloc}{address.path.rstrip('/')}/api/sync/ws?{query}"
        self.sdk, self.name, self.jam_id, self.timeout = sdk, name, jam_id, timeout
        self.connection = None
        self.seq = 0
        self.messages: list[Json] = []

    async def connect(self) -> None:
        self.connection = await self.sdk.connect(
            self.url, open_timeout=self.timeout, close_timeout=3, max_size=65536
        )

    async def receive(
        self, message_type: str, predicate: Callable[[Json], bool] | None = None
    ) -> Json:
        def matches(frame: Json) -> bool:
            return frame.get("type") == message_type and (predicate is None or predicate(frame))

        for frame in self.messages:
            if matches(frame):
                return frame
        try:
            async with asyncio.timeout(self.timeout):
                while True:
                    frame = json.loads(await self.connection.recv())
                    require(isinstance(frame, dict), f"{self.name}: invalid WebSocket frame")
                    require(frame.get("jam_id") == self.jam_id, f"{self.name}: wrong Jam ID")
                    if frame.get("type") == "ERROR":
                        raise FlowError(f"{self.name}: Sync error: {frame.get('payload')}")
                    self.messages.append(frame)
                    if matches(frame):
                        return frame
        except TimeoutError as exc:
            raise FlowError(f"{self.name}: timed out waiting for {message_type}") from exc

    async def send(self, message_type: str, payload: Json) -> None:
        frame = {
            "type": message_type,
            "jam_id": self.jam_id,
            "seq": self.seq,
            "sent_at_ms": time.time_ns() // 1_000_000,
            "payload": payload,
        }
        self.seq += 1
        async with asyncio.timeout(self.timeout):
            await self.connection.send(json.dumps(frame))

    async def sample_clock(self) -> int:
        for _ in range(5):
            sample_id = str(uuid.uuid4())
            await self.send(
                "TIME_PING",
                {
                    "sample_id": sample_id,
                    "client_sent_ms": time.time_ns() // 1_000_000,
                },
            )
            await self.receive(
                "TIME_PONG", lambda frame, wanted=sample_id: frame["payload"]["sample_id"] == wanted
            )
        return 5

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()


def passed(report: Json, label: str) -> None:
    report["checks"].append(label)
    print(f"PASS {label}", flush=True)


async def playback(
    api: Api,
    sdk,
    client_wait_seconds: float,
    report: Json,
    check_reconnect: bool = False,
    check_resync: bool = False,
) -> None:
    owner = report["account_id"]
    song_ids = [song["song_id"] for song in report["songs"]]
    playlist = await asyncio.to_thread(
        api.call,
        "POST",
        "/api/playlist/playlists",
        {"name": f"backend-flow-{report['run_id']}"},
        expected=201,
    )
    playlist_id = str(uuid.UUID(playlist["playlist_id"]))
    report["playlist_id"] = playlist_id
    for song_id in song_ids:
        await asyncio.to_thread(
            api.call, "POST", f"/api/playlist/playlists/{playlist_id}/songs", {"song_id": song_id}
        )
    saved = await asyncio.to_thread(api.call, "GET", f"/api/playlist/playlists/{playlist_id}")
    order = [song["song_id"] for song in saved["songs"]]
    require(order == song_ids, "Saved playlist order differs from the inserted fixture order")
    report["playlist_order"] = order
    passed(report, "playlist contains both generated songs in the expected order")

    jam = await asyncio.to_thread(
        api.call,
        "POST",
        "/api/jam/jams",
        {"playlist_id": playlist_id},
        expected=201,
    )
    jam_id = str(uuid.UUID(jam["jam_id"]))
    report["jam_id"] = jam_id
    require(str(jam["owner_id"]) == owner, "Jam owner differs from signed-in account")
    require([item["song_id"] for item in jam["queue"]] == order, "Jam changed playlist order")
    require([item["position"] for item in jam["queue"]] == [0, 1], "Invalid Jam queue positions")
    queue_item_id = jam["queue"][0]["queue_item_id"]
    passed(report, "Jam imports the exact playlist order")
    guest_api = Api(api.base_url, api.timeout)
    joined = await asyncio.to_thread(
        guest_api.call, "POST", f"/api/jam/jams/{jam_id}/members"
    )
    member = str(uuid.UUID(joined["member_id"]))
    report.update(owner_id=owner, member_id=member)
    require(set(joined["participant_ids"]) == {owner, member}, "Jam membership differs")

    started = await asyncio.to_thread(
        api.call,
        "POST",
        f"/api/jam/jams/{jam_id}/playback/start",
        {"request_id": str(uuid.uuid4())},
    )
    require(started["state"] == "PREPARING", "Jam did not enter PREPARING")
    generation = started["sync_generation"]
    require(isinstance(generation, int) and generation > 0, "Missing Sync generation")
    clients = [
        Client(sdk, api.base_url, jam_id, owner, "owner", client_wait_seconds),
        Client(sdk, api.base_url, jam_id, member, "member", client_wait_seconds),
    ]
    try:
        # Connect and sample concurrently to stay inside Sync's readiness deadline.
        connections = await asyncio.gather(
            *(client.connect() for client in clients), return_exceptions=True
        )
        for client, result in zip(clients, connections, strict=True):
            if isinstance(result, BaseException):
                raise FlowError(f"{client.name}: WebSocket connection failed: {result}")
        await asyncio.gather(*(client.receive("JOINED") for client in clients))
        prepared = await asyncio.gather(*(client.receive("PREPARE") for client in clients))
        for client, frame in zip(clients, prepared, strict=True):
            payload = frame["payload"]
            require(payload["song_id"] == order[0], f"{client.name}: wrong PREPARE song")
            require(payload["queue_item_id"] == queue_item_id, f"{client.name}: wrong queue item")
            require(payload["generation"] == generation, f"{client.name}: wrong generation")
            require(
                payload["stream_url"] == f"/api/streaming/tracks/{order[0]}/audio",
                f"{client.name}: PREPARE stream URL does not match the verified audio",
            )
            require(payload["start_position_ms"] == 0, f"{client.name}: unexpected start position")
        passed(report, "both clients prepare the first fixture song and correct stream URL")
        samples = await asyncio.gather(*(client.sample_clock() for client in clients))
        report["clock_samples"] = dict(zip((c.name for c in clients), samples, strict=True))
        passed(report, "both clients complete five clock exchanges")

        duration = report["songs"][0]["duration_ms"]
        await asyncio.gather(
            *(
                client.send(
                    "READY",
                    {
                        "generation": generation,
                        "buffered_duration_ms": duration,
                        "media_duration_ms": duration,
                    },
                )
                for client in clients
            )
        )
        play_frames = await asyncio.gather(*(client.receive("PLAY_AT") for client in clients))
        first = play_frames[0]["payload"]
        require(
            first == play_frames[1]["payload"], "Participants received different PLAY_AT payloads"
        )
        require(first["generation"] == generation, "PLAY_AT generation differs from PREPARE")
        require(first["start_position_ms"] == 0, "PLAY_AT did not start at position zero")
        require(first["playback_rate"] == 1, "Unexpected initial playback rate")
        for frame in play_frames:
            require(
                first["target_server_time_ms"] > frame["sent_at_ms"],
                "PLAY_AT target was not in the future when the server sent it",
            )
        report["play_at"] = {
            client.name: frame["payload"]
            for client, frame in zip(clients, play_frames, strict=True)
        }
        passed(report, "both participants receive identical future PLAY_AT schedules")
        if check_reconnect:
            # Observe the established owner's stream throughout the reconnect.
            # Check every new control frame; cached initial frames are excluded.
            stop_monitor = asyncio.Event()

            async def watch_owner() -> None:
                while not stop_monitor.is_set():
                    try:
                        async with asyncio.timeout(0.2):
                            frame = json.loads(await clients[0].connection.recv())
                            require(
                                frame.get("type")
                                not in {"PREPARE", "PLAY_AT", "SEEK_TO", "PAUSE_AT", "ERROR"},
                                f"Reconnect disturbed owner: {frame.get('type')}",
                            )
                    except TimeoutError:
                        continue

            # Wait until the original scheduled start has passed. Use the two
            # server timestamps' difference, avoiding cross-host clock assumptions.
            lead = (first["target_server_time_ms"] - play_frames[0]["sent_at_ms"]) / 1000
            await asyncio.sleep(max(0, lead) + 0.2)
            monitor = asyncio.create_task(watch_owner())
            try:
                await clients[1].close()
                clients[1] = Client(
                    sdk, api.base_url, jam_id, member, "member-reconnected", client_wait_seconds
                )
                reconnect_started = time.monotonic()
                await clients[1].connect()
                rejoined = await clients[1].receive("JOINED")
                require(
                    rejoined["payload"]["participant_id"] == member,
                    "Reconnect attached the wrong participant",
                )
                report["reconnect"] = {
                    "participant_id": member,
                    "joined_state": rejoined["payload"]["state"],
                }
                prepare = await clients[1].receive("PREPARE")
                await clients[1].send(
                    "READY",
                    {
                        "generation": prepare["payload"]["generation"],
                        "buffered_duration_ms": duration,
                        "media_duration_ms": duration,
                    },
                )
                caught_up = await clients[1].receive("PLAY_AT")
                payload = caught_up["payload"]
                require(payload["generation"] == generation, "Reconnect changed generation")
                require(
                    payload["target_server_time_ms"] > caught_up["sent_at_ms"],
                    "Reconnect catch-up is not scheduled in the future",
                )
                require(
                    payload["start_position_ms"] > first["start_position_ms"],
                    "Reconnect reset playback to the beginning",
                )
                report["reconnect"].update(
                    play_at=payload,
                    recovery_seconds=round(time.monotonic() - reconnect_started, 3),
                )
                await asyncio.sleep(1)
                stop_monitor.set()
                await monitor
                report["reconnect"]["owner_undisturbed"] = True
                passed(report, "reconnected participant catches up without restarting the owner")
            finally:
                if not monitor.done():
                    monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)

        if check_resync:
            timeline = report.get("reconnect", {}).get("play_at", first)
            simulated_clock_offset_ms = 750

            async def report_drift(
                drift_ms: int,
                elapsed_from_target_ms: int,
                round_trip_delay_ms: int,
                *,
                after_sent_at_ms: int = -1,
            ) -> tuple[Json, float]:
                measured_server_time_ms = (
                    timeline["target_server_time_ms"] + elapsed_from_target_ms
                )
                expected_position_ms = round(
                    timeline["start_position_ms"]
                    + elapsed_from_target_ms * timeline["playback_rate"]
                )
                await clients[1].send(
                    "PLAYBACK_STATUS",
                    {
                        "generation": generation,
                        "measured_server_time_ms": measured_server_time_ms,
                        "position_ms": expected_position_ms + drift_ms,
                        "buffering": False,
                        "clock_offset_ms": simulated_clock_offset_ms,
                        "round_trip_delay_ms": round_trip_delay_ms,
                    },
                )
                started_at = time.monotonic()
                correction = await clients[1].receive(
                    "SYNC_CORRECTION",
                    lambda frame: frame["sent_at_ms"] > after_sent_at_ms,
                )
                return correction, round((time.monotonic() - started_at) * 1000, 1)

            scenarios = [(200, 1_000, 80), (2_000, 4_200, 450), (-2_000, 7_400, 1_200)]
            corrections = []
            previous_sent_at = -1
            for index, (drift_ms, elapsed_ms, rtt_ms) in enumerate(scenarios):
                if index:
                    await asyncio.sleep(3.2)
                correction, response_ms = await report_drift(
                    drift_ms,
                    elapsed_ms,
                    rtt_ms,
                    after_sent_at_ms=previous_sent_at,
                )
                require(
                    correction["payload"]["method"] == "SEEK",
                    f"{drift_ms} ms drift did not use SEEK",
                )
                require(
                    correction["payload"]["drift_ms"] == drift_ms,
                    "Correction reported wrong drift",
                )
                corrections.append(
                    {
                        "input_drift_ms": drift_ms,
                        "simulated_round_trip_delay_ms": rtt_ms,
                        "correction_response_ms": response_ms,
                        "correction": correction["payload"],
                    }
                )
                previous_sent_at = correction["sent_at_ms"]
            report["resync"] = {
                "simulated_clock_offset_ms": simulated_clock_offset_ms,
                "changing_latency_and_drift": corrections,
            }
            passed(
                report,
                "changing +200, +2000 and -2000 ms drift is corrected across variable latency",
            )
    finally:
        results = await asyncio.gather(
            *(client.close() for client in clients), return_exceptions=True
        )
        errors = [str(result) for result in results if isinstance(result, BaseException)]
        report["cleanup"]["websockets_closed"] = not errors
        if errors:
            report["cleanup"]["websocket_errors"] = errors
    require(report["cleanup"]["websockets_closed"], "WebSocket cleanup failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://gateway:8080")
    parser.add_argument("--timeout", type=float, default=180, help="Processing timeout per song")
    parser.add_argument("--request-timeout", type=float, default=15)
    parser.add_argument("--ws-timeout", type=float, default=10)
    parser.add_argument(
        "--check-reconnect",
        action="store_true",
        help="Also reconnect a participant after the scheduled start",
    )
    parser.add_argument(
        "--check-resync",
        action="store_true",
        help="Also simulate moderate and severe playback drift under degraded network telemetry",
    )
    parser.add_argument(
        "--report", type=Path, help="JSON evidence file, including partial failures"
    )
    args = parser.parse_args()
    address = urlsplit(args.base_url)
    if address.scheme not in {"http", "https"} or not address.netloc:
        parser.error("--base-url must be an HTTP(S) gateway URL")
    if any(
        not 0 < value < float("inf")
        for value in (args.timeout, args.request_timeout, args.ws_timeout)
    ):
        parser.error("timeouts must be finite positive numbers")

    report: Json = {
        "run_id": uuid.uuid4().hex,
        "base_url": args.base_url,
        "result": "FAIL",
        "checks": [],
        "songs": [],
        "cleanup": {"playlist_deleted": None},
        "scope": "Backend protocol and media bytes; no audible browser playback measurement",
        "retained_data": (
            "Generated account, songs/S3 objects, Jam and Sync session; no deletion API"
        ),
    }
    started = time.monotonic()
    api = Api(args.base_url, args.request_timeout)
    try:
        try:
            import websockets
        except ImportError as exc:
            raise FlowError("Install websockets (`python -m pip install websockets`) to run this test") from exc
        upload = load_upload_flow()
        for path in (
            "/api/auth/health",
            "/api/playlist/health",
            "/api/jam/ready",
            "/api/sync/health",
        ):
            api.call("GET", path)
        username = f"e2e_{report['run_id'][:16]}"
        credentials = {"username": username, "password": f"E2e-{report['run_id']}"}
        account = api.call(
            "POST",
            "/api/auth/signup",
            credentials,
            expected=201,
        )
        session = api.call("POST", "/api/auth/login", credentials)
        require(session["id"] == account["id"], "Login returned a different account")
        report["account_id"] = str(uuid.UUID(account["id"]))
        report["username"] = username
        passed(report, "disposable account signs in through the deployed Auth service")
        for number in (1, 2):
            frequency = 440 if number == 1 else 660
            song: Json = {
                "run_id": f"{report['run_id']}-{number}",
                "frequency_hz": frequency,
                "result": "FAIL",
            }
            report["songs"].append(song)
            print(f"\nPreparing fixture song {number}/2...", flush=True)
            upload.run(
                upload.Api(api.base_url, args.request_timeout),
                args.timeout,
                song,
                audio=upload.audio_fixture(
                    frequency_hz=frequency,
                    duration_ms=BACKEND_FIXTURE_DURATION_MS,
                ),
                expected_duration_ms=BACKEND_FIXTURE_DURATION_MS,
            )
            song["result"] = "PASS"
        passed(
            report, "both generated songs pass upload, processing and exact audio download checks"
        )
        asyncio.run(
            playback(
                api,
                websockets,
                args.ws_timeout,
                report,
                args.check_reconnect,
                args.check_resync,
            )
        )
        report["result"] = "PASS"
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"FAIL {report['error']}", file=sys.stderr, flush=True)
    finally:
        if playlist_id := report.get("playlist_id"):
            try:
                api.call("DELETE", f"/api/playlist/playlists/{playlist_id}", expected=204)
                report["cleanup"]["playlist_deleted"] = True
            except Exception as exc:
                report["cleanup"]["playlist_deleted"] = False
                report["cleanup"]["playlist_error"] = str(exc)
                report["result"] = "FAIL"
                print(f"FAIL test playlist cleanup: {exc}", file=sys.stderr, flush=True)

    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    print(json.dumps(report, indent=2), flush=True)
    if args.report:
        try:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            print(f"FAIL writing report: {exc}", file=sys.stderr, flush=True)
            return 1
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
