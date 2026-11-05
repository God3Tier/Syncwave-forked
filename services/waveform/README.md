# Waveform Service

**Owner:** Jiawen · **Language/framework:** Python 3.14 / FastAPI, aio-pika, SQLAlchemy + Alembic, ffmpeg + numpy

Owns the complete waveform capability (plan.md §3): it consumes
`SongUploaded`, reads the uploaded audio from S3 and reduces it to data for
playback visualisation:

- **peaks**: an overview of the whole song, e.g. for the seek bar;
- **bands**: how loud each frequency band is, 25 times a second, for a
  visualiser that pulses with the music like the bars in a lyrics video.

It announces the result with `WaveformProcessed` / `WaveformProcessingFailed`
and serves both to the browser.

## Interfaces

| Kind             | Contract                                                              | Notes |
|------------------|-----------------------------------------------------------------------|-------|
| REST             | [`contracts/api/waveform.openapi.yaml`](../../contracts/api/waveform.openapi.yaml) | via gateway at `/api/waveform/...` |
| Events consumed  | `SongUploaded` from queue `waveform.song-uploaded`                    | reads `payload.audio_reference` |
| Events published | `WaveformProcessed` (`waveform.processed`), `WaveformProcessingFailed` (`waveform.failed`) | [`contracts/events/`](../../contracts/events/README.md) |
| gRPC             | none                                                                  | |

```text
waveform.song-uploaded ──> waveform-worker ──> S3: audio/<song_id>.mp3
                                │ ffmpeg: mono 16-bit PCM at 22.05 kHz
                                │ numpy: loudest sample per slice -> 1000 peaks
                                │ numpy: spectrum every 40 ms -> 50 band levels
                                ├──> Postgres: waveforms (status, peaks, bands, duration)
                                └──> syncwave.events: waveform.processed | waveform.failed

browser ──> gateway /api/waveform/songs/{song_id}/waveform?points=N ──> waveform (API) ──> Postgres
browser ──> gateway /api/waveform/songs/{song_id}/waveform/bands ──────┘
```

One image runs as two processes, following the layout in plan.md:

| Folder (`src/waveform_service/`) | Process                                    | What                                     |
|----------------------------------|--------------------------------------------|------------------------------------------|
| `api/`                           | `waveform` (default command, port 8080)    | read-only HTTP API                       |
| `worker/`                        | `waveform-worker` (`python -m waveform_service.worker`) | AMQP consumer: retries, DLQ, idempotency |
| `shared/`                        | both                                       | decoding and peaks, database, events, S3 |

### How the waveform is computed

1. Download the audio from S3 to a temporary file (refused up front if it is
   larger than `WAVEFORM_MAX_AUDIO_BYTES`).
2. ffmpeg decodes any format it understands to mono 16-bit PCM at
   `WAVEFORM_SAMPLE_RATE` (22.05 kHz, so the bands reach 11 kHz). 10
   minutes of audio is about 26 MB in memory.
3. **Peaks:** the samples are split into `WAVEFORM_POINTS` (1000) equal
   slices. Each peak is the loudest sample in its slice as a fraction of full
   scale, 0..1, rounded to 3 decimal places. `duration_ms` comes from the
   sample count.
4. **Bands:** `WAVEFORM_FRAME_RATE` (25) times a second, the spectrum of the
   surrounding ~93 ms of audio (Hann-windowed FFT) is integrated over
   `WAVEFORM_BANDS` (50) bands, log-spaced from 50 Hz to 11 kHz. The
   spectrum is interpolated between FFT bins, so the bass bands below
   ~95 Hz, narrower than one bin, still move on their own. Each band's
   power in dB is tilted up 3 dB per octave, so the treble moves as visibly
   as the bass, then scaled to one byte: 255 for the song's loudest moments,
   0 for 48 dB below them (or silence). A 4-minute song is 6000 frames:
   300 KB, or 400 KB as base64.

