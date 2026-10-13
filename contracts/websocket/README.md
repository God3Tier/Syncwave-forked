# WebSocket contract (Scenario 3: Jam & Sync)

Browsers connect through the gateway, e.g. `ws://localhost:8080/api/sync/ws`
(the gateway forwards WebSocket upgrades for every `/api/<service>/` path).
Jam remains the user-facing room and queue service. Browsers send playback
controls to Jam, Jam authorizes them, and Jam calls Sync internally. Sync
hosts the timing/readiness/playback-coordination socket; it does not accept
queue edits or owner playback commands directly from browsers.

> Status: **in progress**. `JOINED`, `TIME_PING`, `TIME_PONG`, `PREPARE`,
> `READY`, `PARTICIPANT_STATE`, `PLAY_AT`, `PAUSE_AT`, `RESUME_AT`,
> `SEEK_TO`, `PLAYBACK_STATUS`, `SYNC_CORRECTION`, and `ERROR` have JSON
> Schemas and examples validated by CI. Add each remaining message contract
> with its implementation slice.

## Proposed message frame

```json
{
  "type": "PLAY_AT",
  "jam_id": "8a1f...-uuid",
  "seq": 42,
  "sent_at_ms": 1791460000000,
  "payload": { }
}
```

- `type`: one of the messages below.
- `seq`: increases per sender; lets receivers drop stale or reordered messages.
- `*_ms`: integer epoch milliseconds. All timing fields use this so that
  clock-offset and `PLAY_AT(T)` arithmetic stays exact.

## Messages

| Type              | Direction       | Purpose                                              |
|-------------------|-----------------|------------------------------------------------------|
| `PAUSE_AT`        | server to client | Pause at a shared future time and position          |
| `RESUME_AT`       | server to client | Resume from a position at a shared future time      |
| `SEEK_TO`         | server to client | Seek at a shared time, preserving pause state       |
| `JOIN`            | client → server | Join a Jam                                           |
| `LEAVE`           | client → server | Leave a Jam                                          |
| `QUEUE_UPDATED`   | server → client | Shared queue changed                                 |
| `PREPARE`         | server → client | Pre-buffer this song from this offset                |
| `READY`           | client → server | Pre-buffering done                                   |
| `PLAY_AT`         | server → client | Start playback at server time `T` (ms)               |
| `PLAYBACK_STATUS` | client → server | Report current position, for drift measurement       |
| `SYNC_CORRECTION` | server → client | Seek or adjust to correct drift                      |
| `ERROR`           | server → client | Request failed (uses the shared error codes)         |

**Missing from plan.md §8:** the clock-offset exchange (protocol step 3)
needs its own request/response pair, e.g. `TIME_PING` (client sends
`client_sent_ms`) and `TIME_PONG` (server echoes it and adds
`server_received_ms` and `server_sent_ms`).
