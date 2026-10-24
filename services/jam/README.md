# Jam Service

Jam is the room and queue authority for SyncWave. Members can join, leave,
and add songs. Only the owner can remove/reorder songs or start, pause,
resume, seek, skip, and resolve readiness timeouts. Authorized playback
commands are forwarded to Sync over the versioned gRPC contract.

## API

All HTTP calls use `X-Jam-Token: local-jam-member-token` in local development.
Mutations include an `actor_id`; Jam verifies membership or ownership before
changing state or calling Sync.

- `POST /jams`, `GET /jams/{jam_id}`. Pass an optional `playlist_id` to
  create the Jam with that Playlist Service order copied into its queue.
- `POST /jams/{jam_id}/members`, `DELETE /jams/{jam_id}/members/{participant_id}`
- `POST /jams/{jam_id}/queue`, `PUT /jams/{jam_id}/queue`
- `DELETE /jams/{jam_id}/queue/{queue_item_id}`
- `POST /jams/{jam_id}/playback/{start|pause|resume|seek|skip}`
- `GET /jams/{jam_id}/playback/readiness`
- `POST /jams/{jam_id}/playback/readiness-decision`
- `WS /jams/{jam_id}/ws?participant_id=...&token=...`

The create and join responses return the local-development member token.
Production authentication can replace this mock token without changing room
authorization rules.

## Run

From the repository root:

```sh
docker compose up -d --build --wait
curl http://localhost:8080/api/jam/health
```

Leaving `SYNC_GRPC_TARGET` blank uses a deterministic fake for isolated Jam
development. Compose sets it to `sync:50051` and uses the shared internal
token for authenticated calls.

Compose also sets `PLAYLIST_GRPC_TARGET=playlist:50051`. When `playlist_id`
is supplied to `POST /jams`, Jam calls `PlaylistQueryService.GetPlaylist`
with the Playlist-specific `x-internal-token` and a 750 ms deadline. The
returned song order becomes the Jam's mutable queue snapshot.

## Test

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/pytest
.venv/Scripts/ruff check src tests
.venv/Scripts/ruff format --check src tests
```

Jam uses its own PostgreSQL database and Alembic migration. Generated Sync and
Playlist bindings live under `src/syncwave/{sync,playlist}/v1`; regenerate
them from the corresponding files under `contracts/grpc/syncwave/` whenever a
contract changes.

## Cross-service calls

Jam calls Playlist only when importing a playlist and calls Sync for
authorized playback commands. It does not call Catalogue or Streaming;
Sync owns those playback-readiness checks.

## Current cross-service mismatch

Jam, Playlist, Catalogue, and the current `audio_transmitter` now use canonical
UUID song IDs. The transmitter still exposes HTTP and does not implement
`StreamingQueryService.GetStreamInfo`, so Sync keeps only its Streaming
dependency fake until that contract is implemented. Jam does not bypass Sync
or call Streaming itself.
