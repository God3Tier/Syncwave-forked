# Catalogue Service

**Owner:** Orvin · **Language/framework:** Python 3.12 / FastAPI, SQLAlchemy + Alembic

The Catalogue Service is the canonical source for song metadata and processing
state (plan.md §3). It stores each song's core information, tracks whether
lyrics and waveform processing have finished, derives an overall readiness
flag, and publishes `SongReady` once a song is fully processed so Search can
index it.

## Interfaces

| Kind             | Contract                                        | Notes |
|------------------|-------------------------------------------------|-------|
| REST             | no OpenAPI file yet — see the Song contract below | via gateway at `/api/catalogue/...` |
| Events consumed  | `LyricsProcessed`, `LyricsProcessingFailed`, `WaveformProcessed`, `WaveformProcessingFailed` | queue `catalogue.processing-results` |
| Events published | `SongReady` (`song.ready`)                      | `contracts/events/README.md` |
| gRPC             | `syncwave.catalogue.v1.CatalogueService` (proposed) | `contracts/grpc/` |

### Song contract (owned by Catalogue)

Defined in [`contracts/README.md`](../../contracts/README.md):

```text
song_id            UUID
title              string
artist             string
duration_ms        integer
audio_reference    string    S3 object key, e.g. "audio/<song_id>.mp3"
lyrics_status      PENDING | PROCESSING | READY | FAILED
waveform_status    PENDING | PROCESSING | READY | FAILED
processing_status  PROCESSING | PARTIAL | READY | FAILED
created_at         timestamp
updated_at         timestamp
```

`processing_status` is derived from the two stage statuses:

- `READY` when both `lyrics_status` and `waveform_status` are `READY`
- `PARTIAL` when one is `READY` and the other is `FAILED`
- `FAILED` when both failed
- otherwise `PROCESSING`

A song becomes `PARTIAL` (not `FAILED`) when only one stage fails, so the
browser can still play a song with lyrics but no waveform, or vice versa.

### Event flow (Scenario 2 choreography)

```text
SongUploaded ──> Lyrics Service ──> LyricsProcessed  ──┐
                                                     ├──> catalogue.processing-results ──> Catalogue
SongUploaded ──> Waveform Service ──> WaveformProcessed ──┘
                                                          │
                                                          v
                                                    Catalogue derives processing_status
                                                          │
                      READY ──> SongReady (song.ready) ──> Search indexes it
```

Catalogue consumes each processing result, updates the matching stage
status, recomputes `processing_status`, and — only when it becomes `READY`
— publishes `SongReady` so Search can make the song discoverable. Duplicate
event deliveries are skipped idempotently using `event_id` plus the stored
processing state (plan.md §16).

## Data owned

Table `songs` in this service's own `catalogue` database (migrations in
`migrations/`, applied by the container on start-up):

| Column            | Meaning                                                    |
|-------------------|------------------------------------------------------------|
| `song_id`         | primary key, UUID v4                                       |
| `title`           | song title                                                 |
| `artist`          | artist name                                                |
| `duration_ms`     | audio duration in milliseconds                             |
| `audio_reference` | S3 object key, e.g. `audio/<song_id>.mp3`                  |
| `lyrics_status`   | `PENDING`, `PROCESSING`, `READY` or `FAILED`               |
| `waveform_status` | `PENDING`, `PROCESSING`, `READY` or `FAILED`               |
| `processing_status` | `PROCESSING`, `PARTIAL`, `READY` or `FAILED` (derived)  |
| `created_at`      | row creation timestamp                                     |
| `updated_at`      | last update timestamp                                      |

The audio bytes and `.lrc` lyrics file stay in S3 (Upload Service put them
there); this service only stores the S3 key and the processing statuses.

## Configuration

See `.env.example` for every variable. Locally, Compose sets them
(`compose.yaml`); in production they come from the ECS task definition.

Variable specifics for this service are recorded in `.env.example` once the
service skeleton lands; the variables shared by every service are:

| Variable     | Meaning                          |
|--------------|----------------------------------|
| `DATABASE_URL` | Postgres connection string (tests use SQLite) |
| `AMQP_URL`   | RabbitMQ connection string       |

## Run

```sh
# whole stack (from the repo root)
docker compose up -d --build

# just this service, after editing it
docker compose up -d --build catalogue
curl http://localhost:8080/api/catalogue/health
```

## Test

```sh
cd services/catalogue
python -m venv .venv
. .venv/Scripts/activate          # macOS/Linux: . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check src tests migrations && ruff format --check src tests migrations
pytest
```

Tests need no Docker: SQLite stands in for Postgres and in-memory fakes for
RabbitMQ and S3. `test_events_contract.py` checks every event this service
publishes against the schemas in `contracts/events/`.

## Failure handling

Catalogue follows the consumer rules in
[`contracts/events/README.md`](../../contracts/events/README.md). Every
delivery ends in exactly one of:

| Outcome                     | When                                                       |
|-----------------------------|------------------------------------------------------------|
| `ack`                       | stage status updated, or already reflects this result      |
| retry (`reject`, 10 s wait) | a **transient** failure: database briefly unavailable      |
| give up                     | a **permanent** failure, or a transient one on the 3rd attempt |

- **Duplicates (idempotency):** re-delivering `LyricsProcessed` for a song
  whose `lyrics_status` is already `READY` is an `ack` with no write. That
  also repairs a crash between committing `READY` and publishing `SongReady`.
- **One stage fails:** the song becomes `PARTIAL`; the successful stage is
  never redone, and `SongReady` is not published until the failed stage is
  retried and succeeds (or an operator resolves it).
- **Both stages fail:** `processing_status = FAILED`; no `SongReady` is
  published and Search does not index the song.
- **Database down:** the API keeps returning whatever is committed; new
  processing results wait in RabbitMQ's retry queue.

## Deliberate limitations of this slice

- REST contract: [`contracts/api/catalogue.openapi.yaml`](../../contracts/api/catalogue.openapi.yaml)
  (linted by CI).
- Catalogue implements the shared media query gRPC contract at
  `contracts/grpc/syncwave/media/v1/media.proto` on port `50051`. Root Compose
  configures Sync to call `catalogue:50051`; isolated tests still use local
  fakes so they do not require another service.
- Mock/internal tokens are local-development values only.
