# Sync Service

**Owner:** Azeez · **Language/framework:** Python 3.12 / FastAPI

Sync is the playback-coordination extension of Jam. Jam owns rooms,
membership, the shared queue, and user-facing playback controls. After Jam
authorizes an owner action, it activates Sync with an internal command. Sync
then coordinates clocks, readiness, scheduled playback, and drift correction.

## Current vertical slice

- `GET /health` and `GET /ready`
- Generated `SyncControlService` gRPC server on internal port `50051`, with
  authenticated start, pause, resume, seek, skip, readiness-decision, and
  state/readiness query RPCs
- `POST /internal/v1/sessions` remains as temporary HTTP compatibility for
  integration before Jam adopts the generated gRPC client
- `GET /internal/v1/sessions/{jam_id}` returns the current playback snapshot
  for Jam while the temporary HTTP adapter is in use
- `GET /internal/v1/sessions/{jam_id}/readiness` lets Jam determine whether
  the preparation deadline expired and which participants remain unready
- `POST /internal/v1/sessions/{jam_id}/readiness-decision` accepts an
  authenticated owner decision forwarded by Jam: `CONTINUE`, `WAIT`, or
  `CANCEL`
- Authenticated temporary Jam adapters for `pause`, `resume`, `seek`, and
  `skip`; each persists the authoritative timeline before broadcasting
  `PAUSE_AT`, `RESUME_AT`, `SEEK_TO`, or a new-generation `PREPARE`
- `WS /ws` accepts registered mock participants
- `JOINED`, `TIME_PING`, `TIME_PONG`, `PREPARE`, `READY`,
  `PARTICIPANT_STATE`, `PLAY_AT`, `PAUSE_AT`, `RESUME_AT`, `SEEK_TO`,
  `PLAYBACK_STATUS`, `SYNC_CORRECTION`, and structured `ERROR` messages
- Per-participant sequence-number and playback-generation validation
- Shared future start timestamp after every participant becomes ready
- Configurable drift bands using rate adjustment or a scheduled seek
- Per-participant correction hysteresis and cooldown suppress repeated
  commands while still allowing a rate correction to escalate to a seek
- Reconnecting scheduled clients receive the original `PLAY_AT`; clients
  joining during playback receive a new future catch-up time and calculated
  authoritative position without restarting the room
- PostgreSQL persistence for session generation, playback state, selected
  song, authoritative timeline, participants, and idempotent Jam request IDs
- Restart recovery: live sockets reconnect, while the authoritative timeline
  is restored from the Sync database
- Preparation timeout flow remains behind Jam: Sync reports readiness, Jam
  prompts the owner, and only Jam forwards the resulting decision
- Catalogue and Streaming client interfaces guard start/skip before any state
  mutation; local fakes return ready media by default and support not-found,
  processing, unavailable, and delayed responses for deterministic tests
- Each dependency call has a configurable 750 ms timeout. HTTP and gRPC map
  not-found, not-ready, unavailable, and timeout failures separately, and no
  false `PREPARE` is emitted on failure

The versioned gRPC contract is in
`contracts/grpc/syncwave/sync/v1/sync.proto`; generated Python bindings are
checked into `src/syncwave/sync/v1/`. Jam authenticates with the
`x-internal-token` metadata field. Invalid inputs, missing sessions, invalid
state, stale generations, and expired client deadlines map to stable gRPC
status codes.

## Run and try it

```sh
docker compose up -d --build --wait
curl http://localhost:8080/api/sync/health
```

Activate a session as the mock Jam Service:

```sh
curl -X POST http://localhost:8080/api/sync/internal/v1/sessions \
  -H "Content-Type: application/json" \
  -H "X-Internal-Token: local-jam-to-sync-token" \
  -d '{"request_id":"11111111-1111-4111-8111-111111111111","jam_id":"22222222-2222-4222-8222-222222222222","queue_item_id":"33333333-3333-4333-8333-333333333333","song_id":"44444444-4444-4444-8444-444444444444","owner_id":"55555555-5555-4555-8555-555555555555","participant_ids":["55555555-5555-4555-8555-555555555555"]}'
```

Connect a WebSocket client to:

```text
ws://localhost:8080/api/sync/ws?jam_id=22222222-2222-4222-8222-222222222222&participant_id=55555555-5555-4555-8555-555555555555&token=local-sync-participant-token
```

For a local end-to-end timing check, open `/demo?slot=1` through
`/demo?slot=5` in five browser sessions after activating the fixed demo Jam.
Each page buffers the generated 16-second test melody, takes five clock
samples, reports readiness, schedules the Web Audio source from `PLAY_AT`, and
shows its measured timer-start error. This is a development harness rather
than the production Jam UI.

### Five-browser timing result

On 13 October 2026, five isolated headless Chromium sessions on one Windows
host completed the flow against the local Sync service. All clients received
the same target server timestamp and remained in `PLAYING` after their first
`PLAYBACK_STATUS` report.

| Browser | Clock offset | Timer-start error |
| --- | ---: | ---: |
| 1 | +0.5 ms | 1 ms |
| 2 | +0.5 ms | 12 ms |
| 3 | -0.5 ms | 9 ms |
| 4 | -0.5 ms | 15 ms |
| 5 | -0.5 ms | 7 ms |

The observed max-to-min start-error spread was **14 ms**, within the current
100 ms target. This proves the browser scheduling path on local loopback; it
does not replace a later test across five physical devices and real Wi-Fi,
where audio hardware latency and network asymmetry will differ.

## Test

```sh
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/pytest
```

Regenerate the checked-in Python bindings after changing `sync.proto`:

```sh
python -m grpc_tools.protoc \
  -I ../../contracts/grpc \
  --python_out=src \
  --grpc_python_out=src \
  ../../contracts/grpc/syncwave/sync/v1/sync.proto
```

## Persistence

Compose uses Sync's existing isolated PostgreSQL database. Tables are created
idempotently during service startup for the current project phase. Tests use
SQLite through the same repository interface and include a service-restart
recovery test.

## Deliberate limitations of this slice

- Temporary internal HTTP compatibility remains until Jam switches fully to
  the generated gRPC client.
- Database migrations are not versioned yet; add Alembic before schemas begin
  changing across deployed versions.
- Catalogue and Streaming currently use deterministic local fakes because
  their versioned contracts/services are not present in this repository yet;
  replace the fake implementations behind the existing interfaces when those
  contracts land.
- Mock tokens are local-development values only.