The API's `?points=N` returns fewer peaks for a narrower display: each
returned peak is the maximum of the stored peaks it covers, so short loud
moments stay visible.

`GET .../waveform/bands` returns the levels base64-encoded. To draw the
visualiser at playback position `t` seconds, read frame
`floor(t * frame_rate)`: its `band_count` bytes, lowest band first. The
browser can smooth between frames; the service stores them unsmoothed.

Download, ffmpeg and numpy run in a worker thread, so the AMQP connection
keeps answering heartbeats during a long decode. The prefetch is 2 because
decoding is CPU-heavy; run more `waveform-worker` replicas to go faster.

## Data owned

Table `waveforms` in this service's own `waveform` database (migrations in
`migrations/`, applied by the API container on start-up):

| Column            | Meaning                                                    |
|-------------------|------------------------------------------------------------|
| `song_id`         | primary key                                                |
| `status`          | `PROCESSING`, `READY` or `FAILED`                          |
| `peaks`           | JSON array of `points` numbers, 0..1, start to end         |
| `points`          | number of peaks                                            |
| `duration_ms`     | audio duration measured while decoding                     |
| `sample_rate`     | rate the audio was decoded at                              |
| `bands`           | band levels, `bytea`: one byte per band per frame          |
| `band_edges_hz`   | JSON array of the band edges in Hz, lowest first           |
| `band_frame_rate` | band frames per second                                     |
| `error_code`, `error_message` | why it failed                                  |
| `source_event_id` | the `SongUploaded` event last processed                    |

The audio itself stays in S3, where the Upload Service put it.

## Configuration

See `.env.example` for every variable. Locally, Compose sets them
(`compose.yaml`); in production they come from the ECS task definitions
(`waveform` and `waveform-worker`). Specific to this service:

| Variable                    | Default     | Meaning                                         |
|-----------------------------|-------------|-------------------------------------------------|
| `AMQP_PREFETCH`             | `2`         | messages one worker processes concurrently      |
| `WAVEFORM_POINTS`           | `1000`      | peaks stored per song                           |
| `WAVEFORM_SAMPLE_RATE`      | `22050`     | decode rate (Hz); the bands reach half of it    |
| `WAVEFORM_FRAME_RATE`       | `25`        | band frames per second                          |
| `WAVEFORM_BANDS`            | `50`        | frequency bands per frame                       |
| `WAVEFORM_MAX_AUDIO_BYTES`  | `209715200` | larger files fail with `AUDIO_TOO_LARGE`        |
| `WAVEFORM_DECODE_TIMEOUT_S` | `120`       | longer decodes fail with `DECODE_TIMEOUT`       |
| `DATABASE_URL`              | unset       | overrides `DB_*` (the tests use SQLite this way) |

## Run

```sh
# whole stack (from the repo root)
docker compose up -d --build

# just this service, after editing it
docker compose up -d --build waveform waveform-worker
curl http://localhost:8080/api/waveform/health
docker compose logs -f waveform-worker
```

### Try it without the Upload Service

From the repo root, with the stack running (Git Bash on Windows). Any audio
file works; this generates a 3-second tone that fades out:

```sh
SONG_ID=$(python -c "import uuid; print(uuid.uuid4())")
python -c "
import math, struct, wave
with wave.open('demo.wav', 'wb') as f:
    f.setnchannels(1); f.setsampwidth(2); f.setframerate(44100)
    f.writeframes(b''.join(struct.pack('<h', int(30000 * (1 - i / 132300) * math.sin(i / 20))) for i in range(132300)))
"

# 1. Put the audio in S3, as Upload would
curl -fsS --aws-sigv4 aws:amz:us-east-1:s3 --user syncwave:syncwave-secret \
  --upload-file demo.wav "http://localhost:9000/syncwave-audio/audio/$SONG_ID.wav"

# 2. Publish SongUploaded (Lyrics consumes it too: no lyrics_reference = instrumental)
sh tests/integration/publish-song-uploaded.sh "$SONG_ID" "audio/$SONG_ID.wav"

# 3. Read it back, 10 peaks wide, then the visualiser bands
curl -s "http://localhost:8080/api/waveform/songs/$SONG_ID/waveform?points=10"
curl -s "http://localhost:8080/api/waveform/songs/$SONG_ID/waveform/bands"
```

