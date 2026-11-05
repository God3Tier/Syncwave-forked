# Run from the repo root: docker compose run --rm --no-deps -T -e CATALOGUE_MODE=off playlist python - < tests/integration/manual/playlist-large.py
# Builds playlists of 500 and 2000 random song ids (Catalogue check off) in the real playlist database, times each operation and a Jam import, then deletes them.
import json, subprocess, sys, time, uuid, urllib.request, urllib.error
proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "playlist_service.api.main:app", "--port", "9098", "--log-level", "error"])
B = "http://127.0.0.1:9098"
def call(method, url, data=None, headers=None, base=B):
    req = urllib.request.Request(base + url, data=json.dumps(data).encode() if data is not None else None, method=method,
                                 headers={"content-type": "application/json", **(headers or {})})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read(); return r.status, (json.loads(raw) if raw else None), time.time() - t
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200], time.time() - t
for _ in range(30):
    try: urllib.request.urlopen(B + "/health", timeout=1); break
    except Exception: time.sleep(1)
owner = str(uuid.uuid4()); made = []
try:
    for n in (500, 2000):
        s, pl, _ = call("POST", "/playlists", {"owner_id": owner, "name": f"big {n}"}); pid = pl["playlist_id"]; made.append(pid)
        ids = [str(uuid.uuid4()) for _ in range(n)]
        t = time.time(); last = 0
        for i, sid in enumerate(ids):
            s, _, d = call("POST", f"/playlists/{pid}/songs", {"song_id": sid}); last = d
            if s != 200: print("add failed", i, s); break
        print(f"[{n}] add {n} songs one by one: {time.time()-t:5.1f}s total, last add {last*1000:5.0f} ms")
        s, body, d = call("GET", f"/playlists/{pid}");            print(f"[{n}] GET        {s} {d*1000:6.0f} ms, songs={len(body['songs'])}")
        s, body, d = call("POST", f"/playlists/{pid}/shuffle");   print(f"[{n}] shuffle    {s} {d*1000:6.0f} ms")
        s, body, d = call("PUT", f"/playlists/{pid}/songs", {"song_ids": list(reversed(ids))}); print(f"[{n}] reorder    {s} {d*1000:6.0f} ms")
        s, body, d = call("DELETE", f"/playlists/{pid}/songs/{ids[0]}"); print(f"[{n}] remove one {s} {d*1000:6.0f} ms")
        # real Playlist (gRPC) and real Jam, which share the same database
        s, jam, d = call("POST", "/jams", {"owner_id": owner, "playlist_id": pid}, {"X-Jam-Token": "local-jam-member-token"}, base="http://jam:8080")
        print(f"[{n}] Jam import {s} {d*1000:6.0f} ms", f"queue={len(jam['queue'])}" if s == 201 else jam)
finally:
    for pid in made: call("DELETE", f"/playlists/{pid}")
    proc.terminate()
