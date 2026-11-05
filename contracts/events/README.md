# AMQP events (Scenario 2: Upload & Process choreography)

The executable form of this contract is
[`infrastructure/rabbitmq/definitions.json`](../../infrastructure/rabbitmq/definitions.json).
It is loaded into RabbitMQ at start-up, locally by the `rabbitmq-init`
container and in production by the same file. This README explains it.
**Change both in the same MR.**

## Files in this folder

| File                          | Purpose                                                       |
|-------------------------------|---------------------------------------------------------------|
| `envelope.schema.json`        | Shape shared by every event (`event_id`, `event_type`, ...)   |
| `<event-name>.schema.json`    | One per event, added by the producer's owner (see below)      |
| `examples/<name>.json`        | Example message; CI validates it against `<name>.schema.json` |

Every schema's `$id` must be `https://syncwave.local/<its path in the repo>`;
CI enforces this so relative `$ref`s resolve.

A per-event schema reuses the envelope and constrains the payload:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://syncwave.local/contracts/events/song-uploaded.schema.json",
  "type": "object",
  "allOf": [{ "$ref": "envelope.schema.json" }],
  "properties": {
    "event_type": { "const": "SongUploaded" },
    "payload": {
      "type": "object",
      "required": ["audio_reference"],
      "properties": { "audio_reference": { "type": "string" } }
    }
  }
}
```

## Event catalogue

| `event_type`               | Routing key          | Producer  | Consumed by (queue)                   |
|----------------------------|----------------------|-----------|---------------------------------------|
| `SongUploaded`             | `song.uploaded`      | Upload    | Catalogue, Lyrics, Waveform           |
| `LyricsProcessed`          | `lyrics.processed`   | Lyrics    | Catalogue                             |
| `LyricsProcessingFailed`   | `lyrics.failed`      | Lyrics    | Catalogue                             |
| `WaveformProcessed`        | `waveform.processed` | Waveform  | Catalogue                             |
| `WaveformProcessingFailed` | `waveform.failed`    | Waveform  | Catalogue                             |
| `MoodProcessed`            | `mood.processed`     | Catalogue | Catalogue                             |
| `SongReady`                | `song.ready`         | Catalogue | Search                                |

Catalogue publishes `SongReady` once `processing_status` becomes `READY`
(see the Song contract in [`../README.md`](../README.md)).

### Payloads

The per-event schemas are the source of truth; this is a summary.

| `event_type`               | Schema                                     | `payload`                                              |
|----------------------------|--------------------------------------------|--------------------------------------------------------|
| `SongUploaded`             | `song-uploaded.schema.json` (**proposal**) | `audio_reference` (S3 key), optional `lyrics_reference` (S3 key of an `.lrc` file; absent/null = no lyrics) |
| `LyricsProcessed`          | `lyrics-processed.schema.json`             | `line_count`, optional `mood`                          |
| `LyricsProcessingFailed`   | `lyrics-processing-failed.schema.json`     | `error_code`, `message`, `attempts`                    |
| `WaveformProcessed`        | `waveform-processed.schema.json`           | `points`, `duration_ms`                                |
| `WaveformProcessingFailed` | `waveform-processing-failed.schema.json`   | `error_code`, `message`, `attempts`                    |
| `MoodProcessed`            | `mood-processed.schema.json`               | `song_id`, `mood`                                      |

`song-uploaded.schema.json` was written by the Lyrics/Waveform owner so the consumers could be built before the Upload Service. It now also carries the canonical song metadata (`title`, `artist`) so 
Catalogue can create the initial Song record. 
Upload may add further payload fields; consumers ignore fields they do not use. 
Catalogue ignores `duration_ms` until Waveform measures it.

Follow-up events copy the `SongUploaded` `event_id` into `correlation_id`.

Catalogue creates each song from `SongUploaded`, then updates
`lyrics_status`/`waveform_status` from `LyricsProcessed`/`WaveformProcessed`
(and their `...Failed` variants), derives `processing_status`, and publishes
`SongReady` only when the song first becomes fully `READY`. PARTIAL songs are never published.
`…Processed` can be published more than once for the same song (a
duplicate `SongUploaded` delivery re-announces the stored result), so
Catalogue must treat it idempotently.

## Topology

```text
                         syncwave.events (topic)
   song.uploaded ──────────┬──────────────────────────┐
                           v                          v
              lyrics.song-uploaded        waveform.song-uploaded
   lyrics.* / waveform.* ──> catalogue.processing-results
   song.ready ─────────────> search.song-ready

  every consumer queue <q> also has:
     <q> --(nack, requeue=false)--> syncwave.retry --> <q>.retry --(after 10 s TTL)--> <q>
     consumer gives up after 3 attempts --> publish to syncwave.dlx --> <q>.dlq
```

| Exchange          | Type   | Purpose                                                    |
|-------------------|--------|------------------------------------------------------------|
| `syncwave.events` | topic  | All domain events. Producers publish only here.            |
| `syncwave.retry`  | direct | Rejected messages wait in `<q>.retry` before coming back.  |
| `syncwave.dlx`    | direct | Final resting place: `<q>.dlq`, inspected by a human.      |

Queue names follow `<consumer>.<what-it-consumes>`. To add a consumer,
add its queue, its `.retry` and `.dlq` queues and the bindings to
`definitions.json`, mirroring the existing entries, and update the tables
above.

## Rules for producers

- Publish to `syncwave.events` with the routing key from the catalogue.
- Message body is the JSON envelope; set `content_type=application/json`,
  `delivery_mode=2` (persistent), `message_id=<event_id>` and
  `type=<event_type>`.
- Publish only **after** your own state change has been committed, so a
  consumer never sees an event for data that does not exist yet.

## Rules for consumers

- **Do not redeclare queues with different arguments.** The topology is
  owned by `definitions.json`. Declare queues *passively*, or not at all,
  otherwise RabbitMQ rejects the declaration with `PRECONDITION_FAILED`.
- Use manual acknowledgements and a small prefetch (e.g. 10).
- **Be idempotent.** The same event can be delivered more than once. Use
  `event_id` together with your own processing state, e.g.
  "lyrics for this `song_id` are already `READY`", to skip duplicate work
  (plan.md §16).
- **Retrying a transient failure** (S3 hiccup, database briefly down):
  `nack` with `requeue=false`. The message waits 10 s in `<q>.retry` and
  then returns to `<q>`. The message's `x-death` header records earlier
  failures: the entry whose `queue` is `<q>` and whose `reason` is
  `rejected` has a `count` of previous failed attempts (no entry = first
  attempt).
- **Giving up** on the 3rd failed attempt (`count` already 2), or immediately for a permanent failure
  such as an invalid payload: publish the original message unchanged to
  `syncwave.dlx` with routing key `<q>`, then `ack` it. Also publish your
  `...Failed` event so Catalogue can record the failure.
- Messages in a `.dlq` stay there until someone looks at them in the
  RabbitMQ management UI (<http://localhost:15672>).
