# Audio Sampler (audio_transmitter)

The streaming HTTP service listens on port `8081` and exposes `GET /cache`,
`GET /tracks/{track_id}/stream-info`, `GET /tracks/{track_id}/audio`, and
`GET /tracks/{track_id}/audio/range`.

It has **no database of its own**. Song metadata (the S3 key and the duration)
comes from the Catalogue Service, which owns it, through `GET /songs/{song_id}`.
AWS settings are passed through to the service.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `CATALOGUE_URL` | `http://catalogue:8080` in Compose | Catalogue Service base URL |
| `CATALOGUE_TIMEOUT_SECONDS` | `3` | how long to wait for the Catalogue before giving up |
| `S3_BUCKET` | `syncwave-audio` | bucket containing uploaded audio |
| `AWS_REGION` and credentials | see `compose.yaml` | S3 access |

Sync calls `stream-info` before preparing playback. The response contains the
browser-facing `/api/streaming/tracks/{song_id}/audio` URL; Jam continues to
call Sync and does not depend on Streaming directly.

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

The root Compose stack includes this service as `audio_transmitter`, gives it
the network alias `streaming`, connects it to the shared S3-compatible store,
and routes it through the gateway. The alias keeps the public service name
clear without breaking existing internal callers.

## Test

```sh
make test
```

This runs the Rust test suite in Docker. It needs no database and no running
Catalogue: both are faked in the tests. `make clean` removes the cached build volume.
