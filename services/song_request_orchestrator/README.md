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

## Test

```sh
make test
```

This runs the Rust test suite in Docker. `make clean` also removes the local
database volume.
