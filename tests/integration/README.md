# Integration tests

Tests that need several services, or the real infrastructure, running together.

## How CI runs them

On every push to `staging`, the root pipeline's `integration` job:

1. starts `docker-compose.yml` with the images CI already built and tagged
   `:staging` (`IMAGE_REGISTRY` / `IMAGE_TAG`), so nothing is rebuilt;
2. waits for every healthcheck (`docker compose up --wait`);
3. runs `smoke.sh`, then `ingestion-flow.py` and `backend-flow.py` (both reuse
   `upload-flow.py`), then `tests/e2e/run.sh` if it exists;
4. keeps `compose-logs.txt`, `compose-ps.txt` and both scenario JSON reports
   as job artifacts for debugging, including on failure.

CI layers `ingestion.compose.yaml` over root Compose: Recommendation uses
real Catalogue data and fixed RAIN weather for repeatable mood checks.

## Run locally

```sh
docker compose up -d --build --wait
sh tests/integration/smoke.sh
```

`smoke.sh` checks the gateway, S3, the RabbitMQ topology, and
`GET /api/<name>/health` for the seven Python APIs in the root Compose stack,
and `GET /api/streaming/cache` for the audio transmitter. Standalone service
folders are not treated as deployed services.
Add scenario-level integration checks here as services gain behaviour,
e.g. "publish `SongUploaded`, expect `lyrics_status=READY` in Catalogue".

## Worker readiness

The root stack mounts `infrastructure/health/check-consumers.py` into each
worker. Its health check uses the local RabbitMQ management API to verify
that this container's named AMQP connection owns consumers for its required
queues. A consumer in another container does not satisfy the check.
This probe is specific to local Compose; it requires the configured broker's
management API on port 15672. It checks consumer registration, not successful
processing or database/S3 access; scenario tests must verify those separately.

The documented `docker compose up -d --wait` command waits for all three
workers as well as the APIs. To check Catalogue's consumers directly:

```sh
docker compose exec -T catalogue-worker python /app/check-consumers.py catalogue.song-uploaded catalogue.processing-results
```

The following negative check must exit nonzero even while Lyrics is healthy:

```sh
docker compose exec -T catalogue-worker python /app/check-consumers.py lyrics.song-uploaded
```

## Automated upload and processing flow

`upload-flow.py` exercises the actual services through the gateway. It uses
only Python's standard library; it does not start containers or mock S3,
RabbitMQ, the database, or the processing services.

It needs the gateway, Upload/publisher, Catalogue/worker, Lyrics/worker,
Waveform/worker, Streaming, and their infrastructure: `docker compose up -d
--build --wait` starts all of them. Missing services fail the initial
health/readiness checks.

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

### In staging CI

The root `integration` job now imports this flow through `ingestion-flow.py`
(the complete item 2 scenario below). For debugging only the upload/processing
part inside CI or another shell supporting input redirection, use:

```yaml
- docker compose exec -T upload python - --base-url http://gateway:8080 < tests/integration/upload-flow.py
```

This runs the script using Python already present in the Upload image. It
targets `gateway` on the Compose network; no additional Python installation
is needed in the Docker CLI job image. Standard output contains the report,
and the Python exit code causes the job to fail when the scenario fails.
Unlike the manual Playlist/Recommendation scripts farther below, it creates
its own song, so a fresh CI stack is fine.

### Fixture cleanup

No local audio/lyrics files are written: fixtures exist only in memory. Each
execution creates a new remote test song, S3 objects, and processing records;
they are retained for inspection and identified by the reported IDs and
`upload-flow-<run_id>` title. Failed runs can also leave partial fixture data.
There is no shared song-deletion API, so this script does not delete another
service's rows, purge queues, or reset volumes. Use a disposable stack with
its own data volumes for repeated runs, and remove that stack's data only
after confirming it belongs to the test environment.

## Item 2: complete ingestion and discovery scenario

`ingestion-flow.py` verifies the remaining ingestion/discovery acceptance
criteria against the real APIs, S3, RabbitMQ, databases and consumers. It
runs inside Upload using that image's existing `aio-pika` and `boto3`.
No new Python dependencies or frontend are required.

The script:

1. Uploads two distinct four-second WAV/LRC fixtures with unique titles and
   mixed-case/whitespace `mood` values. It reuses the full `upload-flow.py`
   checks and verifies normalized mood reaches both the receipt and Catalogue.
2. Waits for each ready song to appear exactly once in Search with matching
   title/artist, including an uppercase query against the lowercase title.
