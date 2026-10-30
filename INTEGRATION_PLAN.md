# Remaining integration work

Updated: 30 October 2026. Baseline branch: `feat/streaming-sync-integration`.

## Verified baseline

The root Compose stack currently includes Catalogue, Lyrics, Waveform,
Playlist, Recommendation, Jam, Sync, and Streaming (`audio_transmitter`),
plus the gateway, PostgreSQL, RabbitMQ, and S3-compatible storage.

The following checks passed locally:

- All deployed API and infrastructure checks in `tests/integration/smoke.sh`.
- A generated eight-second WAV and LRC file were stored in S3; a manually
  published `SongUploaded` event drove Lyrics and Waveform to `READY`, and
  Catalogue recorded the measured duration and overall `READY` state.
- Playlist creation and song insertion, followed by Jam creation from that
  playlist and playback preparation through Sync's real dependencies.
- Two WebSocket clients connected through the gateway and received identical
  `PLAY_AT` payloads.
- Streaming downloaded 352,844 valid WAV bytes through the gateway after its
  S3 client was changed to path-style requests.
- Sync's local test suite and Jam's 11 tests passed.

These were backend checks. The generated fixture bypassed the missing Upload
service, and the WebSocket clients did not measure audible browser playback.
The other services' complete unit suites were not rerun during this check.

## 1. Make startup and CI reliable

- [x] Verify RabbitMQ startup with fresh volumes and restart with retained
  data. Isolated checks using `rabbitmq:4.3-management-alpine`, including the
  Compose diagnostics health check, started successfully with a cookie owned
  by `rabbitmq` and required no permission repair. The earlier root-owned
  cookie failure did not recur; its cause remains unconfirmed. Capture the
  volume ownership and health-check timing if it returns, before adding a
  workaround. These checks did not delete or reset the main stack's data.
- [x] Resolve `docker compose up --wait` failing with
  `catalogue-worker has no healthcheck configured`. All three workers now
  use a shared Compose probe that checks RabbitMQ for this container's named
  connection and consumers on every required queue. Existing-volume startup,
  a negative check against another worker's queue, smoke checks, and processing
  a fresh generated song to `READY` passed. Clean-volume RabbitMQ startup
  was checked separately using isolated broker containers and volumes.
- [x] Wire Streaming's container image into the shared publishing pipeline and
  configure its Compose `image` consistently with `IMAGE_REGISTRY` and
  `IMAGE_TAG`. The pipeline now runs the shared build after the Rust tests,
  and Compose uses the matching registry image name. Local YAML/Compose checks
  and a simulated registry build/tag check passed; actual publishing remains
  to be verified by GitLab CI.
- [ ] Verify Streaming's image is published by GitLab CI, then run the complete
  staging integration job against registry images. Live CI verification is
  intentionally pending: the saved Git credential received HTTP 403 from the
  API, and the automation browser was signed out. Local configuration and
  simulated publishing checks do not prove a successful registry push.

Acceptance: a fresh environment and a restart with existing volumes both
complete the documented startup command, pass smoke checks, and process a
fixture. Staging pulls every application image and passes the same checks.
Use an isolated Compose project for clean-volume verification.

## 2. Complete song ingestion and discovery

- [ ] Implement or bring in the Upload service, add it to root Compose, and
  verify its existing gateway route. Validate uploads, store audio and lyrics,
  and publish the agreed `SongUploaded` event with matching object references.
- [ ] Automate the fixture flow already exercised manually: upload, wait for
  Catalogue readiness, retrieve lyrics/waveform, and download the actual audio.
- [ ] Implement or connect Search if the Discover journey requires it. Its
  gateway route exists, but no Search service is included in this branch.
  Verify indexing from `SongReady`, including duplicate delivery handling.
- [ ] Decide whether weather-based ranking requires Catalogue mood metadata.
  Recommendations work without it, but the current Song response omits the
  mood used for weather matching. Agree any contract change before adding it.

Acceptance: a user can submit a new song through the public API, discover it
after processing, and retrieve playable audio with its lyrics and waveform.
Failed processing produces a clear status and has a documented retry path.

## 3. Connect the frontend and settle playback orchestration

- [ ] Add or integrate the production frontend and its Compose service. The
  gateway currently forwards `/` to a frontend hostname that is absent.
- [ ] Connect discovery, upload status, playlists, and playback to gateway APIs.
- [ ] Connect Jam room membership, queue updates, owner controls, and the Sync
  WebSocket protocol, including clock sampling, buffering, readiness, scheduled
  playback, drift correction, reconnects, and readiness-timeout decisions.
- [ ] Confirm the role of `song_request_orchestrator` alongside Jam/Sync.
  It currently has a standalone Compose file and is absent from the root stack.
  If it remains part of individual playlist playback, connect its upstreams,
  gateway route, image pipeline, and configuration. Its standalone host ports
  overlap the root gateway/PostgreSQL defaults and need adjustment.
- [ ] Verify seeking and buffering with real audio formats. Streaming currently
  buffers whole objects and reports `supports_ranges=false`; decide whether
  browser playback requires HTTP byte ranges before implementing them.

Acceptance: the three documented user journeys work through the production UI,
including actionable errors when a dependency or processing stage fails.

## 4. Turn manual evidence into repeatable scenario tests

- [ ] Add a backend scenario test using generated audio/lyrics and unique IDs.
  Assert processing results, playlist order copied into Jam, real audio bytes,
  and identical scheduled starts for two participants. Document fixture cleanup.
- [ ] Implement `tests/e2e/run.sh` and browser tests for Discover & Listen,
  Upload & Process, and Create & Synchronise a Jam. Staging already has an
  optional hook for this entry point; the current folder is a placeholder.
- [ ] Cover duplicate events, failed decoding, unavailable S3, dependency
  timeouts, worker/service restarts, unauthorized owner actions, and reconnects.
- [ ] Check all service unit suites in CI and retain useful logs on failures.
- [ ] Validate synchronization across physical devices and real Wi-Fi using
  `services/sync/OBSERVABILITY.md`; record audible timing and drift separately
  from server schedules or browser timer measurements.

Acceptance: CI fails on a broken cross-service flow, and the agreed physical
device synchronization target has measured evidence. Health checks alone do
not satisfy this gate.

## 5. Prepare for deployment and update the runbooks

- [ ] Replace development member/participant tokens with the agreed identity
  flow, and verify authorization from the browser through every protected API.
- [ ] Configure production secrets, internal service authentication, HTTPS/WSS,
  service discovery, storage access, database migrations, and rollback steps.
- [ ] Define the supported Jam/Sync replica topology before scaling; account
  for in-memory WebSocket/session ownership and service restarts.
- [ ] Verify logs and metrics expose failed processing, dead-letter queues,
  unhealthy consumers, dependency timeouts, and playback readiness failures.
- [ ] Update `README.md`, `run.md`, and service READMEs to match the actual
  interfaces. Some still describe Catalogue/media integration as fake even
  though Compose uses Catalogue gRPC and Streaming's HTTP metadata adapter.

Acceptance: a staging deployment runs the same scenario tests, has a tested
rollback, and can be operated using accurate runbooks. Production readiness
is a separate gate from the successful local backend checks above.
