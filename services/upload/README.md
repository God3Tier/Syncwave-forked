# Upload Service

**Owner:** Yonghuey. **Stack:** Python 3.14, FastAPI, SQLAlchemy, PostgreSQL,
boto3, aio-pika. The API stores media and a durable upload receipt. A separate
publisher process sends committed `SongUploaded` events to RabbitMQ.

## Interfaces and flow

| Interface | Purpose |
| --- | --- |
| `POST /uploads` | Multipart `title`, `artist`, `audio`, optional `lyrics`, `duration_ms` and `mood`; returns `202` with a receipt |
| `GET /uploads/{song_id}` | Receipt and event delivery status |
| `GET /health` | Process health |
| `GET /ready` | Database schema and S3 bucket availability |
| `SongUploaded` | `syncwave.events` exchange, `song.uploaded` routing key |

The gateway exposes these routes at `/api/upload/...`. The table above and
examples below describe how to use the API. The standalone API contract is
[`contracts/api/upload.openapi.yaml`](../../contracts/api/upload.openapi.yaml).

Swagger UI is available at <http://localhost:8080/api/upload/docs> when the
service and gateway are running. Expand `POST /uploads`, choose **Try it out**,
enter title/artist, select an audio file and optional lyrics file, and click
**Execute**. A successful upload returns `202` with a receipt. Copy its
`song_id` into `GET /uploads/{song_id}` to check event delivery status.

1. Validate title/artist, optional positive duration, optional mood (trimmed,
   lowercased, at most 64 characters), file size/type and audio header. Audio is spooled to disk by the multipart parser, then passed to S3
   as a file object; it is not loaded into one large Python byte string.
2. Generate UUID v4 `song_id` and `event_id`. Save an `UPLOADING` receipt in
   the Upload database. Client filenames never become S3 paths.
3. Store `audio/<song_id>.<extension>` and optional `lyrics/<song_id>.lrc` in
   `syncwave-audio`. MP3, WAV, FLAC, OGG and M4A are supported. Lyrics must be
   nonempty UTF-8 LRC files; timestamp validation belongs to Lyrics.
4. Atomically change the receipt to `PENDING` and save the full event JSON.
   The receipt itself is the outbox. Return `202` and a `Location` header.
5. `upload-publisher` reads committed `PENDING` rows, locks one row at a time,
   publishes a persistent message with publisher confirms, and marks the
   receipt `PUBLISHED` only after confirmation.
6. Lyrics and Waveform consume independently. Catalogue registers the song
   and its initial processing state from the event, then handles processing
   results. Upload never writes Catalogue's database.

## Supported audio formats

The `audio` upload field accepts these file formats:

- MP3 (`.mp3`)
- WAV (`.wav`)
- FLAC (`.flac`)
- Ogg (`.ogg`)
- M4A (`.m4a`)

File extensions are case-insensitive. The audio header must match the file
extension; renaming an unsupported file does not make it valid. Empty files
are rejected. The default maximum audio file size is **190 MiB**, configurable
through `UPLOAD_MAX_AUDIO_BYTES`.

## State and ownership

```text
UPLOADING -> PENDING -> PUBLISHED
    |
    +-----> FAILED  (S3 failure)
```

`PENDING` means safely stored and waiting for event delivery. `PUBLISHED`
means the broker confirmed receipt, **not** that Catalogue or a processor has
finished. `publish_attempts`, `last_error_code` and `published_at` make delivery
observable. Poll Catalogue separately for canonical `processing_status`,
`lyrics_status` and `waveform_status`.

The event includes `title`, `artist`, `audio_reference`, nullable
`lyrics_reference`, and `duration_ms` and `mood` when supplied, plus the shared
event envelope (`contracts/events/song-uploaded.schema.json`). Catalogue
registers the song from it.

`mood` feeds Recommendation, which puts songs whose mood suits the weather
first. It recognises `calm`, `mellow`, `upbeat` and `energetic`; any other mood
is stored but never matches the weather.

## Run and try

From the repository root:

```sh
docker compose up -d --build upload upload-publisher
curl http://localhost:8080/api/upload/health
curl http://localhost:8080/api/upload/ready
curl -i -X POST http://localhost:8080/api/upload/uploads \
  -F 'title=Example song' -F 'artist=Example artist' -F 'mood=calm' \
  -F 'audio=@/path/to/song.mp3' -F 'lyrics=@/path/to/song.lrc'
curl http://localhost:8080/api/upload/uploads/<song_id>
docker compose logs upload upload-publisher
```

Start the gateway as well if it is not already running:
`docker compose up -d gateway`. Omit `lyrics` for instrumentals; omit
`duration_ms` when unknown. The processor measures duration independently.
On Windows PowerShell use `curl.exe` and put the command on one line.

