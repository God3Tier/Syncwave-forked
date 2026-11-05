"""Moderate load on Playlist, Recommendation and Jam through the gateway.

  1. 2000 playlist reads, 50 at a time
  2. 2000 Recommendation reads, 50 at a time (1800 without a location, 200 with
     one: each of those calls Open-Meteo, so they are kept few)
  3. 1500 mixed reads and writes (add, remove, shuffle, get) on 5 shared
     playlists, 50 at a time, then every playlist must still have contiguous
     positions 0..n-1 and no song twice
  4. 20 Jams created from one playlist at the same time, each queue must match
     the playlist's order

Prints p50 / p95 / max latency and the status codes for each step. A step fails
on any 5xx, any unexpected status, or inconsistent data afterwards.

Runs inside the Jam container (from the repo root, with the stack up):

    docker compose exec -T jam python - < tests/integration/playlist-recommendation-load.py

Needs at least 4 READY songs in the Catalogue. Deletes everything it creates.
Exit code 0 when every step passes, 1 otherwise.
"""

import json
import random
import sys
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

GATEWAY = "http://gateway:8080/api"
WORKERS = 50
failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(("ok    " if ok else "FAIL  ") + label + (f"  ({detail})" if detail else ""))
    failures += 0 if ok else 1


def request(method: str, path: str, data: dict | None = None, jam: bool = False):
    headers = {"content-type": "application/json"}
    if jam:
        headers["X-Jam-Token"] = "local-jam-member-token"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(GATEWAY + path, data=body, method=method, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None), time.perf_counter() - started
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()[:200], time.perf_counter() - started
    except Exception as error:  # timeouts, resets
        return 0, repr(error), time.perf_counter() - started


def run(label: str, jobs: list, allowed: set[int]) -> list:
    """Run `jobs` (zero-argument callables) in parallel and report latency and status codes."""
    started = time.perf_counter()
    with ThreadPoolExecutor(WORKERS) as pool:
        results = list(pool.map(lambda job: job(), jobs))
    elapsed = time.perf_counter() - started
    latencies = sorted(result[2] for result in results)
    codes = Counter(result[0] for result in results)
    p50 = latencies[len(latencies) // 2] * 1000
    p95 = latencies[int(len(latencies) * 0.95)] * 1000
    print(f"      {label}: {len(jobs)} requests in {elapsed:.1f}s ({len(jobs) / elapsed:.0f}/s), "
          f"p50 {p50:.0f} ms, p95 {p95:.0f} ms, max {latencies[-1] * 1000:.0f} ms, codes {dict(codes)}")
    check(f"{label}: only expected statuses, no 5xx and no timeouts", set(codes) <= allowed, str(dict(codes)))
    return results


def main() -> None:
    owner = str(uuid.uuid4())
    songs = [s["song_id"] for s in request("GET", "/catalogue/songs?processing_status=READY&limit=4")[1]["items"]]
    if len(songs) < 4:
        check("need 4 READY songs", False, str(len(songs)))
        return
    created: list[str] = []

    def new_playlist(count: int) -> str:
        pid = request("POST", "/playlist/playlists", {"owner_id": owner, "name": "load test"})[1]["playlist_id"]
        created.append(pid)
        for song in songs[:count]:
            request("POST", f"/playlist/playlists/{pid}/songs", {"song_id": song})
        return pid

    try:
        # 1. playlist reads
        reading = new_playlist(4)
        run("playlist reads", [lambda: request("GET", f"/playlist/playlists/{reading}")] * 2000, {200})

        # 2. recommendation reads
        jobs = [lambda: request("GET", "/recommendation/recommendations?limit=5")] * 1800
        jobs += [lambda: request("GET", "/recommendation/recommendations?lat=1.35&lon=103.82&limit=5")] * 200
        random.shuffle(jobs)
        run("recommendation reads", jobs, {200})

        # 3. mixed writes on shared playlists
        shared = [new_playlist(2) for _ in range(5)]

        def mixed(_: int):
            pid = random.choice(shared)
            roll = random.random()
            if roll < 0.35:
                return request("POST", f"/playlist/playlists/{pid}/songs", {"song_id": random.choice(songs)})
            if roll < 0.60:
                return request("DELETE", f"/playlist/playlists/{pid}/songs/{random.choice(songs)}")
            if roll < 0.75:
                return request("POST", f"/playlist/playlists/{pid}/shuffle")
            return request("GET", f"/playlist/playlists/{pid}")

        # 409 = song already there, 404 = song not in the playlist: both are correct answers
        run("mixed reads and writes", [lambda i=i: mixed(i) for i in range(1500)], {200, 404, 409})
        consistent = True
        for pid in shared:
            playlist = request("GET", f"/playlist/playlists/{pid}")[1]
            positions = [s["position"] for s in playlist["songs"]]
            ids = [s["song_id"] for s in playlist["songs"]]
            if positions != list(range(len(positions))) or len(set(ids)) != len(ids):
                consistent = False
                print("      inconsistent:", pid, positions, ids)
        check("after the mixed run every playlist has contiguous positions and no duplicate song", consistent)

        # 4. many Jams from one playlist at once
        source = new_playlist(4)
        order = [s["song_id"] for s in request("POST", f"/playlist/playlists/{source}/shuffle")[1]["songs"]]
        results = run(
            "20 Jams created from one playlist",
            [lambda: request("POST", "/jam/jams", {"owner_id": owner, "playlist_id": source}, jam=True)] * 20,
            {201},
        )
        good = sum(1 for status, body, _ in results if status == 201 and [q["song_id"] for q in body["queue"]] == order)
        check("every Jam's queue matches the playlist order", good == 20, f"{good} of 20")
    finally:
        for pid in created:
            request("DELETE", f"/playlist/playlists/{pid}")


main()
print("all checks passed" if failures == 0 else f"{failures} check(s) failed")
sys.exit(1 if failures else 0)
