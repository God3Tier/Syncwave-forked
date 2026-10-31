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

## Playlist, Recommendation and Jam

All need at least 4 `READY` songs in the Catalogue (the demo songs are enough).
None of them is run by CI: a fresh CI stack has no `READY` songs, so adding them
to the `integration` job would fail the `staging` pipeline for everyone.

| Script | What it checks | Disruptive? |
|--------|----------------|-------------|
| `playlist-recommendation-flow.sh` | Playlist API through the gateway, Jam importing a playlist (same order), Recommendation with and without a location | no |
| `playlist-recommendation-edge-cases.sh` | bad input, insert positions, reorder errors, shuffle on 0/1/2 songs, paging, 20 parallel adds, Recommendation limits | no |
| `playlist-recommendation-chain.py` | Recommendation -> Playlist -> shuffle -> Jam queue -> Sync `PREPARE` names the first song | no |
| `playlist-recommendation-resilience.sh` | Playlist restart keeps data; Catalogue, Playlist and Postgres stopped and restarted one at a time | **yes**: stops and restarts containers |

```sh
sh tests/integration/playlist-recommendation-flow.sh
sh tests/integration/playlist-recommendation-edge-cases.sh
docker compose exec -T jam python - < tests/integration/playlist-recommendation-chain.py
sh tests/integration/playlist-recommendation-resilience.sh   # stops containers briefly
```

`manual/` holds two one-off experiments that run in throwaway containers (run
commands are in each file's first lines): `recommendation-weather-down.py`
(six ways the weather API can fail) and `playlist-large.py` (500 and 2000 songs).