3. Captures an actual Catalogue `SongReady` on a temporary exclusive queue.
   Replays the same body/event ID twice directly to `search.song-ready`;
   waits for RabbitMQ to record both publications and acknowledgements with
   no pending messages; verifies results, metadata and order are unchanged.
4. Calls real Recommendation/Catalogue APIs without a location and with fixed
   RAIN weather. A newer upbeat song is initially ahead of the calm song;
   weather must promote the calm song and mark it `WEATHER_MATCH`, while the
   upbeat song remains `GENERAL`.
5. Uploads valid audio with untimed UTF-8 lyrics. Checks Catalogue `PARTIAL`,
   Lyrics `FAILED` with `LYRICS_NOT_TIMESTAMPED` and an error message, Waveform
   `READY`, and no Search result for that partial song.
6. Captures its own original dead-lettered event, repairs only the exact
   `lyrics/<fixture-song-id>.lrc` object, and replays that body/event ID directly
   to Lyrics. Checks the same song becomes `READY` and searchable, lyrics and
   audio bytes match, and the successful waveform (including `updated_at`)
   is unchanged.

### Run from Windows PowerShell

Use a quiet local/disposable stack with no other uploads or event publishers
during the check. Duplicate verification requires enabled RabbitMQ management
statistics and an idle Search queue; it deliberately fails if additional
Search publications are observed during that step. Statistics collection can
add several seconds to the run. It does not accept a merely queued duplicate
as proof of consumer processing.

From the repository root, build the backend images, then start the selected
services with deterministic test weather:

```powershell
docker compose build upload catalogue lyrics waveform audio_transmitter search recommendation
docker compose -f docker-compose.yml -f tests/integration/ingestion.compose.yaml up -d --wait --wait-timeout 180 gateway upload upload-publisher catalogue catalogue-worker lyrics lyrics-worker waveform waveform-worker audio_transmitter search search-worker recommendation
```

The override keeps Catalogue mode `http` and sets only Recommendation weather
to `stub`/`RAIN`. The root service defaults are unchanged. This scenario does
not start the frontend, Playlist, Jam or Sync.

Copy both scripts and execute the item 2 checks:

```powershell
docker compose cp tests/integration/upload-flow.py upload:/tmp/upload-flow.py
docker compose cp tests/integration/ingestion-flow.py upload:/tmp/ingestion-flow.py
docker compose exec -T upload python /tmp/ingestion-flow.py --report /tmp/ingestion-flow-report.json
$LASTEXITCODE
```

Exit code 0 and report `result: PASS` mean all checks passed. Any nonzero code
is a failure. `--timeout 180` bounds each processing/polling stage;
`--request-timeout 15` bounds individual API requests. Main errors still
produce a partial JSON report. Retrieve it **before** `docker compose down`:

```powershell
docker compose cp upload:/tmp/ingestion-flow-report.json tests/integration/ingestion-flow-report.json
```

If needed, inspect worker logs:

```powershell
docker compose logs --tail 100 upload upload-publisher catalogue-worker search-worker lyrics-worker waveform-worker recommendation
```

After copying evidence, stop the stack:

```powershell
docker compose down
```

The next normal root `docker compose up` restores the usual Recommendation
weather configuration. Do not delete volumes to repeat this scenario.

### Retained data and CI

The script leaves three uniquely named songs, their S3 objects and processing
records, and the recovery fixture's original entry in
`lyrics.song-uploaded.dlq`. These are recorded in the report. It consumes only
its own exclusive observer copies; it never gets/purges messages from a
service queue or shared DLQ, stops a service, or edits service database rows.
The exclusive observer queue is removed when its connection closes.

The original dead letter remains as failure evidence: recovery republishes
its captured copy, rather than deleting or moving other queued work. There
is no shared song-deletion API, so use disposable test data for repeated runs.

The root staging `integration` job starts the same weather override, runs
this scenario after smoke checks, fails on a nonzero result, and retrieves
`tests/integration/ingestion-flow-report.json` in `after_script`. That report
and Compose logs/status are retained for one week with `when: always`.
Other branches keep the existing pipeline rules. Live GitLab execution still
requires an authorized push/merge and a successful staging pipeline.

## Self-contained backend scenario

`backend-flow.py` combines the generated upload/processing checks with
Playlist -> Jam -> Sync. It creates two new songs on every run, so it does not
need any pre-existing READY songs. The WAV tones have different frequencies
(440 and 660 Hz); a wrong-song audio response therefore fails the byte check.
It reuses `upload-flow.py`, which must be copied alongside it.

