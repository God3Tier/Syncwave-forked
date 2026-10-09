# WebSocket contract (Scenario 3: Jam & Sync)

Browsers connect through the gateway, e.g. `ws://localhost:8080/api/sync/ws`
(the gateway forwards WebSocket upgrades for every `/api/<service>/` path).
Which service hosts which socket (Jam, Sync, or both) is decided by the
Jam/Sync owner and recorded here.

> Status: **skeleton**. The message list comes from plan.md §8. Payloads
> are to be defined by the Jam/Sync owner before frontend work starts
> (plan.md §10), as `<message>.schema.json` files plus examples in
> `examples/`, which CI validates like the event schemas.

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
