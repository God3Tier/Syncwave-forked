# Lyrics Service

**Owner:** Jiawen · **Language/framework:** Python 3.14 / FastAPI, aio-pika, SQLAlchemy + Alembic

Owns the complete lyrics capability (plan.md §3): it consumes `SongUploaded`,
validates and stores the song's timestamped (LRC) lyrics, announces the
result with `LyricsProcessed` / `LyricsProcessingFailed`, and serves the
lyrics to the browser.

## Interfaces

| Kind             | Contract                                                              | Notes |
|------------------|-----------------------------------------------------------------------|-------|
| REST             | [`contracts/api/lyrics.openapi.yaml`](../../contracts/api/lyrics.openapi.yaml) | via gateway at `/api/lyrics/...` |
| Events consumed  | `SongUploaded` from queue `lyrics.song-uploaded`                      | reads `payload.lyrics_reference` |
| Events published | `LyricsProcessed` (`lyrics.processed`), `LyricsProcessingFailed` (`lyrics.failed`) | [`contracts/events/`](../../contracts/events/README.md) |
| gRPC             | none                                                                  | |

```text
lyrics.song-uploaded ──> lyrics-worker ──> S3: lyrics/<song_id>.lrc
                              │ validate + parse LRC
                              ├──> Postgres: lyrics (status, lines)
                              └──> syncwave.events: lyrics.processed | lyrics.failed

browser ──> gateway /api/lyrics/songs/{song_id}/lyrics ──> lyrics (API) ──> Postgres
```

One image runs as two processes, following the layout in plan.md:

| Folder (`src/lyrics_service/`) | Process                                | What                                         |
|--------------------------------|----------------------------------------|----------------------------------------------|
| `api/`                         | `lyrics` (default command, port 8080)  | read-only HTTP API                           |
| `worker/`                      | `lyrics-worker` (`python -m lyrics_service.worker`) | AMQP consumer: retries, DLQ, idempotency |
| `shared/`                      | both                                   | LRC parsing, database, events, S3            |

## Data owned

Table `lyrics` in this service's own `lyrics` database (migrations in
`migrations/`, applied by the API container on start-up):

| Column            | Meaning                                                    |
|-------------------|------------------------------------------------------------|
| `song_id`         | primary key                                                |
| `status`          | `PROCESSING`, `READY` or `FAILED`                          |
| `lines`           | `[{"time_ms": 12340, "text": "..."}]`, sorted by time      |
| `line_count`      | number of lines                                            |
| `error_code`, `error_message` | why it failed                                  |
| `source_event_id` | the `SongUploaded` event last processed                    |

The `.lrc` file itself stays in S3, where the Upload Service put it.

### Accepted lyrics (LRC)

```text
[ti:Song title]           ID tags: ignored, except [offset:]
[offset:+250]             show every line 250 ms earlier (negative: later)
[00:12.34]First line      [mm:ss], [mm:ss.x], [mm:ss.xx] or [mm:ss.xxx]
[00:15.00][01:30.00]Hook  several time tags can share one line
[00:20.00]                no text: an instrumental break
```

UTF-8 (a BOM is fine), at most `LYRICS_MAX_BYTES`. Word-level `<mm:ss.xx>`
tags are removed and lines without a time tag are ignored. A song uploaded
without lyrics (no `lyrics_reference`) is `READY` with no lines.

## Configuration

See `.env.example` for every variable. Locally, Compose sets them
(`compose.yaml`); in production they come from the ECS task definitions
(`lyrics` and `lyrics-worker`). Specific to this service:

| Variable           | Default  | Meaning                                                 |
|--------------------|----------|---------------------------------------------------------|
| `AMQP_PREFETCH`    | `10`     | messages one worker processes concurrently              |
| `LYRICS_MAX_BYTES` | `262144` | larger `.lrc` files fail with `LYRICS_TOO_LARGE`        |
| `DATABASE_URL`     | unset    | overrides `DB_*` (the tests use SQLite this way)        |

## Run

```sh
# whole stack (from the repo root)
docker compose up -d --build

# just this service, after editing it
docker compose up -d --build lyrics lyrics-worker
curl http://localhost:8080/api/lyrics/health
docker compose logs -f lyrics-worker
```

### Try it without the Upload Service