The scenario checks:

1. Both songs pass upload, confirmed event delivery, Catalogue readiness,
   lyrics/waveform retrieval, measured duration and exact audio-byte checks.
2. A new playlist contains the two songs in their inserted order.
3. Jam imports that exact order and admits the independent owner/member IDs.
4. Both Sync clients receive `JOINED` and `PREPARE` for the correct first
   song, queue item, media URL and generation.
5. Both clients complete five clock exchanges and report readiness using the
   actual fixture duration.
6. Both receive identical `PLAY_AT` payloads, with a future server timestamp,
   the same generation, position zero and normal playback rate.

These are protocol clients: no frontend or audible playback is exercised.
The test does not start/stop shared services or test outage/restart scenarios.

### Run from Windows PowerShell

From the repository root, build and start the required backend services:

```powershell
docker compose build upload catalogue lyrics waveform playlist audio_transmitter sync jam
docker compose up -d --wait --wait-timeout 180 gateway upload upload-publisher catalogue catalogue-worker lyrics lyrics-worker waveform waveform-worker playlist audio_transmitter sync jam
```

The gateway, RabbitMQ, PostgreSQL and S3 dependencies start automatically.
Search, Recommendation and the frontend are not required for this scenario.
Copy the two scripts to known file paths (safe to repeat) and run inside Jam,
whose image already provides Python and `websockets`:

```powershell
docker compose cp tests/integration/upload-flow.py jam:/tmp/upload-flow.py
docker compose cp tests/integration/backend-flow.py jam:/tmp/backend-flow.py
docker compose exec -T jam python /tmp/backend-flow.py --report /tmp/backend-flow-report.json
$LASTEXITCODE
```

The default gateway URL is `http://gateway:8080` inside Compose. Exit code 0
means all checks and playlist cleanup passed; any nonzero result is a failure.
Processing may take up to `--timeout 180` seconds per song. HTTP requests use
`--request-timeout 15`; individual WebSocket operations use `--ws-timeout 10`.
Connection and clock sampling run concurrently to avoid unnecessarily using
up Sync's preparation deadline.

Copy the report back even if the test fails:

```powershell
docker compose cp jam:/tmp/backend-flow-report.json tests/integration/backend-flow-report.json
```

It includes both song/event IDs, object references, byte hashes, playlist/Jam
IDs, both playback schedules and cleanup outcomes. Jam HTTP authentication
uses its `MOCK_JAM_TOKEN` environment variable (or the local default); Sync
uses `SYNC_PARTICIPANT_TOKEN` when supplied, otherwise the local participant
token. Tokens are not included in the report.

### Cleanup and CI

All WebSockets are closed in a `finally` block, and the newly created playlist
is deleted even when a later step fails. Generated songs, S3 objects, Jam and
Sync session remain identified in the report: there are no public deletion
APIs for all of them. Run against disposable test data for repeated checks;
no existing songs, shared queues, databases or volumes are deleted.

The root staging `integration` job runs this scenario after ingestion checks
and before the optional browser-test hook. It copies both scripts into Jam,
then executes:

```yaml
- docker compose cp tests/integration/upload-flow.py jam:/tmp/upload-flow.py
- docker compose cp tests/integration/backend-flow.py jam:/tmp/backend-flow.py
- docker compose exec -T jam python /tmp/backend-flow.py --report /tmp/backend-flow-report.json
```

`integration.after_script` retrieves the report even when the scenario fails.
The job retains it with the ingestion report and Compose logs/status for one
week using `artifacts.when: always`:

```yaml
# after_script entry:
- docker compose cp jam:/tmp/backend-flow-report.json tests/integration/backend-flow-report.json || true
# artifacts.paths entry:
- tests/integration/backend-flow-report.json
```

A nonzero scenario exit fails the job. Report collection is best effort:
if startup or an earlier scenario fails before this script runs, its report
will not exist; the available ingestion report and Compose logs still help
diagnose the failure. Live verification requires the updated configuration
to reach staging through an authorized push/merge. Check the job output for
both scenario PASS results, download both reports from job artifacts, and
record the successful pipeline URL in `INTEGRATION_PLAN.md`.

## Playlist, Recommendation and Jam

All need at least 4 `READY` songs in the Catalogue. A fresh stack has only the
seeded demo song, so first add three more, e.g. by running `upload-flow.py`
three times (each run leaves one `READY` song behind). None of them is run by
CI: they would need the same setup there, so adding them to the `integration`
job as they are would fail the `staging` pipeline for everyone.

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
