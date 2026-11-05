# SyncWave

A browser-based social music streaming platform built as microservices
(CS302 DevOps Principles & Practices, G4 Team 6). The three key scenarios
are **Discover & Listen**, **Upload & Process** (event-driven
choreography) and **Create & Synchronise a Jam** (orchestration).
See [plan.md](plan.md) for the architecture and service ownership.
See [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md) for verified integration status,
remaining work, and acceptance criteria.
See [DESIGN.md](DESIGN.md) for the implemented visual system and
[FRONTEND_PLAN.md](FRONTEND_PLAN.md) for the implemented nine-slot audio buffer,
usability requirements, and Playwright coverage.
See [infrastructure/aws/DEPLOYMENT.md](infrastructure/aws/DEPLOYMENT.md) for
the AWS deployment sequence, current gaps, and production readiness gates.

## Run it locally

**Prerequisites:** Docker Desktop (or Docker Engine) with Compose
**v2.24 or newer** (`docker compose version`). Nothing else: no AWS
account, no local Java/Node/Python.

```sh
docker compose up -d --build --wait
```

`--wait` returns once every container is healthy. Then open:

| What                       | URL                                          | Login                       |
|----------------------------|----------------------------------------------|-----------------------------|
| SyncWave (via the gateway) | <http://localhost:8080>                      |                             |
| A service's API            | `http://localhost:8080/api/<service>/...`    |                             |
| RabbitMQ management        | <http://localhost:15672>                     | `syncwave` / `syncwave`     |
| S3 console (RustFS)        | <http://localhost:9001/rustfs/console/>      | `syncwave` / `syncwave-secret` |
| Postgres                   | `localhost:5432`                             | `postgres` / `postgres`; per service `<name>` / `<name>` |

Check that everything is wired up, then run Scenario 2 end to end (upload,
parallel processing, Catalogue, Streaming) without the browser:

```sh
sh tests/integration/smoke.sh
python tests/integration/upload-flow.py   # Python 3.10+; adds one test song per run
```

The stack starts with five public-domain demo songs already loaded (see
[infrastructure/seed](infrastructure/seed/README.md)): "Daisy Bell", an 1894
recording with synced lyrics, and one song for each mood Recommendation
matches to the weather (calm, mellow, upbeat, energetic). They are READY a
few seconds after `--wait` returns.

### Try the three scenarios

All three run in the browser at <http://localhost:8080>.

1. **Discover & Listen.** Discover lists recommendations and recently
   added songs; Search finds songs by title or artist. Open "Daisy Bell"
   and press Play: the waveform playhead moves and the current lyric line
   is highlighted, and the live visualiser below moves with the music.
   Switch "For you right now" from General to "Match weather" to put songs
   whose mood suits the weather first. It uses your browser location, or a
   city you pick (browsers only share a location over HTTPS or localhost).
2. **Upload & Process.** On Upload, add a title, an artist, an audio file
   and optionally an `.lrc` file and a mood. The processing panel shows
   Lyrics and Waveform working in parallel until the song is READY; it then
   appears in Search and Discover.
3. **Create & Synchronise a Jam.** Listening stays open to guests. Create an
   account with a username and password to save playlists or host a Jam. Open
   the invite link in a second tab or on another device to join as a guest;
   guests can add songs to the shared queue. Tap "enable audio" on every
   device, then press Play as the owner. Each device buffers the song and
   starts it at the same server time. The Sync stats panel shows the clock
   offset and start error.

Stop with `docker compose down`, and add `-v` to also delete all local
data (databases, queues, uploaded audio).

If a port is already taken (e.g. a local Postgres on 5432), stop that
program or change the left-hand port in `docker-compose.yml`.

## Repository layout

```text
contracts/        shared contracts: REST (OpenAPI), AMQP events, gRPC, WebSocket
services/<name>/  one folder per microservice, each with Dockerfile, compose.yaml, .gitlab-ci.yml
services/_template/  starting point for a new service
frontend/         web UI
infrastructure/   gateway (nginx), RabbitMQ topology, Postgres init, AWS notes
ci/               shared CI job templates and scripts
tests/            integration (smoke) and end-to-end tests
docker-compose.yml  local environment: infrastructure + `include:` of every service
.gitlab-ci.yml    parent pipeline: decides which service pipelines run
```

## Local conventions

- Every service listens on **8080** inside its container (**50051** for
  gRPC) and answers `GET /health`. `/api/<service>/<path>` reaches
  `<service>:8080/<path>`. The exception is Streaming
  (`services/audio_transmitter`): it listens on **8081** and the gateway
  routes it as `/api/streaming/...`.
- The gateway is the only service published on the host, apart from
  Streaming on 8081 and the infrastructure consoles in the table above.
- Infrastructure hostnames inside Compose: `rabbitmq:5672`,
  `postgres:5432`, `s3:9000`.
- Each service has its **own** Postgres database and cannot connect to
  anyone else's ([init.sql](infrastructure/postgres/init.sql)).
- The RabbitMQ exchanges, queues, retry queues and DLQs are created from
  [definitions.json](infrastructure/rabbitmq/definitions.json); see
  [contracts/events](contracts/events/README.md).

## Workflow

```text
feature/*, feat/*, fix/* or chore/*  --MR-->  dev  --MR-->  staging  --MR-->  main
```

Branch prefixes: `feature/` or `feat/` for new behaviour, `fix/` for bug
fixes, `chore/` for tooling, docs and follow-ups.

- `dev` is the default branch; nobody pushes to `dev`, `staging` or
  `main` directly.
- **Merge request:** lint, test and build only the services that changed,
  plus contract checks, SAST and secret detection. The image is built once
  here and tagged by its content.
- **dev:** the same checks again, plus container scanning of the
  (reused) images.
- **staging:** the full stack starts inside CI from the already-built
  images, then the smoke test and the Scenario 2 flow (`upload-flow.py`)
  run against it.
- **main:** each changed service is deployed to production (Amazon ECS).

CI minutes are shared by every CS302 team: open a draft MR to get
pipelines, and avoid pushing many tiny commits in a row (each push to an
open MR runs a pipeline; a newer push cancels the older one).

## Adding a service

1. Copy `services/_template/` to `services/<name>/` and follow the
   checklist at the bottom of its README.
2. Add `- services/<name>/compose.yaml` to `include:` in `docker-compose.yml`.
3. Its trigger job in `.gitlab-ci.yml` already exists and starts running
   as soon as `services/<name>/.gitlab-ci.yml` is committed.
