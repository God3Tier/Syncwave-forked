# SyncWave --- Implementation Plan

## 1. Project Goal

SyncWave is a browser-based social music streaming platform built around
three end-to-end scenarios:

1.  **Discover & Listen**
    -   Search for songs
    -   Receive contextual recommendations
    -   Stream audio using adaptive browser-side buffering
    -   Retrieve synchronized lyrics
    -   Retrieve waveform data for playback visualisation
2.  **Upload & Process**
    -   Upload audio, lyrics, and metadata
    -   Store audio in S3
    -   Publish an upload event through RabbitMQ/AMQP
    -   Process lyrics and waveform data asynchronously and in parallel
    -   Update the catalogue/search state when processing completes
3.  **Create & Synchronize a Jam**
    -   Create or join a Jam from multiple browsers
    -   Maintain a shared queue
    -   Pre-buffer the selected song
    -   Estimate client/server clock offset
    -   Synchronize playback using `PLAY_AT(T)`
    -   Measure playback offset and drift
    -   Resynchronize clients when necessary

The architecture deliberately demonstrates two microservice
communication patterns:

-   **Choreography** for Scenario 2: Upload & Process
-   **Orchestration** for Scenario 3: Jam & Synchronization

------------------------------------------------------------------------

## 2. Team and Service Ownership

The project has six team members and ten primary microservices.

  -----------------------------------------------------------------------
  Person                  Primary Microservices   Main Responsibilities
  ----------------------- ----------------------- -----------------------
  **Azeez**               **Jam Service, Sync     Jam rooms,
                          Service**               participants, shared
                                                  queue, WebSockets, gRPC
                                                  orchestration,
                                                  clock-offset
                                                  estimation,
                                                  `PLAY_AT(T)`, drift
  **Orvin**               **Catalogue Service,    Canonical song
                          Search Service**        metadata, processing
                                                  state, search/indexing

  **Joseph**                **Streaming Service**   S3 audio delivery, HTTP
                                                  Range/chunk delivery,
                                                  playback information,
                                                  circular-buffer support

  **Yonghuey**            **Upload Service**      Upload API, metadata
                                                  validation, S3
                                                  ingestion, initial
                                                  processing state, AMQP
                                                  event publishing

  **Jiawen**              **Lyrics Service,       Lyrics
                          Waveform Service**      processing/retrieval,
                                                  waveform
                                                  generation/retrieval,
                                                  AMQP consumers

  **Hayyun**              **Playlist Service,     Playlist
                          Recommendation          CRUD/order/shuffle,
                          Service**               recommendations,
                                                  Weather API
  -----------------------------------------------------------------------

Ownership indicates **primary responsibility**, not exclusive knowledge.
Every member should understand the three scenarios, the high-level
architecture, and the contracts their services depend on.

------------------------------------------------------------------------

## 3. Microservice List

### 1. Catalogue Service --- Orvin

Canonical source for song metadata and processing state.

Responsibilities: - Store/retrieve song metadata - Store S3/audio
reference - Store duration - Track lyrics processing status - Track
waveform processing status - Track overall song readiness - Expose song
information to Search, Streaming, Jam/Sync, Playlist and frontend flows

Initial song model:

``` text
song_id
title
artist
duration
audio_reference
lyrics_status
waveform_status
processing_status
created_at
updated_at
```

------------------------------------------------------------------------

### 2. Search Service --- Orvin

Responsibilities: - Search by song title - Search by artist - Search
relevant metadata - Make newly processed songs discoverable - Maintain
or query the searchable representation of catalogue data

Start with the simplest suitable implementation.
OpenSearch/Elasticsearch should only be added if its additional
operational complexity is justified.

------------------------------------------------------------------------

### 3. Streaming Service --- Joseph

Responsibilities: - Resolve playable audio - Interface with S3 - Support
HTTP Range requests or bounded chunk delivery - Provide playback
information required by browsers - Support browser prefetching - Provide
stream information required by the Sync Service

The Streaming Service should not maintain several minutes of audio in
server memory for every user. The browser owns the logical playback
buffer.

------------------------------------------------------------------------

### 4. Upload Service --- Yonghuey

Responsibilities: - Accept upload request - Validate song metadata -
Store/upload audio in S3 - Register initial song/processing state -
Publish `SongUploaded` - Return upload status

Long-running lyrics/waveform processing must not occur inside the upload
HTTP request.

------------------------------------------------------------------------

### 5. Lyrics Service --- Jiawen

The Lyrics Service owns the **complete lyrics capability**, including
processing and retrieval.

Responsibilities: - Consume relevant AMQP upload events -
Validate/process timestamped lyrics - Store processed lyrics - Publish
success/failure events - Expose an HTTP API for lyric retrieval

Conceptual structure:

``` text
lyrics-service/
├── api/
│   └── GET /songs/{songId}/lyrics
├── worker/
│   └── RabbitMQ consumer
└── shared/
    └── processing/storage logic
```

The API process and consumer process may run separately while remaining
part of the same logical service capability.

------------------------------------------------------------------------

### 6. Waveform Service --- Jiawen

The Waveform Service owns the **complete waveform capability**,
including generation and retrieval.

Responsibilities: - Consume relevant AMQP upload events - Read uploaded
audio - Calculate/downsample waveform amplitude data - Store processed
waveform data - Publish success/failure events - Expose an HTTP API for
waveform retrieval

Conceptual structure:

``` text
waveform-service/
├── api/
│   └── GET /songs/{songId}/waveform
├── worker/
│   └── RabbitMQ consumer
└── shared/
    └── waveform generation/storage logic
```

Lyrics and waveform processing should execute independently and in
parallel.

------------------------------------------------------------------------

### 7. Playlist Service --- Hayyun

Responsibilities: - Create playlist - Delete playlist - Retrieve
playlist - Add/remove songs - Reorder songs - Shuffle playlist - Return
queue/order information to Jam/Sync where required

Example API:

``` text
POST   /playlists
GET    /playlists/{id}
POST   /playlists/{id}/songs
DELETE /playlists/{id}/songs/{songId}
POST   /playlists/{id}/shuffle
```

------------------------------------------------------------------------

### 8. Recommendation Service --- Hayyun

Responsibilities: - Generate song/playlist recommendations - Consume
catalogue information - Use Weather API as one contextual recommendation
signal - Fall back gracefully when Weather API is unavailable

Weather is a supporting signal, not the entire recommendation system.

------------------------------------------------------------------------

### 9. Jam Service --- Azeez

Responsibilities: - Create Jam - Join Jam - Leave Jam - Track Jam
owner - Track connected participants - Maintain shared queue/session
state - Add/remove/reorder queued songs - Broadcast Jam/queue state
changes - Trigger synchronization through the Sync Service

Example Jam state:

``` text
jam_id
owner_id
participants[]
queue[]
current_song
state
created_at
```

------------------------------------------------------------------------

### 10. Sync Service --- Azeez

The Sync Service is the orchestrator for synchronized playback.