See `.env.example` for every variable. Compose sets local credentials. The
190 MiB audio limit leaves room below the gateway's 200 MiB request limit;
lyrics default to 256 KiB. Production uses S3's normal endpoint and the ECS
task role: omit local endpoint/path-style settings and static AWS keys.

## Failures and recovery

- Invalid inputs return the shared error body and do not write media/events.
- On S3 failure the service best-effort deletes attempted objects, records
  `FAILED`, and returns `503` with the upload ID. No upload event is queued.
- On RabbitMQ failure media and the pending event remain durable. Delivery
  retries indefinitely with exponential backoff capped at 60 seconds. Restart
  recovery reads the same event and preserves its `event_id`.
- A crash after broker confirmation but before the database commit can send
  the event twice. Delivery is at least once; consumers must deduplicate.
- A crash during ingestion or a database failure after S3 writes can leave
  `UPLOADING` receipts/orphaned objects. Media is retained after an ambiguous
  database commit to avoid deleting something a committed event references.
  Automatic reconciliation/resumable upload is future work; inspect receipts
  and S3 keys before manually cleaning these objects. No stale receipt is
  automatically announced as a completed upload.
- Audio is hashed incrementally with SHA-256. Repeating `POST /uploads` with
  exactly the same audio bytes returns the canonical receipt with HTTP `200`
  and `duplicate: true`; it does not write another object or event. Different
  encodings of the same performance are not considered duplicates.
- The verified account cookie supplies the canonical uploader ID. The database
  column remains nullable only for historical rows; every new upload is owned.
  Duplicate attempts never transfer ownership.
- `/ready` checks API dependencies; broker delivery problems are observable
  through pending receipts and publisher logs. The API can accept uploads
  while RabbitMQ is unavailable.

## Test and build

### Processing failures after publication

After a receipt becomes `PUBLISHED`, check Catalogue
`GET /api/catalogue/songs/<song_id>` for overall/stage status and
`GET /api/lyrics/songs/<song_id>/lyrics` or
`GET /api/waveform/songs/<song_id>/waveform` for the failed stage's error.
One failed stage gives Catalogue `PARTIAL`; both failing give `FAILED`.
Search indexes songs only once Catalogue announces `SongReady`.

Transient worker failures retry through RabbitMQ at ten-second intervals,
giving up after three failed attempts. Permanent validation/decoding errors
go directly to the affected worker's dead-letter queue. Broker publication
retries on an Upload receipt are separate from these processing retries.

For a user with malformed media/lyrics, correct the source files and submit
a new upload; this creates a new song ID. There is no public HTTP endpoint
for editing media or retrying an existing song.

For operator recovery preserving the song ID:

1. Inspect the failed stage's error, logs and the selected original
   `SongUploaded` in `lyrics.song-uploaded.dlq` or
   `waveform.song-uploaded.dlq`. Confirm the song ID/object references.
2. Fix the dependency or repair that song's source object at the referenced
   S3 key. Replaying permanently invalid input unchanged will fail again.
3. Republish only that selected original body/event ID to the affected
   consumer's queue (`lyrics.song-uploaded` or `waveform.song-uploaded`),
   using RabbitMQ's default exchange. A failed stage can process it again;
   already successful stages need not be replayed. A copied DLQ entry remains
   for inspection until the operator explicitly removes that selected entry.
4. Poll the stage and Catalogue until `READY`, then verify Search and media.
   Do not purge/replay an entire shared queue to retry a single song.

The automated version of this procedure is documented under item 2 in
[`tests/integration/README.md`](../../tests/integration/README.md). It repairs
only its generated lyrics fixture and leaves existing songs untouched.

### Unit checks and container build

```sh
cd services/upload
python -m venv .venv
# Activate the virtual environment, then:
pip install -r requirements-dev.txt
ruff check src tests migrations
ruff format --check src tests migrations
pytest
# From the repository root:
docker compose build upload
```

Tests use real SQLite transactions with fake S3/broker adapters. They cover
media and metadata validation, cleanup, persisted delivery/retry and restart,
event contracts, and migration upgrade/downgrade. Live S3/RabbitMQ/Postgres
integration still requires Docker. Alembic migrations run before API startup;
the publisher waits for the API to become healthy. Both processes use the same
image and the `upload` child pipeline builds/deploys that image.

After deploying the nullable hash column, backfill published legacy uploads
oldest-first with the service environment configured:

```sh
cd services/upload
PYTHONPATH=src python -m upload_service.backfill
```

The backfill streams S3 objects, is safe to rerun, assigns each hash to the
oldest matching row, and leaves later legacy duplicate rows unchanged so their
existing song references continue to work. Historical `uploader_id` values
remain null because ownership cannot be reconstructed safely.
