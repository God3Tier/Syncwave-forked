# Item 4 execution steps

Backend scenario code, fault automation and CI configuration are provided.
New scenarios still need actual PASS reports. Browser work stays deferred;
physical-device acceptance needs measured evidence from real devices.
No script can establish audible synchronization from server schedules alone.

## 1. Start the backend stack

Use Docker Desktop in Linux-container mode and a quiet disposable local
stack. The fault runner stops S3 and selected workers, restarts Playlist and
pauses Playlist briefly. Run scenarios sequentially with no other uploads.
It does not remove volumes or consume/purge another service's queue.

From the repository root in Windows PowerShell:

```powershell
docker compose build upload catalogue lyrics waveform audio_transmitter search recommendation playlist sync jam
docker compose -f docker-compose.yml -f tests/integration/ingestion.compose.yaml up -d --wait --wait-timeout 180 gateway upload upload-publisher catalogue catalogue-worker lyrics lyrics-worker waveform waveform-worker audio_transmitter search search-worker recommendation playlist sync jam
```

All Python commands below use the existing Upload virtual environment. Any
Python 3.11+ interpreter also works for the host fault runner and CSV summary.
The CI configuration audit additionally needs `PyYAML==6.0.3` (already present
in this workspace's Upload virtual environment).

## 2. Run the ingestion and playback/reconnect scenarios

The ingestion scenario provides duplicate-event and failed-lyrics recovery
coverage and has already passed locally. Run it again when validating the
complete suite or after relevant changes:

```powershell
docker compose cp tests/integration/upload-flow.py upload:/tmp/upload-flow.py
docker compose cp tests/integration/ingestion-flow.py upload:/tmp/ingestion-flow.py
docker compose exec -T upload python /tmp/ingestion-flow.py --report /tmp/ingestion-flow-report.json
$LASTEXITCODE
docker compose cp upload:/tmp/ingestion-flow-report.json tests/integration/ingestion-flow-report.json
```

Run the backend scenario with the new reconnect check:

```powershell
docker compose cp tests/integration/upload-flow.py jam:/tmp/upload-flow.py
docker compose cp tests/integration/backend-flow.py jam:/tmp/backend-flow.py
docker compose exec -T jam python /tmp/backend-flow.py --check-reconnect --report /tmp/backend-flow-report.json
$LASTEXITCODE
docker compose cp jam:/tmp/backend-flow-report.json tests/integration/backend-flow-report.json
```

The optional flag disconnects the member after the scheduled start and
reconnects the same participant. It checks the generation, forward catch-up
position and future catch-up schedule, while observing the owner's socket
for unexpected restart/pause/seek/error frames. The report records recovery
time and `owner_undisturbed`. These remain protocol checks, not audible tests.

## 3. Run the fault/recovery scenarios

Run this on the **host**, where Docker CLI is available:

```powershell
.\services\upload\.venv\Scripts\python.exe tests/integration/failure-recovery.py --report tests/integration/failure-recovery-report.json
$LASTEXITCODE
```

It exercises six scenarios, stopping at the first failure:

| Scenario | Trigger and required outcome |
| --- | --- |
| `corrupt_audio` | Upload a recognizable but corrupt WAV; real ffmpeg decoding fails with `AUDIO_UNDECODABLE`. Valid lyrics become READY and Catalogue becomes PARTIAL. |
| `s3_outage` | Stop S3; a fresh upload returns 503/`STORAGE_UNAVAILABLE`, its receipt is FAILED with zero publish attempts, and no Catalogue song exists. Restore S3 and verify a fresh song processes and downloads correctly. |
| `publisher_restart` | Stop the publisher, accept a durable PENDING receipt, restart the publisher and verify the same event ID becomes PUBLISHED and the song reaches READY. |
| `worker_restart` | Stop Lyrics/Waveform workers, publish a fixture and observe its unfinished Catalogue state. Restart both workers and verify the same song reaches READY with matching lyrics, waveform and audio bytes. |
| `playlist_and_timeout` | Create a playlist, restart Playlist and compare its persisted content/order. Pause the real dependency after warming Jam's gRPC channel; require a bounded 503 timeout. Unpause it and verify Jam can import the playlist again. |
| `owner_permissions` | Start an active Jam with owner/member IDs. Member start/pause/resume/seek/skip requests must each return 403 and preserve the room state/generation. |

The runner checks that every disruption target is initially running. It tracks
stopped/paused services before each command and restores them in `finally`,
including normal errors and Ctrl+C. It deletes only its own playlist. A forced
process kill or machine shutdown can prevent cleanup; restore any interrupted
targets before rerunning:

```powershell
docker compose unpause playlist
docker compose start s3 upload-publisher lyrics-worker waveform-worker playlist
```

Unpause is only needed when Playlist is actually paused; Docker may report
an error when it is already running normally. The normal runner handles this
through its recorded target set.

Use `--project-name <name>` if testing a separately named Compose project.
The base URL must point at that project's gateway. Creating another project
does not change the root stack's fixed host ports; stop a conflicting local
stack before starting a second one.

Expected outcome is exit code 0, report `result: PASS`, all six checks PASS,
and `cleanup.services_restored_and_playlists_deleted: true`. Failure reports
include completed checks and known fixture IDs. Generated songs, objects,
Jams and the corrupt-audio DLQ entry remain for inspection; there is no shared
song/Jam deletion API. Nothing is reset or purged to repeat the tests.

For diagnosis, save logs and inspect the report before stopping containers:

```powershell
docker compose logs --no-color --timestamps upload upload-publisher catalogue-worker lyrics-worker waveform-worker playlist jam sync
Get-Content tests/integration/failure-recovery-report.json
```

Copy the two container reports in step 2 before `docker compose down`; the
fault report is already on the host.

## 4. Verify unit suites in GitLab CI

The new `ci:test-coverage` validation job discovers deployed application build
contexts from root Compose and included files. For each application it checks
that a parent trigger waits for a child pipeline, the child has a blocking
test command, and failure results are retained as JUnit or log artifacts.
It resolves this repository's local `ci/service.yml` inheritance. It does not
execute unit tests or replace GitLab's full CI lint and pipeline evaluation.

Run the same read-only configuration audit locally:

```powershell
.\services\upload\.venv\Scripts\python.exe ci/scripts/check-test-coverage.py --report tests/integration/ci-test-coverage-report.json
$LASTEXITCODE
```

If using another environment without PyYAML, install the pinned dependency
into that environment first: `python -m pip install PyYAML==6.0.3`.

After an authorized push, run a manual branch pipeline to exercise every
existing service child pipeline. Check actual unit-job results and JUnit/log
artifacts; save the successful pipeline URL in the integration plan. Then
verify staging's integration job against registry images. It runs smoke,
ingestion, backend/reconnect and the host fault runner in that order. The
host runner uses `http://docker:8080` to reach Docker-in-Docker's published
gateway. Its report is retained with the existing scenario reports and logs
for one week. An earlier failure skips later scenarios; a missing later
report is not a passing result.

## 5. Browser tests (deferred)

When frontend work resumes, integrate the teammate's frontend, add browser
tests for the three journeys in `tests/e2e/README.md`, and implement
`tests/e2e/run.sh` with a nonzero failure exit and retained screenshots/traces.
The existing staging hook remains optional. This work is not completed by
the backend scripts, and its plan checkbox must stay open.

## 6. Record physical-device evidence

Follow `services/sync/OBSERVABILITY.md` with at least one laptop and two
phones on the same documented Wi-Fi. Open the Sync demo through the laptop's
LAN address on port 8080 and follow its setup controls. Record device/browser
versions, network configuration and five completed clock samples per device.

Create blank working copies of the supplied headers (do this once):

```powershell
if (-not (Test-Path tests/integration/physical-sync-starts.csv)) { Copy-Item tests/integration/physical-sync-starts.template.csv tests/integration/physical-sync-starts.csv }
if (-not (Test-Path tests/integration/physical-sync-events.csv)) { Copy-Item tests/integration/physical-sync-events.template.csv tests/integration/physical-sync-events.csv }
```

Perform at least 20 fresh starts. Fill one starts row per device per run:

- Use `device_type` values `laptop` and `phone`, with unique device IDs.
- Record at least five completed `clock_samples` for every device/run.
- Use `measurement_method` = `external_audio_recording` and measure each
  device's audible start against a common recording/time reference for that
  run. Document the measurement setup and account for microphone placement,
  propagation and recording-channel offsets. Store the recording reference
  in `evidence_ref`; every device in a run must share that reference.
- Keep browser `timer_start_error_ms` separate from audible timing. Record
  maximum absolute drift and correction counts from the client observations.
- Record at least one `delayed_client` and one `reconnect` event in the events
  CSV, using existing run/device IDs. Include measured recovery time, absolute
  drift after recovery, `room_timeline_restarted` (`true`/`false`) and evidence.
- Retain network/jitter settings and notes alongside the recordings. Repeat
  a subset with injected latency/jitter/loss where the environment supports it.

Summarize real, filled-in measurements:

```powershell
.\services\upload\.venv\Scripts\python.exe tests/integration/summarize-sync-measurements.py --starts tests/integration/physical-sync-starts.csv --events tests/integration/physical-sync-events.csv --report tests/integration/physical-sync-report.json
$LASTEXITCODE
```

The analyzer requires 20 runs, a laptop/two phones per run, both recovery
event types and recording references. It reports audible P50/P95/max spread
separately from timer spread. Default targets follow the Sync runbook: audible
P95 spread at most 100 ms, recovery drift at most 80 ms and no room restart.
Use `--start-spread-target-ms` and `--recovery-drift-target-ms` only if the team
has agreed different targets; record the chosen values with the evidence.
Missing data yields INCOMPLETE, missed targets yield FAIL, and only a complete
passing dataset yields exit code 0. Headers contain no sample measurements.
CSV declarations/references are user-supplied; review the actual recordings
and experimental setup as part of acceptance.

Also export diagnostics:

```powershell
curl.exe --fail --silent --show-error http://localhost:8080/api/sync/metrics -o tests/integration/physical-sync-metrics.txt
docker compose logs --no-color --timestamps sync > tests/integration/physical-sync-logs.txt
```

## 7. Complete the plan using evidence

Record local PASS run IDs and the successful unit/staging pipeline links in
`INTEGRATION_PLAN.md`. Check the failure/recovery group only after both the
new reconnect scenario and all fault checks pass. Check physical validation
only after reviewing the measurements and recordings. Browser coverage stays
pending until frontend tests exist and pass. Item 4 as a whole remains open
while any required gate is deferred or lacks measured evidence.
