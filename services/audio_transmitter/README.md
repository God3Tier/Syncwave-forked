# Audio Sampler (audio_transmitter)

The audio sampler HTTP service listens on port `8081` and exposes `GET /cache`.
Its Compose stack includes its own PostgreSQL database and passes AWS settings
through to the service.

## Run

From this directory:

```sh
make up
make status
make logs
make down
```

The database is published on port `5433` by default so it can run alongside the
orchestrator stack. Set `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, and
`POSTGRES_PASSWORD` to override the database defaults. AWS credentials and
`AWS_REGION` can be set in the environment or a local `.env` file.

## Test

```sh
make test
```

This runs the Rust test suite in Docker against a disposable PostgreSQL
container. `make clean` also removes the local database volume.
