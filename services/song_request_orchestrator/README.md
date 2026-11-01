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

The endpoint is protected by Cognito whenever authentication is configured.
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
Cognito enabled the client key is the verified user ID; with Cognito disabled,
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

The service optionally verifies JWTs issued by Amazon Cognito through an
actix-web middleware (`src/security`). Authentication is enabled when the
following environment variables are set; otherwise the service runs
unauthenticated (suitable for local development):

- `COGNITO_REGION` (or `AWS_REGION`) - AWS region, **required**.
- `COGNITO_USER_POOL_ID` - **required**.
- `COGNITO_CLIENT_ID` - **required**.
- `COGNITO_DOMAIN` - optional Cognito domain prefix, enables token issuance.
- `COGNITO_ISSUER` - optional issuer URL override.
- `COGNITO_JWKS_TTL_SECS` - JWKS cache TTL in seconds (default `3600`).

When enabled, every route except `GET /health` requires an
`Authorization: Bearer <token>` header. Tokens are verified against Cognito's
JWKS endpoint (`.../.well-known/jwks.json`): signature (RS256), issuer,
audience (`COGNITO_CLIENT_ID`) and expiration are validated.

The middleware is built with actix-web's middleware traits (`Transform` and
`Service`) and the authenticated user ID is passed to handlers as a request
parameter through the `UserId` extractor:

```rust
use crate::security::UserId;

async fn me(user_id: UserId) -> impl Responder {
    format!("authenticated as {}", user_id.0)
}
```

`GET /me` is an example protected route that returns the caller's Cognito user
ID. The full set of verified claims is also available via the `CognitoClaims`
extractor.

Tokens can be obtained with `CognitoClient::authenticate_password`, which calls
the Cognito token endpoint
(`https://{domain}.auth.{region}.amazoncognito.com/oauth2/token`) using the
`password` grant. The app client must allow the `PASSWORD` grant and must not
have a client secret.

## Test

```sh
make test
```

This runs the Rust test suite in Docker; the tests need no database.
`make clean` stops and removes the orchestrator container.
