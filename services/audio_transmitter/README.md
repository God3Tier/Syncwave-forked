# Audio Sampler (audio_transmitter)

The audio sampler HTTP service listens on port `8081` and exposes `GET /cache`,
`GET /tracks/{track_id}/audio` and `GET /tracks/{track_id}/audio/range`.

It has **no database of its own**. Song metadata (the S3 key and the duration)
comes from the Catalogue Service, which owns it, through `GET /songs/{song_id}`.
AWS settings are passed through to the service.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `CATALOGUE_URL` | `http://localhost:8080/api/catalogue` (`http://host.docker.internal:8080/api/catalogue` in this folder's Compose file) | where the Catalogue Service is reached; the main stack's gateway works |
| `CATALOGUE_TIMEOUT_SECONDS` | `3` | how long to wait for the Catalogue before giving up |
| `AWS_REGION` and credentials | see `compose.yaml` | S3 access |

## Range endpoint and the Catalogue

`GET /tracks/{track_id}/audio/range?start=&end=` (seconds) asks the Catalogue for the song first:

| Catalogue answers | This endpoint returns |
|---|---|
| the song | the audio bytes for the range, read from the Catalogue's `audio_reference` |
| song does not exist | `404` |
| unreachable, too slow, an error, or an unreadable answer | `502` (the song may exist; we could not find out) |
| the song, but `duration_ms` is `null` (Waveform has not measured it yet) | `409` |

## Run

From this directory:

```sh
make up
make status
make logs
make down
```

Start the main stack first (`docker compose up -d --wait` in the repository
root) so the Catalogue is reachable through the gateway. AWS credentials and
`AWS_REGION` can be set in the environment or a local `.env` file.

## Test

```sh
make test
```

This runs the Rust test suite in Docker. It needs no database and no running
Catalogue: both are faked in the tests. `make clean` removes the cached build volume.