From the repo root, with the stack running (Git Bash on Windows):

```sh
SONG_ID=$(python -c "import uuid; print(uuid.uuid4())")
printf '[ti:Demo]\n[00:01.00]Hello\n[00:03.50]SyncWave\n' > demo.lrc

# 1. Put the lyrics in S3, as Upload would
curl -fsS --aws-sigv4 aws:amz:us-east-1:s3 --user syncwave:syncwave-secret \
  --upload-file demo.lrc "http://localhost:9000/syncwave-audio/lyrics/$SONG_ID.lrc"

# 2. Publish SongUploaded (Waveform consumes it too; it reports AUDIO_NOT_FOUND
#    after ~20 s unless audio/$SONG_ID.mp3 exists, see services/waveform)
sh tests/integration/publish-song-uploaded.sh "$SONG_ID" "audio/$SONG_ID.mp3" "lyrics/$SONG_ID.lrc"

# 3. Read them back
curl -s "http://localhost:8080/api/lyrics/songs/$SONG_ID/lyrics"
```

`LyricsProcessed` waits in the `catalogue.processing-results` queue until
Catalogue consumes it; peek at it in the RabbitMQ UI
(<http://localhost:15672>, Queues → `catalogue.processing-results` → Get messages).

## Test

```sh
cd services/lyrics
python -m venv .venv
. .venv/Scripts/activate          # macOS/Linux: . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check src tests migrations && ruff format --check src tests migrations
pytest
```

The tests need no Docker: SQLite stands in for Postgres and in-memory fakes
for RabbitMQ and S3. `test_events_contract.py` checks every event the
worker publishes against the schemas in `contracts/events/`.

## Failure handling

The worker follows the consumer rules in
[`contracts/events/README.md`](../../contracts/events/README.md). Every
delivery ends in exactly one of:

| Outcome                     | When                                                       |
|-----------------------------|------------------------------------------------------------|
| `ack`                       | processed, or already `READY` (a duplicate delivery)       |
| retry (`reject`, 10 s wait) | a **transient** failure on attempt 1 or 2: S3 or the database unavailable, the `.lrc` not in S3 (yet) |
| give up                     | a **permanent** failure, or a transient one on the 3rd attempt |

Giving up records `FAILED` with the error code, moves the original message
unchanged to `lyrics.song-uploaded.dlq`, publishes `LyricsProcessingFailed`
(so Catalogue can set `lyrics_status = FAILED`), then acks.

| `error_code`              | Kind      | Cause                                           |
|---------------------------|-----------|-------------------------------------------------|
| `INVALID_EVENT`           | permanent | not a usable `SongUploaded` message             |
| `LYRICS_INVALID_ENCODING` | permanent | not UTF-8                                       |
| `LYRICS_INVALID`          | permanent | malformed time tag or `[offset:]`               |
| `LYRICS_NOT_TIMESTAMPED`  | permanent | no `[mm:ss.xx]` time tags at all                |
| `LYRICS_TOO_LARGE`        | permanent | larger than `LYRICS_MAX_BYTES`                  |
| `LYRICS_FILE_NOT_FOUND`   | transient | `lyrics_reference` missing from S3 after 3 attempts |
| `PROCESSING_ERROR`        | transient | anything else, after 3 attempts                 |

- **Duplicates (idempotency):** the `lyrics` row is the processing state. A
  `READY` song is never processed again; its `LyricsProcessed` is published
  again instead. That also repairs a crash between committing `READY` and
  publishing the event. A failure never overwrites `READY` lyrics.
- **Crash mid-message:** the message was not acked, so RabbitMQ redelivers
  it; the row stays `PROCESSING` until then.
- **Independent of Waveform:** each has its own queue, retries and DLQ, so a
  bad `.lrc` does not hold up the waveform (the song becomes `PARTIAL`).
- **RabbitMQ or S3 down:** the API keeps serving stored lyrics; it needs only
  Postgres. The worker reconnects to RabbitMQ by itself.
- **Not handled:** replaying a DLQ is manual (RabbitMQ UI: move the messages
  back to `lyrics.song-uploaded`; a `FAILED` song is then processed again).
  Lyrics cannot be edited after upload, and untimed plain-text lyrics are
  rejected rather than shown without sync.
