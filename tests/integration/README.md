# Integration tests

Tests that need several services, or the real infrastructure, running together.

## How CI runs them

On every push to `staging`, the root pipeline's `integration` job:

1. starts `docker-compose.yml` with the images CI already built and tagged
   `:staging` (`IMAGE_REGISTRY` / `IMAGE_TAG`), so nothing is rebuilt;
2. waits for every healthcheck (`docker compose up --wait`);
3. runs `smoke.sh`, then `tests/e2e/run.sh` if it exists;
4. keeps `compose-logs.txt` and `compose-ps.txt` as job artifacts for debugging.

## Run locally

```sh
docker compose up -d --build --wait
sh tests/integration/smoke.sh
```

`smoke.sh` checks the gateway, S3, the RabbitMQ topology, and
`GET /api/<name>/health` for every folder in `services/`.
Add scenario-level integration checks here as services gain behaviour,
e.g. "publish `SongUploaded`, expect `lyrics_status=READY` in Catalogue".

## Automated upload and processing flow

`upload-flow.py` exercises the actual services through the gateway. It uses
only Python's standard library; it does not start containers or mock S3,
RabbitMQ, the database, or the processing services.

Before running it, integrate Catalogue and the UUID-based Streaming service
from `feat/streaming-sync-integration`, and include Upload in root Compose.
Start the gateway, Upload/publisher, Catalogue/worker, Lyrics/worker,
Waveform/worker, Streaming, and their infrastructure. The Upload branch's
older integer-track-ID Streaming implementation is not compatible with this
scenario. Missing services fail the initial health/readiness checks.

From the repository root in Windows PowerShell, using the prepared Upload
virtual environment:

```powershell
.\services\upload\.venv\Scripts\python.exe tests/integration/upload-flow.py --report tests/integration/upload-flow-report.json
```

With another installed Python 3.10+ interpreter:

```sh
python3 tests/integration/upload-flow.py --base-url http://localhost:8080 --timeout 180
```

The script automatically:

1. Checks the required APIs through the gateway.
2. Generates a four-second WAV tone and a two-line timestamped LRC in memory.
3. Uploads them with a unique title through `POST /api/upload/uploads`, without
   supplying duration so the measured-duration path is exercised.
4. Polls the upload receipt until `PUBLISHED` and checks that the event ID is
   unchanged and a publish attempt/confirmation timestamp is recorded.
5. Waits for Catalogue `processing_status`, `lyrics_status` and
   `waveform_status` to become `READY`; verifies metadata/object references and
   the measured duration.
6. Retrieves lyrics and waveform through their public APIs and checks the
   expected text/timestamps, nonzero peaks, and duration.
7. Downloads the audio through Streaming and compares every byte with the
   generated WAV. The report includes its SHA-256 hash and byte count.

It prints `PASS` for completed checks and exits with code 0 on success. A bad
HTTP response, failed processing stage, mismatched data, or timeout produces a
nonzero exit code and diagnostic output. Asynchronous processing shares the
`--timeout` budget (180 seconds by default), with individual HTTP requests
bounded by `--request-timeout` (10 seconds). A temporary 404 while a consumer
has not created the song's row yet is retried. `--report` optionally saves
JSON evidence, including the test's song/event IDs when available; the example
report filename is gitignored.

### Add the scenario to staging CI

After Upload and the integration dependencies have been merged into the CI
branch, add this command immediately after `smoke.sh` in the root
`integration` job's `script` list:

```yaml
- docker compose exec -T upload python - --base-url http://gateway:8080 < tests/integration/upload-flow.py
```

This runs the script using Python already present in the Upload image. It
targets `gateway` on the Compose network; no additional Python installation
is needed in the Docker CLI job image. Standard output contains the report,
and the Python exit code causes the job to fail when the scenario fails.

### Fixture cleanup

No local audio/lyrics files are written: fixtures exist only in memory. Each
execution creates a new remote test song, S3 objects, and processing records;
they are retained for inspection and identified by the reported IDs and
`upload-flow-<run_id>` title. Failed runs can also leave partial fixture data.
There is no shared song-deletion API, so this script does not delete another
service's rows, purge queues, or reset volumes. Use a disposable stack with
its own data volumes for repeated runs, and remove that stack's data only
after confirming it belongs to the test environment.
## Playlist, Recommendation and Jam

All need at least 4 `READY` songs in the Catalogue (the demo songs are enough).
None of them is run by CI: a fresh CI stack has no `READY` songs, so adding them
to the `integration` job would fail the `staging` pipeline for everyone.

| Script | What it checks | Disruptive? |
|--------|----------------|-------------|
| `playlist-recommendation-flow.sh` | Playlist API through the gateway, Jam importing a playlist (same order), Recommendation with and without a location | no |
| `playlist-recommendation-edge-cases.sh` | bad input, insert positions, reorder errors, shuffle on 0/1/2 songs, paging, 20 parallel adds, Recommendation limits | no |
| `playlist-recommendation-chain.py` | Recommendation -> Playlist -> shuffle -> Jam queue -> Sync `PREPARE` names the first song | no |
| `playlist-sync-playback.py` | two test clients join a Jam built from a playlist, answer clock pings, send `READY`, both get the same `PLAY_AT` for the first song; a reconnect and a late join do not disturb the first client | no |
| `playlist-recommendation-load.py` | 2000 playlist reads, 2000 Recommendation reads, 1500 mixed reads/writes on shared playlists (data must stay consistent), 20 Jams from one playlist at once; prints p50/p95/max | no (moderate load) |
| `playlist-recommendation-resilience.sh` | Playlist restart keeps data; Catalogue, Playlist and Postgres stopped and restarted one at a time | **yes**: stops and restarts containers |

```sh
sh tests/integration/playlist-recommendation-flow.sh
sh tests/integration/playlist-recommendation-edge-cases.sh
docker compose exec -T jam python - < tests/integration/playlist-recommendation-chain.py
docker compose exec -T jam python - < tests/integration/playlist-sync-playback.py
docker compose exec -T jam python - < tests/integration/playlist-recommendation-load.py
sh tests/integration/playlist-recommendation-resilience.sh   # stops containers briefly
```

`manual/` holds two one-off experiments that run in throwaway containers (run
commands are in each file's first lines): `recommendation-weather-down.py`
(six ways the weather API can fail) and `playlist-large.py` (500 and 2000 songs).