Responsibilities: - Maintain synchronization-related WebSocket
communication - Estimate browser/server clock offset - Coordinate
`PREPARE` - Track participant `READY` state - Resolve required
playlist/song/stream information - Select future playback timestamp -
Broadcast `PLAY_AT(T)` - Track expected playback position - Measure
playback drift - Issue synchronization corrections when required

The detailed implementation backlog, protocol decisions, test strategy,
and completion criteria for this service are in
[Section 24](#24-azeez--sync-service-detailed-implementation-plan).

------------------------------------------------------------------------

## 4. High-Level Architecture

``` text
                                  Frontend
                                     |
        +----------------------------+-----------------------------+
        |                 |                 |                      |
        v                 v                 v                      v
      Search           Playlist            Jam                  Upload
        |                 |                 |                      |
        v                 v                 v                      v
    Catalogue       Recommendation         Sync                   S3
        |                 |             /    |    \                 |
        |            Weather API      gRPC  gRPC  gRPC             |
        |                              /      |      \              |
        +--------------------------> Playlist Catalogue Streaming   |
                                                               RabbitMQ
                                                               /       \
                                                              v         v
                                                           Lyrics   Waveform
```

------------------------------------------------------------------------

## 5. Scenario 1 --- Discover & Listen

### Flow

``` text
Browser
   |
   +----> Recommendation Service ----> Weather API
   |
   +----> Search Service
                |
                v
          Catalogue Service
                |
                +----> Streaming Service ----> S3 ----> Browser audio
                |
                +----> Lyrics Service -------> Browser lyrics
                |
                +----> Waveform Service -----> Browser waveform
```

### Adaptive Circular Buffer

``` text
Position:  -4   -3   -2   -1   CURRENT   +1   +2   +3   +4
Buffer:    30s  30s  2m   2m     3m      2m   2m   30s  30s
```

Songs outside the ±4-song window initially have **0 seconds buffered**.

The browser owns the logical buffer state.

When the current song advances: 1. Rotate the logical window. 2. Evict
chunks that are no longer useful. 3. Preserve relevant nearby chunks. 4.
Request new ranges for newly relevant songs.

The server provides bounded ranges/chunks rather than maintaining a
large per-user audio buffer.

------------------------------------------------------------------------

## 6. Scenario 2 --- Upload & Process

Scenario 2 demonstrates **event-driven choreography**.

### Flow

``` text
Uploader
   |
   v
Upload Service
   |
   +--------------------> S3
   |
   v
SongUploaded
   |
   v
RabbitMQ / AMQP
   |
   +-----------------------------+
   |                             |
   v                             v
Lyrics Service              Waveform Service
Consumer                    Consumer
   |                             |
   v                             v
Process lyrics              Generate waveform
   |                             |
   v                             v
Store result                Store result
   |                             |
   v                             v
LyricsProcessed             WaveformProcessed
   |                             |
   +--------------+--------------+
                  |
                  v
          Catalogue / Search
```

### Why Choreography

There is no single service synchronously commanding every processing
step.

After `SongUploaded`: - Lyrics Service reacts independently. - Waveform
Service reacts independently. - Both can execute in parallel. - Each can
succeed, fail, and retry independently.

One slow processor should not unnecessarily block the other.

### Initial Events

``` text
SongUploaded
LyricsProcessed
LyricsProcessingFailed
WaveformProcessed
WaveformProcessingFailed
SongReady
```

Minimum event envelope:

``` text
event_id
event_type
song_id
timestamp
payload
```

Consumers must be designed to be **idempotent**.

------------------------------------------------------------------------

## 7. Scenario 3 --- Create & Synchronize a Jam

Scenario 3 demonstrates **orchestration**.

### Jam Setup

``` text
Browser A ─┐
Browser B ─┼──── WebSocket ────> Jam / Sync
Browser C ─┘
```

Users can use multiple phones/laptops in the same physical space as
separate synchronized playback devices.

### Internal Orchestration

``` text
Owner
  |
  v
Jam Service
  |
  v
Sync Service
  |
  +------ gRPC ------> Playlist Service
  |
  +------ gRPC ------> Catalogue Service
  |
  +------ gRPC ------> Streaming Service
```

### Synchronization Protocol

1.  User joins the Jam.
2.  Browser establishes WebSocket connection.
3.  Browser and Sync Service exchange timing information.
4.  Browser estimates its clock offset relative to the Sync Service.
5.  Owner requests synchronized playback.
6.  Sync Service resolves the selected track.
7.  Sync Service sends `PREPARE(song)`.
8.  Each browser pre-buffers the required beginning of the song.
9.  Browsers send `READY`.
10. Sync Service chooses a future server timestamp.
11. Sync Service broadcasts `PLAY_AT(T)`.
12. Each browser converts `T` to its local timing reference.
13. Each browser schedules playback locally.
14. Browsers report timing/playback position.
15. Sync Service measures drift and corrects significant differences.

Example:

``` text
Current server time: 12:00:00.000
Target start:        12:00:02.000

PLAY_AT(12:00:02.000)
```

Do not rely on:

``` text
PLAY_NOW
```

because network delivery latency would directly affect start time.

### Demo Measurement

``` text
Target:    14:32:10.000

Device A:  +38 ms
Device B:  -21 ms
Device C:  +54 ms

Maximum observed offset: 75 ms
```

The acceptable synchronization tolerance should be determined
experimentally.

------------------------------------------------------------------------

## 8. Communication Patterns

### HTTP/JSON

Use primarily for: - Browser-facing APIs - Search - Catalogue
operations - Playlist operations - Upload initiation - Lyrics
retrieval - Waveform retrieval

### AMQP / RabbitMQ

Use for: - Upload processing - `SongUploaded` - Lyrics processing
events - Waveform processing events - Processing success/failure

### gRPC

Primary self-directed research item.

Use for selected internal synchronous calls around the Jam workflow:

``` text
Sync -> Playlist
Sync -> Catalogue
Sync -> Streaming
```

### WebSocket

Use between browsers and Jam/Sync for real-time Jam communication:

``` text
JOIN
LEAVE
QUEUE_UPDATED
PREPARE
READY
PLAY_AT
PLAYBACK_STATUS
SYNC_CORRECTION
ERROR
```

### HTTP Range / Bounded Chunks

Use between browser and Streaming/S3 for audio prefetching and playback.

------------------------------------------------------------------------

## 9. Data Path vs Control Path

Do not route raw audio through unnecessary service chains.

### Control Path

``` text
Sync
 |
 +--> Playlist
 +--> Catalogue
 +--> Streaming metadata
```

### Audio Path

``` text
S3 / Streaming
      |
      v
   Browser
```

The control plane coordinates playback. The audio data path remains
short.

------------------------------------------------------------------------

## 10. Shared Contracts --- Must Be Agreed Before Building

Before everyone develops independently, agree on the shared interfaces.

### Common IDs

``` text
user_id
song_id
playlist_id
jam_id
event_id
```

### Song Contract

``` text
song_id
title
artist
duration
audio_reference
lyrics_status
waveform_status
processing_status
```

### AMQP Contract

Agree on: - Exchange names - Queue names - Routing keys - Event
envelope - Retry behaviour - Dead-letter queue behaviour

### gRPC Contract

Create `.proto` files before Jam integration.

Initial operations may include:

``` text
GetPlaylist(...)
GetSong(...)
GetStreamInfo(...)
```

### WebSocket Contract

Define message names and payloads before Jam/frontend implementation:

``` text
JOIN
LEAVE
QUEUE_UPDATED
PREPARE
READY
PLAY_AT
PLAYBACK_STATUS
SYNC_CORRECTION
ERROR
```

### Contract Rule

A breaking shared-contract change must be communicated to every affected
service owner.

------------------------------------------------------------------------

## 11. Data Ownership

Avoid multiple services directly modifying the same data without a clear
owner.

Suggested ownership:

  Data                          Owner
  ----------------------------- -----------------------------
  Song metadata/status          Catalogue Service
  Search/index representation   Search Service
  Audio objects                 Streaming/Upload through S3
  Lyrics                        Lyrics Service
  Waveform data                 Waveform Service
  Playlists                     Playlist Service
  Jam/session state             Jam Service
  Sync timing/readiness state   Sync Service

Other services should interact through APIs/events rather than directly
modifying another service's owned data.

------------------------------------------------------------------------

## 12. Repository Structure

``` text
syncwave/
|
+-- frontend/
|
+-- services/
|   +-- catalogue/
|   +-- search/
|   +-- streaming/
|   +-- upload/
|   +-- lyrics/
|   |   +-- api/
|   |   +-- worker/
|   |   +-- shared/
|   +-- waveform/
|   |   +-- api/
|   |   +-- worker/
|   |   +-- shared/
|   +-- playlist/
|   +-- recommendation/
|   +-- jam/
|   +-- sync/
|
+-- contracts/
|   +-- api/
|   +-- events/
|   +-- grpc/
|   +-- websocket/
|
+-- infrastructure/
|   +-- docker/
|   +-- aws/
|
+-- tests/
|   +-- integration/
|   +-- e2e/
|
+-- docker-compose.yml
+-- plan.md
+-- agents.md
+-- README.md
```

Each deployable service should contain: - `Dockerfile` - README -
tests - configuration/example environment file - CI/CD coverage

------------------------------------------------------------------------

## 13. Git Workflow

Main flow:

``` text
feature/* -> dev -> staging -> main
```

`main` is production: merges to it deploy to ECS. `staging` is an
ephemeral environment inside CI: merges to it start the full Docker
Compose stack in the pipeline and run the integration/e2e tests, at no
extra cloud cost.

Example feature branches:

``` text
feature/catalogue-api
feature/search
feature/streaming-range
feature/upload-amqp
feature/lyrics-worker
feature/waveform-generation
feature/playlist-crud
feature/weather-recommendation
feature/jam-websocket
feature/jam-clock-sync
```

Do not perform major development directly on `dev`, `staging`, or
`main`.

------------------------------------------------------------------------

## 14. Development Phases

### Phase 0 --- Contracts and Architecture

**Whole team**

Before substantial feature development:

1.  Confirm service ownership.
2.  Confirm service boundaries.
3.  Agree common IDs.
4.  Agree the Song contract.
5.  Define initial REST contracts.
6.  Define `SongUploaded`.
7.  Define AMQP event envelope.
8.  Define WebSocket Jam messages.
9.  Define initial gRPC `.proto`.
10. Agree data ownership.
11. Agree environment/secrets approach.

**Milestone:** every member knows what their service receives and sends.

------------------------------------------------------------------------

### Phase 1 --- Skeleton and Infrastructure

Goal:

> **All services exist and can run together before the team builds
> deeply in isolation.**

Tasks: - Repository structure - Frontend skeleton - Service skeletons -
Dockerfiles - Docker Compose - RabbitMQ - Development database(s) - S3
connectivity - Health endpoints - Basic CI pipelines - Basic
inter-service communication

**Milestone:** all services run locally and at least one test
request/event can cross service boundaries.

------------------------------------------------------------------------

### Phase 2 --- Individual Happy Paths

#### Azeez --- Jam / Sync

``` text
Create Jam
 -> second browser joins
 -> WebSocket communication
 -> shared room state
```

Then:

``` text
clock-offset exchange
 -> PREPARE
 -> READY
 -> PLAY_AT(T)
```

#### Orvin --- Catalogue / Search

``` text
Create/retrieve song metadata
 -> index/search
 -> retrieve song
```

#### Joseph --- Streaming

``` text
Song reference
 -> S3
 -> HTTP Range/chunk
 -> browser playback
```

#### Yonghuey --- Upload

``` text
Upload request
 -> S3
 -> create processing state
 -> publish SongUploaded
```

#### Jiawen --- Lyrics / Waveform

``` text
SongUploaded
 -> Lyrics consumer
 -> store lyrics
 -> retrieve lyrics
```

and:

``` text
SongUploaded
 -> Waveform consumer
 -> generate waveform
 -> retrieve waveform
```

#### Hayyun --- Playlist / Recommendation

``` text
Create playlist
 -> add songs
 -> retrieve
 -> shuffle
```

and:

``` text
Catalogue data
 -> recommendation
 -> optional Weather API context
```

------------------------------------------------------------------------

## 15. Phase 3 --- Scenario Integration

### Scenario 1

``` text
Recommendation
 -> Search
 -> Catalogue
 -> Streaming
 -> Browser buffer
 -> Lyrics
 -> Waveform
```

### Scenario 2

``` text
Upload
 -> S3
 -> AMQP
 -> Lyrics + Waveform in parallel
 -> Catalogue
 -> Search
```

### Scenario 3

``` text
Jam
 -> Sync
 -> Playlist / Catalogue / Streaming
 -> PREPARE
 -> READY
 -> PLAY_AT(T)
```

**Milestone:** all three scenarios work end-to-end.

------------------------------------------------------------------------

## 16. Failure Handling

### Upload succeeds but processing fails

Keep the uploaded media and expose processing state.

``` text
PROCESSING
PARTIAL
READY
FAILED
```

Retry only the failed stage where possible.

### Lyrics succeeds, waveform fails

``` text
lyrics_status   = READY
waveform_status = FAILED
```

Do not redo successful lyrics processing.

### Duplicate AMQP Delivery

Consumers must be idempotent.

Use `event_id`, `song_id`, and processing state to detect duplicate
work.

### Consumer Failure

``` text
Failure
 -> retry
 -> retry limit
 -> dead-letter queue
```

### Search Indexing Failure

Catalogue remains the canonical source. Retry/rebuild search state.

### Weather API Failure

Fall back to recommendations without weather context.

### Jam Participant Disconnect

On reconnect: 1. Rejoin Jam. 2. Retrieve current song. 3. Retrieve
expected playback position. 4. Re-estimate clock offset. 5. Resume at
the expected position.

### Participant Not Ready

Wait for all connected participants until the preparation timeout. If one
or more participants are still not ready, prompt the Jam owner to continue
without them, keep waiting, or cancel. Do not automatically exclude a
participant or allow a non-owner to make this decision.

Late participants can join at the expected playback offset.

### Clock Drift

Small drift may be ignored.

Larger drift can trigger synchronization correction or seeking.

Exact thresholds should be determined experimentally.

### Streaming Failure

Do not issue `PLAY_AT(T)` if the required audio cannot be obtained.

------------------------------------------------------------------------

## 17. CI/CD

Every deployable service/UI must have CI/CD coverage.

Suggested pipeline:

``` text
Lint / Static Analysis
        |
        v
Unit Tests
        |
        v
Build
        |
        v
Docker Build
        |
        v
Integration Tests
        |
        v
Push Image
        |
        v
Deploy
```

### Local

Use Docker Compose for: - services - frontend - RabbitMQ - development
databases - supporting infrastructure

### Production Direction

Use: - AWS - ECR - ECS - S3 - managed database only where justified

Keep cloud cost visible and remove unnecessary resources when not in
use.

------------------------------------------------------------------------

## 18. Testing

### Unit Tests

Each owner tests their service's internal logic.

### Contract / Integration Tests

Test: - REST interfaces - AMQP event payloads - gRPC interfaces -
WebSocket message handling

### End-to-End Tests

Test the three main scenarios.

### Jam Physical Device Test

Minimum:

``` text
Laptop
Phone A
Phone B
```

Measure: - clock offset - start-time difference - playback drift -
disconnect/reconnect - late join

Record real measurements rather than claiming perfect synchronization.

------------------------------------------------------------------------

## 19. Definition of Done

A service/feature is not complete merely because it works on one
developer's machine.

It is complete when:

-   Core implementation works
-   Unit tests pass
-   Shared contracts are documented
-   Docker build works
-   Runs in Docker Compose
-   CI pipeline passes
-   Expected failure cases are handled
-   Logs are useful
-   Dependent services can integrate with it
-   Owner can explain its architecture and trade-offs

------------------------------------------------------------------------

## 20. Integration Rule

Do not wait until everyone has "finished their service" before
integrating.

Use:

``` text
Define contract
      |
      v
Build small capability
      |
      v
Integrate
      |
      v
Build next capability
      |
      v
Integrate again
```

A feature that only works inside one person's isolated service is not
considered complete.

------------------------------------------------------------------------

## 21. Workload Balance

The service count is not intended to represent equal difficulty.

### Azeez

**Jam + Sync**

High technical complexity: - WebSockets - distributed timing - gRPC
orchestration - clock-offset estimation - readiness - `PLAY_AT(T)` -
drift

### Orvin

**Catalogue + Search**

Moderate complexity: - central song model - search/indexing - catalogue
state - integration with multiple services

### Joseph

**Streaming**

Moderate/high technical complexity despite one primary service: - S3 -
range requests - audio playback - browser prefetch interaction - Jam
playback integration

joseph can additionally assist with cross-service integration once the
core Streaming path is stable.

### Yonghuey

**Upload**

Moderate complexity: - HTTP upload workflow - S3 - metadata validation -
processing state - RabbitMQ producer - integration with Catalogue and
processing consumers

### Jiawen

**Lyrics + Waveform**

Moderate/high complexity: - two independent consumers - processing
logic - storage - retrieval APIs - retry/idempotency behaviour

### Hayyun

**Playlist + Recommendation**

Moderate complexity: - playlist state/ordering - recommendation logic -
catalogue integration - Weather API - Jam queue integration

Work should be rebalanced during implementation if one workstream
becomes significantly heavier than expected.

------------------------------------------------------------------------

## 22. Immediate Next Steps

Before substantial implementation:

1.  Confirm this service ownership.
2.  Create repository folders.
3.  Agree `song_id`, `user_id`, `playlist_id`, `jam_id`, and `event_id`.
4.  Finalise the Song schema.
5.  Define initial REST endpoints.
6.  Define the `SongUploaded` event.
7.  Define the AMQP event envelope.
8.  Define Lyrics/Waveform success/failure events.
9.  Define Jam WebSocket messages.
10. Define the first gRPC `.proto`.
11. Decide data/table ownership.
12. Create Docker Compose.
13. Start RabbitMQ.
14. Configure development S3 access.
15. Create minimal skeletons for all ten services.
16. Make one HTTP request work across services.
17. Make one AMQP event reach a consumer.
18. Make one WebSocket message work between two browsers.
19. Make one gRPC call work between two services.

------------------------------------------------------------------------

## 23. First Team Milestone

The first milestone should **not** be:

> Each person has finished their assigned service.

The first milestone should be:

> **All ten service skeletons exist, the system runs together locally,
> and HTTP, AMQP, WebSocket, and gRPC communication have each been
> proven with a minimal working path.**

After this milestone, each member can build deeper functionality with
much lower integration risk.

------------------------------------------------------------------------

## 24. Azeez --- Sync Service Detailed Implementation Plan

This section is Azeez's working plan for the Sync Service. It turns the
high-level Scenario 3 design into small deliverables that can be built,
tested, demonstrated, and integrated one at a time.

### 24.1 Scope and Service Boundary

The Sync Service owns **playback coordination**, not Jam membership or
audio delivery.

It owns:

- WebSocket connections used by the synchronization protocol
- Per-connection timing samples and estimated clock offset
- The playback session lifecycle (`IDLE`, `PREPARING`, `SCHEDULED`,
  `PLAYING`, `PAUSED`, `ENDED`)
- Readiness for the current playback generation
- Selection of a future server start time
- The authoritative playback timeline for a Jam
- Drift calculation and correction decisions
- Re-synchronization after reconnect or late join
- Calls to Playlist, Catalogue, and Streaming through defined contracts

It does not own:

- Jam creation, ownership, membership, or queue editing; Jam Service owns
  these
- Playlist contents; Playlist Service owns these
- Song metadata/readiness; Catalogue Service owns these
- Audio bytes or signed stream URLs; Streaming Service owns these
- The browser's audio buffer or media player

The Jam Service is the user-facing controller. Members add and arrange
songs through Jam, and the owner presses play, pause, resume, seek, or skip
through Jam. After validating the action, Jam tells Sync which Jam, song,
and queue item to coordinate. Sync performs the timing work and returns
playback state to Jam without editing the queue or writing directly to
another service's database.

### 24.2 Decisions to Confirm Before Coding

The following initial decisions were agreed for the project. Record them
in `contracts/websocket/README.md` or the relevant contract file before
implementation:

1. Implement Jam and Sync as separate Python 3.12 services using FastAPI.
   Use Pydantic v2 for message/configuration validation, SQLAlchemy 2 with
   `asyncpg` for Sync's PostgreSQL state, and `grpcio` for internal service
   calls. FastAPI provides HTTP APIs, WebSocket support, and a
   straightforward asynchronous programming model.
2. Jam remains the main user-facing room capability. It owns membership,
   owner role, shared queue, and permission to add songs. Sync is activated
   only when the owner starts synchronized playback; Jam then hands the
   playback request and Jam snapshot to Sync through an internal API.
3. Sync hosts the playback WebSocket endpoint:
   `GET /api/sync/ws?jam_id={jamId}`. Clients only need this connection
   while synchronized playback is active. Jam should send clients the Sync
   session information when the hand-off occurs.
4. The first version uses mock users and a short-lived mock Jam/Sync token.
   Jam validates membership and owner permissions before starting Sync;
   Sync validates the handed-off session/token rather than trusting a role
   supplied directly by the browser.
5. All protocol timestamps use integer Unix epoch milliseconds.
   Durations and playback positions use integer milliseconds.
6. Every message contains `type`, `jam_id`, `seq`, `sent_at_ms`, and
   `payload`.
7. Every playback attempt has a monotonically increasing `generation`.
   Messages from an older generation must be ignored.
8. Jam is the only service that accepts queue changes and owner playback
   actions from users. Members can add songs through Jam. Only the Jam owner
   can start, pause, resume, seek, skip, or decide to continue without an
   unready participant. After authorization, Jam sends an authenticated
   internal command to Sync; Sync does not expose these controls directly
   to browsers.
9. Initial readiness policy: wait for all connected participants. If the
   prepare timeout expires, Sync notifies Jam. Jam prompts the owner with
   the unready participants and sends the owner's `CONTINUE`, `WAIT`, or
   `CANCEL` decision back to Sync. Sync must not silently choose on the
   owner's behalf.
10. Initial correction policy: ignore small drift, temporarily adjust
    playback rate for medium drift, and use a scheduled seek for large
    drift or when rate correction is unsupported.
11. The measured synchronization target is an absolute client-to-client
    difference of 100 ms or less under the documented demo conditions.
    Report actual results and do not claim the target was met unless the
    physical-device tests demonstrate it.
12. Persist the authoritative playback timeline so Sync can recover after
    a container restart. Clients must reconnect and rejoin because live
    WebSocket objects cannot be persisted.
13. The project version runs one Sync instance. Multi-instance routing and
    shared pub/sub are documented future work, not part of the MVP.

Do not hide undecided behaviour in code defaults. Put it in configuration
and document the selected value.

### 24.3 Playback Session State Machine

Use an explicit state machine so repeated or out-of-order commands cannot
produce impossible states.

``` text
IDLE
  |
  | Jam sends authorized start command
  v
PREPARING ---- prepare timeout/no ready clients ----> IDLE or ERROR
  |
  | readiness policy satisfied
  v
SCHEDULED ---- Jam cancels/changes generation -----> PREPARING or IDLE
  |
  | target server time reached
  v
PLAYING <---- resume ---- PAUSED
  |  \                    /
  |   \---- pause -------/
  |
  +---- song finishes -----------------------------> ENDED
  +---- Jam sends authorized skip ----------------> PREPARING
```

For every transition, define:

- The command/event that caused it
- Who is authorized to cause it
- The state that must already exist
- The state changes written atomically
- The WebSocket message broadcast to clients
- What happens if the command is duplicated

Reject invalid transitions with a stable error code. A duplicated command
with the same request ID should return the original result rather than
starting a second generation.

### 24.4 WebSocket Protocol to Define

Create JSON Schemas in `contracts/websocket/` and valid examples in
`contracts/websocket/examples/`. At minimum define:

| Message | Direction | Required payload |
|---|---|---|
| `JOIN` | client -> Sync | `participant_id`, authentication/join token, client capabilities |
| `JOINED` | Sync -> client | current generation, state, song, authoritative timeline |
| `TIME_PING` | client -> Sync | `sample_id`, `client_sent_ms` |
| `TIME_PONG` | Sync -> client | echoed client time, `server_received_ms`, `server_sent_ms` |
| `PREPARE` | Sync -> client | generation, song ID, stream information, start offset |
| `READY` | client -> Sync | generation, buffered duration, media duration |
| `PLAY_AT` | Sync -> client | generation, `target_server_time_ms`, start position |
| `PLAYBACK_STATUS` | client -> Sync | generation, measured server time, position, paused/buffering state |
| `SYNC_CORRECTION` | Sync -> client | generation, method, target position or rate, reason |
| `PAUSE_AT` | Sync -> client | generation, target server time |
| `RESUME_AT` | Sync -> client | generation, target server time and position |
| `SEEK_TO` | Sync -> client | generation, target server time and position |
| `PARTICIPANT_STATE` | Sync -> clients | participant connected/ready/buffering status |
| `ERROR` | Sync -> client | stable code, readable message, related request ID |

`START_REQUEST`, pause, resume, seek, skip, and readiness decisions are not
browser-to-Sync WebSocket messages. They are authenticated internal
Jam-to-Sync operations. Likewise, Sync reports a readiness timeout to Jam,
and Jam owns the prompt shown to the owner.

Protocol rules:

- Validate every incoming message before changing state.
- Enforce maximum message size and a per-connection message rate.
- Drop stale sequence numbers and stale generations.
- Use a request ID for internal Jam commands and a sample ID for timing
  messages.
- Send heartbeat ping/pong frames and close dead connections.
- Never trust a client-provided Jam role without server-side validation.
- Keep errors machine-readable; do not require the frontend to parse text.

Initial error codes should include `INVALID_MESSAGE`, `UNAUTHORIZED`,
`NOT_JAM_OWNER`, `UNKNOWN_JAM`, `INVALID_STATE`, `STALE_GENERATION`,
`SONG_NOT_READY`, `STREAM_UNAVAILABLE`, `PREPARE_TIMEOUT`, and
`DEPENDENCY_UNAVAILABLE`.

### 24.5 Clock-Offset Estimation

The browser and Sync Service should exchange several timing samples before
scheduled playback. For one sample:

``` text
t0 = client send time
t1 = server receive time
t2 = server send time
t3 = client receive time

round_trip_delay = (t3 - t0) - (t2 - t1)
clock_offset     = ((t1 - t0) + (t2 - t3)) / 2
```

Implementation rules:

1. Collect at least 5 samples on join and refresh samples periodically.
2. Reject impossible or negative values caused by malformed messages.
3. Prefer the offset from the lowest-delay samples; for example, take the
   median offset of the best 3 samples.
4. Store offset, round-trip delay, sample count, and last-sampled time per
   connection.
5. Mark the estimate stale after a configurable interval.
6. Require a fresh estimate before `PLAY_AT` where possible.
7. Use a monotonic clock for durations inside a process. Use wall-clock
   epoch time only for timestamps exchanged between machines.

The client converts a server target time to its local clock using the
estimated offset, then schedules playback locally. Network arrival time of
`PLAY_AT` must not itself determine when playback starts.

### 24.6 Prepare, Ready, and Scheduled Start

The happy path is:

1. Receive an authenticated, authorized `StartPlayback` command from Jam.
2. Increment the Jam playback `generation`.
3. Accept the selected `queue_item_id` and `song_id` snapshot from Jam.
4. Call Catalogue to confirm the song exists and is ready.
5. Call Streaming for playable stream metadata or a short-lived URL.
6. Create a `PREPARING` session and snapshot the connected participants.
7. Broadcast `PREPARE` with the new generation.
8. Track `READY` only when its Jam, participant, and generation match.
9. When all participants are ready, select
   `target_server_time_ms = now + start_lead_time_ms`.
10. If the prepare timeout expires, report `ReadinessDecisionRequired` to
    Jam. Jam prompts the owner and returns the decision. Continue only after
    an explicit `CONTINUE`, remain in `PREPARING` after `WAIT`, or return to
    `IDLE` after `CANCEL`.
11. Persist the authoritative timeline before broadcasting `PLAY_AT`.
12. Broadcast `PLAY_AT` and move to `SCHEDULED`.
13. At the target time, move to `PLAYING`.

Suggested starting configuration for local testing, not final claims:

``` text
START_LEAD_TIME_MS=2000
PREPARE_TIMEOUT_MS=10000
STATUS_INTERVAL_MS=2000
CLOCK_SAMPLE_MAX_AGE_MS=30000
TARGET_SYNC_TOLERANCE_MS=100
```

If the selected song changes while clients prepare, increment the
generation and send a new `PREPARE`. Late `READY` messages for the previous
generation must have no effect.

### 24.7 Authoritative Timeline and Drift

For a playing session, store an anchor rather than updating the expected
position continuously:

``` text
anchor_server_time_ms
anchor_position_ms
playback_rate
paused
```

When playing:

``` text
expected_position_ms = anchor_position_ms
                     + (server_now_ms - anchor_server_time_ms)
                       * playback_rate

drift_ms = client_reported_position_ms - expected_position_ms
```

When paused, expected position remains at `anchor_position_ms`. Seeking,
pausing, resuming, or changing rate creates a new anchor.

Start with configurable correction bands and tune them with measurements:

``` text
abs(drift) <= 80 ms       -> observe only
80 ms < abs(drift) <= 250 -> gentle temporary rate correction if supported
abs(drift) > 250 ms       -> scheduled seek to authoritative position
```

Add hysteresis and a cooldown so a client does not oscillate between
corrections. Do not correct a client while it reports `buffering`; first
restore its buffer, then schedule a seek to the current expected position.

### 24.8 Late Join and Reconnect

On join or reconnect:

1. Validate Jam membership again.
2. Replace the participant's previous dead connection, if present.
3. Return the current generation and session state in `JOINED`.
4. Run a fresh clock sample exchange.
5. If the Jam is preparing, send the current `PREPARE` and accept `READY`.
6. If it is scheduled, send the same target only if enough lead time
   remains; otherwise treat the client as a late joiner.
7. If it is playing, calculate the current expected position, ask the
   client to buffer, and issue a future scheduled seek/start.
8. Never restart or pause all existing participants merely because one
   participant reconnects.

### 24.9 Data Model

Keep durable session/timeline state in Sync's own Postgres database. Keep
live WebSocket objects and short-lived timing samples in process memory.

Suggested tables:

``` text
sync_sessions
  jam_id                  primary key
  generation              bigint
  state                   text
  song_id                 uuid/null
  queue_item_id           uuid/null
  anchor_server_time_ms   bigint/null
  anchor_position_ms      bigint
  playback_rate           numeric
  prepare_deadline_ms     bigint/null
  created_at
  updated_at

sync_commands
  request_id              primary key
  jam_id
  command_type
  generation
  result                   jsonb
  created_at
```

Live per-connection state:

``` text
connection_id
jam_id
participant_id
role
last_seq
generation
ready
clock_offset_ms
round_trip_delay_ms
last_clock_sample_at
last_status_at
last_reported_position_ms
buffering
```

Do not store raw WebSocket connections in Postgres. If multi-instance Sync
is added later, introduce a shared presence/pub-sub design explicitly
rather than pretending database rows can route socket messages.

### 24.10 Internal Dependency Contracts

Define `.proto` contracts before writing clients. Sync initially needs:

``` text
Jam -> Sync:   start, pause, resume, seek, skip, and readiness decision
Sync -> Jam:   playback state and readiness-decision-required notification
Catalogue:    get song metadata and verify processing_status == READY
Streaming:    get stream URL/range metadata and verify availability
```

Jam passes an immutable snapshot containing `jam_id`, `queue_item_id`,
`song_id`, participant IDs, the authorized owner ID, and `request_id`.
Sync does not query or mutate the Jam queue and does not reimplement Jam's
user permissions. It authenticates that the internal request came from Jam
and makes repeated request IDs idempotent.

Every call needs a deadline. Distinguish `not found`, `not ready`,
`permission denied`, and `temporarily unavailable`. Do not wait forever or
issue `PLAY_AT` with incomplete stream information.

Where another service is not implemented yet, use a small fake gRPC server
in Sync's tests. Do not reach into another service's database as a shortcut.

### 24.11 Browser Test Client

Build a minimal browser page early, even before the full frontend exists.
It should show:

- Connection and participant ID
- Current Jam, generation, and state
- Latest offset and round-trip delay
- `PREPARE` and readiness status
- Target start time and actual start difference
- Expected position, actual position, and drift
- Last correction received
- Buttons for connect, prepare/ready, start, pause, resume, seek, and
  disconnect/reconnect

This page is a development instrument, not throwaway decoration. It makes
the timing protocol observable and allows two browsers or devices to prove
the vertical slice before the production UI is ready.

### 24.12 Implementation Slices

Each slice should end with working tests and an integration checkpoint.

Current implementation status (13 October 2026):

- Python/FastAPI Sync service skeleton created and included in Docker Compose
- Health/readiness endpoints and service-specific CI pipeline added
- Initial Jam-to-Sync gRPC control contract defined
- Temporary authenticated internal HTTP activation endpoint added so Sync
  can be tested before the Jam gRPC client exists
- Authenticated participant WebSocket handshake, `JOINED`, `TIME_PING`,
  `TIME_PONG`, `PREPARE`, `READY`, `PARTICIPANT_STATE`, `PLAY_AT`,
  `PLAYBACK_STATUS`, `SYNC_CORRECTION`, and structured errors implemented
- Sequence and generation checks covered by automated tests
- All-ready scheduling chooses one future timestamp shared by every client
- Drift calculation uses the authoritative timeline and selects rate or seek
  corrections from configurable thresholds
- Sync sessions and idempotent Jam request IDs persist in Sync's PostgreSQL
  database; restart recovery is covered by an automated test
- Readiness timeout status is exposed only to Jam, including ready/unready
  participants; Jam can forward `CONTINUE`, `WAIT`, or `CANCEL`
- `CONTINUE` broadcasts `PLAY_AT` only to ready participants, `WAIT` extends
  the preparation deadline, and `CANCEL` ends the playback attempt
- JSON Schema examples validate in the repository contract checker
- A browser development harness now buffers and plays a generated test melody,
  performs five clock samples, schedules Web Audio from `PLAY_AT`, reports
  playback status, and displays the measured start error
- Five isolated local Chromium sessions completed one Jam start using the
  same target timestamp; the latest measured timer-start errors were 6, 3, 4,
  4, and 4 ms (3 ms max-to-min spread)
- Periodic reports drove scheduled seek corrections in headless Web Audio; an
  injected 400 ms delay produced `SEEK (-403ms)` and did not cause a repeated
  correction before the generated melody ended
- The five-browser result is loopback evidence only; the Slice 7 physical
  device and real-Wi-Fi test remains required
- Per-participant correction hysteresis and a configurable cooldown now
  prevent correction spam while permitting a medium-drift rate adjustment
  to escalate to a large-drift scheduled seek
- A reconnect during `SCHEDULED` receives the unchanged shared `PLAY_AT` and
  can restart its client sequence counter; a join during `PLAYING` receives
  a future catch-up timestamp and calculated authoritative position without
  disturbing existing participants
- Authenticated Jam-only pause, resume, seek, and skip adapters now update and
  persist the authoritative timeline before broadcasting `PAUSE_AT`,
  `RESUME_AT`, `SEEK_TO`, or the next generation's `PREPARE`
- Control request IDs suppress duplicate broadcasts, stale generations are
  rejected, skip resets participant readiness, and the browser development
  harness understands all three scheduled control messages
- `PAUSE_AT`, `RESUME_AT`, and `SEEK_TO` now have validated JSON Schemas and
  examples alongside the existing WebSocket contracts
- Python bindings are generated from the versioned Sync proto and an
  authenticated `SyncControlService` now runs beside FastAPI on internal port
  50051, covering start, pause, resume, seek, skip, readiness decisions, and
  state/readiness queries
- In-process generated-client tests cover the complete gRPC control flow,
  unauthenticated access, invalid UUID mapping, stale-generation status, and
  client deadline expiry
- Catalogue and Streaming now sit behind async client interfaces with
  deterministic fakes; start and skip require a ready catalogue song and an
  available stream before mutating the Sync session
- Dependency calls use a configurable 750 ms bound and distinguish not found,
  not ready, unavailable, and timeout failures across HTTP and gRPC; tests
  prove a dependency failure cannot create a false playback session
- Structured JSON logs, safe correlation IDs, and Prometheus metrics now cover
  HTTP, gRPC, WebSocket lifecycle, dependencies, timing, drift, corrections,
  and protocol failures
- WebSocket connections now enforce idle liveness, a 64 KiB message bound,
  per-connection rate limits, replacement/restart close codes, and graceful
  service shutdown
- Clock selection has deterministic latency, asymmetry, staleness, and outlier
  tests; the browser reports playback periodically and applies rate/seek
  corrections with a duration calculated to return drift to tolerance
- Alembic owns the deployed database schema and includes an upgrade/downgrade
  test plus adoption of databases created by the earlier bootstrap code
- The live remaining work is tracked in the checklist below; update it when a
  slice is completed instead of adding another separate status list

### 24.12.1 Current Sync Todo

Completed foundation:

- [x] Define the Jam/Sync ownership boundary and owner-only control flow
- [x] Create the Python/FastAPI service, health checks, Compose integration,
  PostgreSQL persistence, and restart recovery
- [x] Define and validate the WebSocket JSON Schemas and Sync gRPC contract
- [x] Generate the Python gRPC bindings and run the authenticated control
  service on internal port 50051
- [x] Implement join, clock sampling, prepare/readiness, scheduled playback,
  pause, resume, seek, skip, and readiness decisions
- [x] Implement authoritative timeline calculation, drift bands, hysteresis,
  cooldown, rate correction, and scheduled seek correction
- [x] Implement reconnect sequence reset, scheduled reconnect, and playing
  late-join catch-up
- [x] Add Catalogue/Streaming client boundaries, deterministic fakes,
  dependency timeouts, and stable HTTP/gRPC failure mapping
- [x] Build the browser melody harness and complete a five-browser loopback
  run with a measured 3 ms start-error spread
- [x] Cover the current slice with 43 automated tests and 14 validated
  WebSocket schemas/examples

Completed observability:

- [x] Add structured JSON logs with `jam_id`, `participant_id`, `generation`,
  `request_id`, message type, outcome, and duration where applicable
- [x] Propagate or generate correlation IDs across HTTP, gRPC, and WebSocket
  operations without logging tokens or signed stream URLs
- [x] Expose Prometheus metrics for connections, readiness, start error,
  drift, corrections, dependency duration/failures, and protocol errors
- [x] Add tests that verify required log context and metric increments

Then -- protocol and service hardening:

- [x] Add WebSocket heartbeat/liveness handling, maximum message size, and
  per-connection rate limits
- [x] Add explicit shutdown/reconnect close codes and test duplicate live
  connection replacement under load
- [x] Add deterministic clock-offset tests for asymmetric latency, jitter,
  stale samples, and outlier rejection
- [x] Send periodic browser `PLAYBACK_STATUS` reports and demonstrate that an
  intentionally delayed client converges after correction
- [x] Add Alembic migrations before making further deployed schema changes
- [ ] Replace the temporary internal HTTP adapters after Jam switches to the
  generated gRPC client
- [ ] Replace Catalogue/Streaming fakes with real deadline-bound gRPC clients
  when those versioned contracts become available

Final integration and evidence:

- [ ] Run the full Jam-to-Sync flow through the real Jam service and production
  frontend, including members queueing while only the owner controls playback
- [ ] Run at least 20 starts across physical laptops/phones on real Wi-Fi and
  record P50/P95/max client-to-client start difference
- [ ] Measure stable-playback drift, correction count, reconnect recovery, and
  results under injected latency/jitter/packet loss
- [ ] Tune lead time and correction thresholds from the measurements, then
  record the final configuration and any missed targets honestly
- [x] Add dashboards/log queries, the final demo procedure, known limitations,
  and the documented path to multi-instance routing/pub-sub

#### Slice 0 --- Contracts and skeleton

- Agree the Sync/Jam boundary with the Jam implementation
- Document Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, `asyncpg`, and
  `grpcio` as the Sync technology stack
- Create `services/sync/` from the service template
- Add `/health` and `/ready` endpoints
- Add the service to root Docker Compose and gateway routing
- Add configuration validation and structured logging
- Define the common WebSocket frame and error schema

**Exit check:** the Sync container becomes healthy in the full local stack,
and CI validates its contracts.

#### Slice 1 --- WebSocket connection and membership

- Add the WebSocket endpoint
- Validate join credentials/membership
- Track connect, disconnect, heartbeat, sequence number, and participant ID
- Return `JOINED` and broadcast participant presence
- Add malformed-message, unauthorized-join, duplicate-connection, and
  disconnect tests

**Exit check:** two browser tabs join one Jam, see each other's presence,
and a non-member is rejected.

#### Slice 2 --- Clock synchronization

- Implement `TIME_PING`/`TIME_PONG`
- Implement client-side sampling and estimate selection
- Expose timing metrics on the test client
- Unit-test the formulas with symmetric and asymmetric artificial latency
- Test stale sample refresh and outlier rejection

**Exit check:** two clients show stable estimated offset and round-trip
delay under injected latency.

#### Slice 3 --- Prepare and readiness

- Add Jam's internal `StartPlayback` operation plus WebSocket `PREPARE` and
  `READY`
- Add generation handling and the `PREPARING` state
- Integrate Catalogue and Streaming fakes, then their real gRPC services
- Implement the readiness timeout and explicit owner decision prompt
- Handle song-not-ready and stream-unavailable failures

**Exit check:** two clients receive the same song/stream metadata, buffer,
and become ready; stale readiness cannot start a newer generation. If one
client remains unready, Sync reports this to Jam and only the owner can
choose through Jam to continue without that client.

#### Slice 4 --- Scheduled playback

- Add `PLAY_AT`
- Persist the timeline before broadcasting it
- Schedule browser playback using the offset estimate
- Measure actual start error on each client
- Add pause, resume, seek, skip, and duplicate-command handling

**Exit check:** laptop and phone start the same track from one future server
timestamp, and the test UI records the measured difference.

#### Slice 5 --- Drift detection and correction

- Add periodic `PLAYBACK_STATUS`
- Calculate expected position and drift from the authoritative anchor
- Add correction bands, hysteresis, and cooldown
- Implement scheduled seek first; rate correction can follow
- Add buffering awareness and correction audit logs

**Exit check:** an intentionally delayed client is detected and returns
within the configured tolerance without disrupting other clients.

#### Slice 6 --- Reconnect, late join, and failures

- Restore session state after a Sync process restart
- Re-sample clocks after reconnect
- Catch a late joiner up to the authoritative position
- Add dependency deadlines and mapped errors
- Add clean shutdown, WebSocket close reasons, and overload/rate limits

**Exit check:** disconnect/reconnect, late join, unavailable dependency,
and Sync restart are demonstrated without corrupting the Jam timeline.

#### Slice 7 --- Hardening and evidence

- Add metrics, dashboards/log queries, and correlation IDs
- Run multi-device tests on real Wi-Fi
- Record results for at least 20 scheduled starts
- Tune lead time and drift thresholds from measured percentiles
- Document limitations and the path to multi-instance scaling
- Complete CI, Docker, contract, integration, and end-to-end tests

**Exit check:** the service meets its Definition of Done and the demo has
reproducible measurements rather than an unsupported accuracy claim.

### 24.13 Test Plan

#### Unit tests

- State-machine transitions and invalid transitions
- Expected-position calculation while playing and paused
- Clock-offset and round-trip formulas
- Timing-sample selection and outlier rejection
- Readiness policy and timeout
- Drift bands, hysteresis, and cooldown
- Stale sequence/generation rejection
- Idempotent internal Jam commands
- Rejection of direct browser playback commands to Sync

Use a fake clock in tests. Timing tests should advance the clock
deterministically and must not depend on real `sleep` calls.

#### Contract tests

- Every WebSocket example validates against its JSON Schema
- Invalid payloads are rejected with the documented error code
- Generated gRPC clients and servers agree with `.proto` files
- Breaking contract changes are caught in CI

#### Integration tests

- Sync + Postgres persistence
- Sync + fake/real Catalogue and Streaming gRPC dependencies
- Two WebSocket clients completing `PREPARE -> READY -> PLAY_AT`
- One slow participant causing an owner prompt, followed by `CONTINUE`,
  `WAIT`, and `CANCEL` test cases
- Disconnect/reconnect and late join
- Dependency timeout without a false `PLAY_AT`

#### End-to-end and physical tests

- Two tabs on one machine as the fast feedback test
- Laptop plus two phones on the same Wi-Fi as the required device test
- Add artificial delay, jitter, duplicate messages, reordering, and packet
  loss where the chosen tools allow it
- Capture target start, actual start, initial error, maximum drift,
  corrections, and reconnect recovery time

Suggested acceptance targets must be validated, not promised in advance:

``` text
No client starts before it is ready.
No stale generation can change the active session.
P95 client-to-client start difference is <= 100 ms under the documented
demo conditions, or the measured result and reason for missing it are
reported honestly.
P95 absolute drift during stable playback is measured and reported.
A reconnecting client rejoins without restarting the room.
```

### 24.14 Observability

Use structured logs with `jam_id`, `participant_id`, `connection_id`,
`generation`, `request_id`, and message type where applicable. Never log
tokens or complete signed stream URLs.

Useful metrics:

``` text
sync_websocket_connections
sync_clock_offset_ms
sync_round_trip_delay_ms
sync_prepare_duration_ms
sync_ready_participants
sync_start_error_ms
sync_drift_ms
sync_corrections_total{method,reason}
sync_dependency_duration_ms{service,method,status}
sync_protocol_errors_total{code}
```

Key lifecycle logs should cover join, disconnect, generation change,
prepare, ready, scheduled start, state transition, correction, dependency
failure, and reconnect. These records are also useful evidence for the
project demonstration and report.

### 24.15 Security and Reliability Checklist

- Authenticate the WebSocket handshake
- Authenticate internal Jam-to-Sync commands; Jam authorizes owner actions
- Validate Jam membership on join and reconnect
- Validate JSON types, ranges, UUIDs, message size, and allowed message type
- Rate-limit connections, timing pings, and status reports
- Use TLS (`wss://`) outside local development
- Put secrets in environment/secret storage, never Git or logs
- Set gRPC deadlines and bounded retries with jitter
- Make internal Jam commands idempotent with `request_id`
- Reject direct browser playback-control commands at Sync
- Require a Jam-forwarded owner decision before excluding an unready
  participant
- Persist the timeline before publishing it
- Reject stale generation and sequence values
- Close connections cleanly during shutdown
- Return readiness failure when required dependencies are unavailable

### 24.16 Sync Service Definition of Done

The Sync Service is complete for the project when:

- Its responsibility boundary with Jam is documented
- WebSocket and gRPC contracts are versioned and validated in CI
- The service runs in Docker Compose and passes health/readiness checks
- Two or more clients complete `PREPARE -> READY -> PLAY_AT`
- Clock offset is estimated from multiple samples
- The server maintains an authoritative, persisted playback timeline
- Drift is measured and significant drift triggers a bounded correction
- The 100 ms synchronization target is tested and the result is recorded
- An unready participant produces an owner decision prompt
- Queueing and owner controls remain in Jam; Sync only executes the
  resulting playback coordination commands
- Pause, resume, seek/skip, late join, and reconnect have defined behaviour
- Invalid, duplicate, reordered, and stale messages are safe
- Dependency failures never cause a false synchronized start
- Unit, contract, integration, and physical multi-device tests pass
- Logs and metrics explain what happened for a Jam and generation
- Measured synchronization results and known limitations are documented

### 24.17 Recommended Work Order for Azeez

- [x] Document the agreed Jam-to-Sync hand-off and WebSocket frame
- [x] Define JSON Schemas and gRPC proto files
- [x] Create the Python/FastAPI Sync skeleton and Compose integration
- [x] Connect multiple clients over WebSocket
- [x] Implement and measure clock sampling
- [x] Implement `PREPARE` and generation-safe `READY` tracking
- [x] Implement persisted `PLAY_AT` scheduling
- [x] Add pause/resume/seek and authoritative timeline updates
- [x] Add playback reports and drift correction
- [x] Add reconnect, late join, and dependency failure handling
- [ ] Run physical-device tests and tune configuration
- [ ] Document final physical results, limitations, and demo procedure

Integrate after every small slice. Do not wait for all synchronization
features to be complete before testing with Jam, Catalogue, Streaming, and
the browser.
