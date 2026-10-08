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
| `SongUploaded`             | `song.uploaded`      | Upload    | Lyrics, Waveform                      |
| `LyricsProcessed`          | `lyrics.processed`   | Lyrics    | Catalogue                             |
| `LyricsProcessingFailed`   | `lyrics.failed`      | Lyrics    | Catalogue                             |
| `WaveformProcessed`        | `waveform.processed` | Waveform  | Catalogue                             |
| `WaveformProcessingFailed` | `waveform.failed`    | Waveform  | Catalogue                             |
| `SongReady`                | `song.ready`         | Catalogue | Search                                |

Catalogue publishes `SongReady` once `processing_status` becomes `READY`
(see the Song contract in [`../README.md`](../README.md)).

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
