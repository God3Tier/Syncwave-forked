# Orchestrator

The orchestrator HTTP service listens on port `8080` and exposes `GET /health`.
It runs as part of the root Compose stack (Compose service `orchestrator`),
reached through the gateway at `/api/orchestrator/*`, with its own database
`orchestrator` on the shared PostgreSQL.

## Playlist playback

`POST /playlists/{playlist_id}/play` accepts the playlist UUID. The
orchestrator gets the ordered song IDs from Playlist Service, then prepares
the plan's nine-slot audio window. Each returned buffer contains base64 audio,
lyrics with timestamps in seconds, and waveform peaks with their duration and
per-peak midpoint timestamps in milliseconds. The timestamp positions are
derived from the waveform service's evenly spaced peaks and duration.

The endpoint uses the same account session as the SyncWave frontend whenever
authentication is configured.
Upstream base URLs can be overridden with `PLAYLIST_SERVICE_URL`,
`AUDIO_SERVICE_URL`, `LYRICS_SERVICE_URL`, and `WAVEFORM_SERVICE_URL`. Defaults
are `http://playlist:8080`, `http://audio_transmitter:8081`,
`http://lyrics:8080`, and `http://waveform:8080`; Compose sets the Streaming
one to `http://streaming:8081`.

`POST /playlists/{playlist_id}/play/next` fetches and appends the next three
minutes of the current song to the same authenticated client's ring buffer.
Call the initial `/play` endpoint first. Subsequent calls resume from the
buffered offset and stop at the song duration when waveform metadata provides
it. The response contains the updated playback buffers. Sessions are held in
memory per client and playlist, so they reset when the service restarts. With
With Auth enabled the client key is the verified user ID; with Auth disabled,
send the same stable `X-Client-ID` header to both playback requests.

## Run

From this directory (the targets drive the root `docker-compose.yml`, which
also starts PostgreSQL and the services the orchestrator calls):

```sh
make up
make status
make logs
make down
```

`curl http://localhost:8080/api/orchestrator/health` answers `OK` through the
gateway. The orchestrator itself publishes no port.

The database connection comes from `DATABASE_URL` if it is set, otherwise from
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER` and `DB_PASSWORD` (Compose uses
these, and so does AWS, where the password comes from Secrets Manager). The
service opens its connection pool at startup and exits if the database is not
reachable. The local database is created by `infrastructure/postgres/init.sql`;
an existing local Postgres volume needs `docker compose down -v` once to get
it.

## Security / Authentication

The service verifies the RS256 session JWT issued by the project's Auth
Service. Authentication is enabled when `AUTH_JWKS_URL`
is configured; the included Compose file points it directly at the Auth
service on the root Compose network. The orchestrator remains available
through the gateway at `/api/orchestrator/*`.

- `AUTH_JWKS_URL` - Auth's public signing-key endpoint.
- `AUTH_ISSUER` - expected issuer (default `syncwave-auth`).
- `AUTH_AUDIENCE` - expected audience (default `syncwave`).
- `AUTH_JWKS_TTL_SECS` - key refresh interval (default `3600`).

Every route except `GET /health` accepts the frontend's HttpOnly
`syncwave_session` cookie. `Authorization: Bearer <token>` is also supported
for service clients. Signature, issuer, audience, expiry, issue time, and
subject are validated against Auth's JWKS.

The middleware is built with actix-web's middleware traits (`Transform` and
`Service`) and the authenticated user ID is passed to handlers as a request
parameter through the `UserId` extractor:

```rust
use crate::security::UserId;

async fn me(user_id: UserId) -> impl Responder {
    format!("authenticated as {}", user_id.0)
}
```

`GET /me` is an example protected route that returns the caller's SyncWave
account ID. The full set of verified claims is available through the
`AuthClaims` extractor. Login and signup remain owned by `/api/auth/login` and
`/api/auth/signup`; the orchestrator does not handle passwords.

## Test

```sh
make test
```

This runs the Rust test suite in Docker; the tests need no database.
`make clean` stops and removes the orchestrator container.
