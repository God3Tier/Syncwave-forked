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
