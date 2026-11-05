# Search Service

**Owner:** Orvin · **Language/framework:** Python 3.12 / FastAPI, SQLAlchemy + Alembic

The Search Service maintains a searchable index of ready songs (plan.md §3.2).
It consumes `SongReady` events published by Catalogue, fetches the song's
title/artist from Catalogue, and stores a small searchable row per song.
Browsers search by title or artist through `GET /search`.

## Interfaces

| Kind             | Contract                                        | Notes |
|------------------|-------------------------------------------------|-------|
| REST             | `contracts/api/search.openapi.yaml`             | via gateway at `/api/search/...` |
| Events consumed  | `SongReady` (`song.ready`)                      | queue `search.song-ready` |
| Events published | none                                            |       |

### Search result contract

```text
song_id   UUID
title     string
artist    string
```

`GET /search?q=<text>&limit=&cursor=` returns `{ items, next_cursor }`.

Matching is case-insensitive substring on title or artist.

### Rebuilding the index

Catalogue is the canonical source. When the worker starts, it pages through
Catalogue's `GET /songs?processing_status=READY` and indexes every song, so
songs that became ready while Search was down (or before it existed) are
searchable. Re-indexing is idempotent and keeps each song's `indexed_at`. A
failed startup rebuild is logged, not fatal. To rebuild by hand:

```sh
docker compose exec search-worker python -m search_service.worker.rebuild
```

## Data owned

Table `search_index` in this service's own `search` database:

| Column     | Meaning                      |
|------------|------------------------------|
| song_id    | primary key, UUID            |
| title      | song title                   |
| artist     | artist name                  |
| indexed_at | when the row was first indexed |

## Configuration

See `.env.example`.

## Run

```sh
docker compose up -d --build search
curl http://localhost:8080/api/search/health
```

## Test

```sh
cd services/search
python -m venv .venv
. .venv/Scripts/activate
pip install -r requirements-dev.txt
ruff check src tests migrations && ruff format --check src tests migrations
pytest
```

Tests need no Docker: SQLite stands in for Postgres and an in-memory fake for
Catalogue.