`WaveformProcessed` waits in the `catalogue.processing-results` queue until
Catalogue consumes it; peek at it in the RabbitMQ UI
(<http://localhost:15672>, Queues → `catalogue.processing-results` → Get messages).

## Test

```sh
cd services/waveform
python -m venv .venv
. .venv/Scripts/activate          # macOS/Linux: . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check src tests migrations && ruff format --check src tests migrations
pytest
```

The tests need no Docker: SQLite stands in for Postgres, in-memory fakes
for RabbitMQ and S3, and a fake decoder for ffmpeg in the worker tests. The
two tests that run the real ffmpeg are skipped when it is not installed;
CI installs it. `test_events_contract.py` checks every event the worker
publishes against the schemas in `contracts/events/`.

## Failure handling

The worker follows the consumer rules in
[`contracts/events/README.md`](../../contracts/events/README.md). Every
delivery ends in exactly one of:

| Outcome                     | When                                                       |
|-----------------------------|------------------------------------------------------------|
| `ack`                       | processed, or already `READY` (a duplicate delivery)       |
| retry (`reject`, 10 s wait) | a **transient** failure on attempt 1 or 2: S3 or the database unavailable, the audio not in S3 (yet), a decode timeout |
| give up                     | a **permanent** failure, or a transient one on the 3rd attempt |

Giving up records `FAILED` with the error code, moves the original message
unchanged to `waveform.song-uploaded.dlq`, publishes
`WaveformProcessingFailed` (so Catalogue can set `waveform_status = FAILED`),
then acks.

| `error_code`        | Kind      | Cause                                             |
|---------------------|-----------|---------------------------------------------------|
| `INVALID_EVENT`     | permanent | not a usable `SongUploaded` message (e.g. no `audio_reference`) |
| `AUDIO_TOO_LARGE`   | permanent | larger than `WAVEFORM_MAX_AUDIO_BYTES`            |
| `AUDIO_UNDECODABLE` | permanent | ffmpeg cannot decode it (not audio, corrupt)      |
| `AUDIO_EMPTY`       | permanent | decodes to no samples                             |
| `AUDIO_NOT_FOUND`   | transient | `audio_reference` missing from S3 after 3 attempts |
| `DECODE_TIMEOUT`    | transient | decoding took longer than `WAVEFORM_DECODE_TIMEOUT_S`, 3 times |
| `PROCESSING_ERROR`  | transient | anything else, after 3 attempts                   |

- **Duplicates (idempotency):** the `waveforms` row is the processing state.
  A `READY` song is never processed again; its `WaveformProcessed` is
  published again instead. That also repairs a crash between committing
  `READY` and publishing the event. A failure never overwrites a `READY`
  waveform.
- **Crash mid-message:** the message was not acked, so RabbitMQ redelivers
  it; the row stays `PROCESSING` until then. The temporary audio file is
  deleted even when processing fails.
- **Independent of Lyrics:** each has its own queue, retries and DLQ, so a
  slow or failing decode does not hold up the lyrics (the song becomes
  `PARTIAL`).
- **RabbitMQ or S3 down:** the API keeps serving stored waveforms; it needs
  only Postgres. The worker reconnects to RabbitMQ by itself.
- **Not handled:** replaying a DLQ is manual (RabbitMQ UI: move the messages
  back to `waveform.song-uploaded`; a `FAILED` song is then processed again).
  Changing `WAVEFORM_POINTS`, `WAVEFORM_FRAME_RATE` or `WAVEFORM_BANDS`
  does not regenerate existing waveforms.
