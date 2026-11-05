# Remaining integration work

Updated: 5 November 2026. Original baseline branch: `feat/streaming-sync-integration`.

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

- [x] Upload is included in root Compose behind `/api/upload`, validates files,
  stores audio/lyrics in S3, and publishes the agreed `SongUploaded` envelope
  using durable receipts and publisher confirms. The local backend report
  `3f95ad5d66164feeb4353640ac741377` records both generated uploads passing.
- [x] `upload-flow.py` automates submission, publication, Catalogue readiness,
  lyrics/waveform retrieval, measured duration and exact audio downloads.
  `backend-flow.py` reused it for two distinct WAV fixtures; both passed locally.
- [x] Complete live Search verification. Search and its worker are included in
  root Compose and the gateway; `SongReady` indexing, duplicate upserts and
  startup rebuilding are implemented, with unit tests present.
  `ingestion-flow.py` passed locally: both new uploads appeared exactly once
  through case-insensitive title queries, and two repeated `SongReady`
  deliveries were acknowledged without duplicate results or reordering.
- [x] Optional mood metadata is implemented in Upload, the `SongUploaded`
  schema, Catalogue storage/REST contract and Recommendation's Catalogue
  adapter. Upload normalizes labels; weather matching promotes the agreed
  moods while songs without a mood retain general ranking.
- [x] Run `ingestion-flow.py` using `ingestion.compose.yaml` and keep its PASS
  report. Run `227e86d528604ac5abbce85fda7d0ef9` passed all five checks locally
  on 2 November 2026 in 22.07 seconds. Mood propagation and deterministic RAIN
  ranking passed. Invalid lyrics produced the expected
  `PARTIAL`/`LYRICS_NOT_TIMESTAMPED` error; repairing only the fixture's lyrics
  object and replaying its captured event restored the same song to READY
  and Search without changing the successful waveform.
  See `tests/integration/README.md` for commands and retained fixture data.

Acceptance: a user can submit a new song through the public API, discover it
after processing, and retrieve playable audio with its lyrics and waveform.
Failed processing produces a clear status and has a documented retry path.
Item 2 local acceptance passed, recorded in
`tests/integration/ingestion-flow-report.json` with the run ID above. CI is
configured to run the scenario and retain its report; live staging execution
remains pending under the shared staging verification in item 1.

## 3. Connect the frontend and settle playback orchestration

The agreed implementation details and first-release boundaries are in
[FRONTEND_PLAN.md](FRONTEND_PLAN.md), including the browser-owned nine-slot
buffer, laptop/mobile layouts, Nielsen heuristics, and Playwright coverage.
Upload and full Search follow once their backend services are ready.

- [x] Integrate the production frontend and its Compose service behind the
  gateway. Desktop and mobile rendering passed local Playwright checks.
- [x] Connect discovery, upload status, playlists, and playback to gateway APIs.
  A browser upload reached Catalogue `READY`, then opened and played through
  the production UI.
- [x] Connect Jam room membership, queue updates, owner controls, and the Sync
  WebSocket protocol, including clock sampling, buffering, readiness, scheduled
  playback, drift correction, reconnects, and readiness-timeout decisions.
  The production frontend implements the complete Jam/Sync client flow. The
  local browser suite passed independent owner/member membership, shared-queue
  search/add, audio activation, owner start, synchronized `PLAYING` state, and
  responsive Queue/People navigation on 5 November 2026. The backend scenario
  separately verifies identical scheduled starts and reconnect catch-up. Audible
  cross-device timing remains a physical-device evidence gate under item 4.
- [x] Implement browser-owned nine-slot buffering using Streaming's versioned
  manifest and independently decodable chunk endpoints. The browser prioritizes
  current, +1, -1, +2, -2, then outer positions, permits at most two downloads,
  and reduces targets on constrained devices while retaining all nine logical
  positions. The separate `song_request_orchestrator` remains standalone.
- [x] Verify seeking and chunk-boundary playback with real audio formats. The
  Streaming suite generates variable-bitrate MP3 input and verifies three
  independently decodable 44.1 kHz stereo WAV outputs at 441,000, 441,000, and
  220,544 samples. The browser seeks by manifest chunk and intra-chunk offset;
  the proportional legacy byte-slicing endpoint is not used by this flow.

Acceptance: the three documented user journeys work through the production UI,
including actionable errors when a dependency or processing stage fails.

## 4. Turn manual evidence into repeatable scenario tests

- [x] Add a backend scenario test using generated audio/lyrics and unique IDs.
  Assert processing results, playlist order copied into Jam, real audio bytes,
  and identical scheduled starts for two participants. Document fixture cleanup.
- [x] Wire `backend-flow.py` into staging's root `integration` job after
  ingestion checks. Both scenario reports are collected in `after_script`
  and retained with Compose logs/status for one week, including on failures.
  Live staging execution and a successful pipeline link remain pending under
  item 1; configuring the job does not establish that GitLab has run it.
- [ ] Wire the Playwright browser test into staging. `tests/e2e/test_app.py`
  passes locally for Discover & Listen, Upload & Process, a two-browser Jam
  playback flow, and desktop/tablet/mobile layout at 1440px, 768px, and 390px. The
  current `docker:29-cli` integration
  image has no browser runtime, so a pinned Playwright job or image is still
  required before adding `tests/e2e/run.sh`.
- [x] Cover duplicate events, failed decoding, unavailable S3, dependency
  timeouts, worker/service restarts, unauthorized owner actions, and reconnects.
  Duplicate `SongReady` and failed-lyrics recovery already passed under item 2.
  `failure-recovery.py` now provides six sequential fault scenarios, and
  `backend-flow.py --check-reconnect` checks catch-up without restarting the
  owner. All six fault scenarios and reconnect passed locally on 4 November;
  a successful staging run is still required. Commands and retained-data details are in
  `tests/integration/ITEM4_RUNBOOK.md`.
- [ ] Check all service unit suites in CI and retain useful logs on failures.
  The `ci:test-coverage` validation job now audits every deployed application
  image's blocking child test job and retained results. Static configuration
  checks passed for all 11 applications. Every local suite passed in its
  declared CI runtime on 4 November; a successful pipeline link remains pending.
- [ ] Validate synchronization across physical devices and real Wi-Fi using
  `services/sync/OBSERVABILITY.md`; record audible timing and drift separately
  from server schedules or browser timer measurements.
  Blank start/recovery CSV templates and `summarize-sync-measurements.py` are
  provided. At least 20 measured laptop/two-phone runs, delayed-client and
  reconnect evidence, and reviewed external audio recordings remain required.
  No physical measurements have been generated or claimed by these scripts.

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
- [x] Update `README.md`, `run.md`, and service READMEs to match the actual
  interfaces. The root runbook, frontend design documentation, and Catalogue
  notes now describe Catalogue gRPC, Streaming's HTTP metadata adapter, the
  production Jam frontend, and the whole-object playback limitation accurately.

Acceptance: a staging deployment runs the same scenario tests, has a tested
rollback, and can be operated using accurate runbooks. Production readiness
is a separate gate from the successful local backend checks above.
