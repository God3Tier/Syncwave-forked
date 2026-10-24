# Playlist Service

**Owner:** Hayyun · **Language/framework:** Python 3.12 / FastAPI, SQLAlchemy + Alembic

Owns playlists: create, rename and delete them, add, remove and reorder songs,
and shuffle. A playlist is an ordered list of `song_id`s and nothing else.
Titles, artists and audio belong to the Catalogue and Streaming services
(plan.md §3, §11).

## Interfaces

| Kind             | Contract                                                                           | Notes |
|------------------|------------------------------------------------------------------------------------|-------|
| REST             | [`contracts/api/playlist.openapi.yaml`](../../contracts/api/playlist.openapi.yaml) | via gateway at `/api/playlist/...` |
| Events published | none                                                                               | |
| Events consumed  | none                                                                               | |
| gRPC (served)    | [`contracts/grpc/syncwave/playlist/v1/playlist.proto`](../../contracts/grpc/syncwave/playlist/v1/playlist.proto) | `GetPlaylist`, read-only, on internal port 50051; callers send `x-internal-token`. Jam and Sync read playlists from here |
| Calls (HTTP)     | Catalogue `GET /songs/{song_id}`, only when a song is added and `CATALOGUE_MODE=http` | refuses the add if the song is unknown or the Catalogue is down |

```text
browser ──> gateway /api/playlist/playlists/... ──> playlist ──> Postgres (playlist database)
Jam / Sync ──────── gRPC GetPlaylist (port 50051, internal) ──┘
```

Jam and Sync use this service as the one source of playlists: the order they
play is the order stored here. Only the REST API changes a playlist; gRPC only
reads.

| Endpoint                                       | What                                                |
|------------------------------------------------|-----------------------------------------------------|
| `POST /playlists`                              | create (`owner_id`, `name`)                         |
| `GET /playlists?owner_id=`                     | a user's playlists, newest first, paged             |
| `GET /playlists/{playlist_id}`                 | one playlist with its songs in order                |
| `PATCH /playlists/{playlist_id}`               | rename                                              |
| `DELETE /playlists/{playlist_id}`              | delete                                              |
| `POST /playlists/{playlist_id}/songs`          | add a song (append, or insert at `position`)        |
| `PUT /playlists/{playlist_id}/songs`           | replace the order with a full list of `song_ids`    |
| `DELETE /playlists/{playlist_id}/songs/{song_id}` | remove a song                                    |
| `POST /playlists/{playlist_id}/shuffle`        | shuffle and save the new order                      |
| `GET /health`                                  | liveness                                            |

## Ordering rules

- `position` is 0-based and contiguous. Adding or removing a song shifts the
  others, so there are never gaps.
- A song appears at most once per playlist (a second add is `409
  SONG_ALREADY_IN_PLAYLIST`).
- **The order is saved.** Shuffle writes the new order, so reading the playlist
  again returns the same order. The browser builds its prefetch window (the
  ±4 songs around the current one, plan.md §5) from this order, so it must not
  change between reads.
- A shuffle of two or more songs always changes the order.
- A reorder must list exactly the songs already in the playlist, once each; it
  can neither add nor drop a song.
- With `CATALOGUE_MODE=http` a `song_id` is checked against the Catalogue when added (see
  Failure handling). The default `off` accepts any id.

The rules are plain functions in `src/playlist_service/ordering.py`; the
database code only saves the result.

## Data owned

Two tables in this service's own `playlist` database (migrations in
`migrations/`, applied by the container on start-up):

| Table            | Columns                                                         |
|------------------|-----------------------------------------------------------------|
| `playlists`      | `playlist_id` (PK), `owner_id`, `name`, `created_at`, `updated_at` |
| `playlist_songs` | `playlist_id` + `song_id` (PK), `position`                       |

Every change to a playlist's songs locks the playlist's row, reads the order,
computes the new order and writes it back in one transaction, so two
simultaneous edits to one playlist cannot overwrite each other.

`owner_id` is the browser-generated `user_id` (`contracts/README.md`); there is
no authentication in scope, so anyone who knows a `playlist_id` can edit it.

## Configuration

See `.env.example` for every variable. Locally, Compose sets them
(`compose.yaml`); in production they come from the ECS task definition.

| Variable       | Default    | Meaning                                              |
|----------------|------------|------------------------------------------------------|
| `DB_HOST` etc. | `localhost`/`playlist` | the service's own Postgres database      |
| `DATABASE_URL` | unset      | overrides `DB_*` (the tests use SQLite this way)     |
| `LOG_LEVEL`    | `INFO`     |                                                      |

## Run

```sh
# whole stack (from the repo root)
docker compose up -d --build

# just this service, after editing it
docker compose up -d --build playlist
curl http://localhost:8080/api/playlist/health
```

## Test

```sh
cd services/playlist
pip install -r requirements-dev.txt
pytest
ruff check src tests migrations && ruff format --check src tests migrations
```

The tests run against SQLite, so they need no Docker. `test_contract.py` fails
if the API stops matching `contracts/api/playlist.openapi.yaml`.

## Failure handling

- **Postgres is down:** requests fail with a 500 and the container's health
  check stays up (it only reports that the process is alive). Nothing is
  cached, so there is no stale data to serve. Compose starts the service only
  after Postgres is healthy.
- **`CATALOGUE_MODE=off` (the default):** the Catalogue is never asked and any
  song id is accepted. Switch to `http` once the Catalogue Service is in the stack.
- **Adding a song the Catalogue does not have** (`http` mode): refused with 404
  `SONG_NOT_FOUND`; nothing is stored.
- **The Catalogue is down or too slow when a song is added** (`http` mode): refused with 502
  `CATALOGUE_UNAVAILABLE`; nothing is stored and nothing is queued for later.
  This is the only operation that needs the Catalogue. Create, read, rename,
  reorder, shuffle, remove and delete keep working. Playlist does not wait for
  the Catalogue to start.
- **A song removed from the Catalogue after it was added:** not detected.
  Playlist keeps the `song_id`. Reacting to a Catalogue "song deleted" event
  would fix it, but no such event exists, so it is out of scope.
- **Two edits at once:** serialised by the row lock described above.
- **Not handled on purpose:** authentication, ownership checks, a maximum
  playlist size and rate limiting.
