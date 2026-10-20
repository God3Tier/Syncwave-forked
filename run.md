# Running Jam and Sync

This guide starts the Jam and Sync services together and exercises the main
room, queue, and playback flow. Run commands from the repository root unless
the section says otherwise.

## Requirements

- Docker Desktop with Docker Compose v2.24 or newer
- Git
- Python 3.12 only if running tests or services outside Docker

Use the `jam` branch to run both services:

```powershell
git switch jam
```

## Recommended: Docker Compose

Start Jam, Sync, PostgreSQL, the gateway, and shared local infrastructure:

```powershell
docker compose up -d --build --wait
docker compose ps
```

Check both services through the browser-facing gateway:

```powershell
Invoke-RestMethod http://localhost:8080/api/jam/health
Invoke-RestMethod http://localhost:8080/api/sync/health
Invoke-RestMethod http://localhost:8080/api/jam/ready
Invoke-RestMethod http://localhost:8080/api/sync/ready
```

View logs when something fails:

```powershell
docker compose logs --follow jam sync
```

Stop the stack without deleting its databases:

```powershell
docker compose down
```

Delete all local Compose data and start clean:

```powershell
docker compose down -v
```

The `-v` command permanently removes the local PostgreSQL, RabbitMQ, and S3
volumes.

## Try the Jam flow

The following PowerShell creates one owner and one member, lets the member
queue a song, and lets only the owner start playback.

```powershell
$baseUrl = "http://localhost:8080/api/jam"
$headers = @{ "X-Jam-Token" = "local-jam-member-token" }
$ownerId = [guid]::NewGuid().ToString()
$memberId = [guid]::NewGuid().ToString()
$songId = [guid]::NewGuid().ToString()

$jam = Invoke-RestMethod `
  -Method Post `
  -Uri "$baseUrl/jams" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body (@{ owner_id = $ownerId } | ConvertTo-Json)

$jamId = $jam.jam_id

Invoke-RestMethod `
  -Method Post `
  -Uri "$baseUrl/jams/$jamId/members" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body (@{ participant_id = $memberId } | ConvertTo-Json)

Invoke-RestMethod `
  -Method Post `
  -Uri "$baseUrl/jams/$jamId/queue" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body (@{ actor_id = $memberId; song_id = $songId } | ConvertTo-Json)

$playback = Invoke-RestMethod `
  -Method Post `
  -Uri "$baseUrl/jams/$jamId/playback/start" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body (@{ actor_id = $ownerId; request_id = [guid]::NewGuid().ToString() } | ConvertTo-Json)

$playback
```

The response should show `state` as `PREPARING`, a `sync_generation` of `1`,
and the member-added queue item. Jam has called Sync over authenticated gRPC
at this point.

Retrieve the latest state from Sync through Jam:

```powershell
Invoke-RestMethod `
  -Uri "$baseUrl/jams/$jamId" `
  -Headers $headers
```

Jam reconciles its stored playback state with Sync when this endpoint is
called.

## Browser connections

Jam broadcasts room and queue changes at:

```text
ws://localhost:8080/api/jam/jams/{jam_id}/ws?participant_id={participant_id}&token=local-jam-member-token
```

After playback starts, each registered participant connects to Sync at:

```text
ws://localhost:8080/api/sync/ws?jam_id={jam_id}&participant_id={participant_id}&token=local-sync-participant-token
```

The expected Sync flow is:

```text
JOINED -> PREPARE -> READY -> PLAY_AT
```

Clients must continue sending `TIME_PING` or playback-status messages. Sync
closes inactive WebSockets after 45 seconds. Owner actions are sent to Jam's
HTTP playback endpoints; browsers must not send owner commands directly to
Sync.

There is not yet a production Jam frontend. The APIs, WebSockets, automated
tests, and Sync demo harness are available, but a user-facing room screen
still needs to be connected to them.

## Run the automated tests

### Sync

```powershell
Set-Location services/sync
py -3.12 -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/ruff check src tests
.venv/Scripts/ruff format --check src tests
.venv/Scripts/pytest
Set-Location ../..
```

### Jam

```powershell
Set-Location services/jam
py -3.12 -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/ruff check src tests
.venv/Scripts/ruff format --check src tests
.venv/Scripts/pytest
Set-Location ../..
```

Current expected result:

```text
Sync: 46 tests passed
Jam:  8 tests passed
```

## Run without Docker

Use two PowerShell terminals after installing each service's development
requirements as shown above.

Terminal 1 — Sync:

```powershell
Set-Location services/sync
$env:PYTHONPATH = "src"
$env:DATABASE_URL = "sqlite+aiosqlite:///./sync-local.db"
$env:GRPC_PORT = "50051"
.venv/Scripts/python -m uvicorn sync_service.main:app --host 127.0.0.1 --port 18081
```

Terminal 2 — Jam:

```powershell
Set-Location services/jam
$env:PYTHONPATH = "src"
$env:DATABASE_URL = "sqlite+aiosqlite:///./jam-local.db"
$env:SYNC_GRPC_TARGET = "127.0.0.1:50051"
.venv/Scripts/python -m uvicorn jam_service.main:app --host 127.0.0.1 --port 18082
```

When running this way, use `http://127.0.0.1:18082` as the Jam base URL and
`http://127.0.0.1:18081` as the Sync base URL.

## Current media limitation

Catalogue and Streaming have not yet implemented the shared UUID-based media
gRPC contract. Sync therefore uses deterministic media fakes when
`CATALOGUE_GRPC_TARGET` and `STREAMING_GRPC_TARGET` are blank. Jam-to-Sync
coordination works, but real audio streaming requires those services to adopt
`contracts/grpc/syncwave/media/v1/media.proto`.
