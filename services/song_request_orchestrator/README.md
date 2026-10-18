# Orchestrator

The orchestrator HTTP service listens on port `8080` and exposes `GET /health`.
Its Compose stack includes its own PostgreSQL database.

## Run

From this directory:

```sh
make up
make status
make logs
make down
```

The database is published on port `5432` by default. Set `POSTGRES_PORT`,
`POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` in the environment or a
local `.env` file to override the defaults.

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

This runs the Rust test suite in Docker. `make clean` also removes the local
database volume.
