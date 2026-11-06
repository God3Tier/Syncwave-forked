# Sync observability and test runbook

## Metrics

Prometheus metrics are available at `GET /metrics` (or
`/api/sync/metrics` through the gateway). Useful starter queries are:

```promql
sync_websocket_connections
histogram_quantile(0.95, sum by (le) (rate(sync_start_error_ms_bucket[5m])))
histogram_quantile(0.95, sum by (le) (rate(sync_drift_ms_bucket[5m])))
sum by (method, reason) (increase(sync_corrections_total[15m]))
sum by (service, method, status) (rate(sync_dependency_duration_ms_count[5m]))
histogram_quantile(0.95, sum by (service, method, status, le) (rate(sync_dependency_duration_ms_bucket[5m])))
sum by (code) (increase(sync_protocol_errors_total[15m]))
```

Create dashboard panels for active connections, P95 start error, P95 drift,
corrections by method, dependency latency/failure status, and protocol errors.
Use the same time range for screenshots included in the final report.

## Structured logs

Application lifecycle records are emitted as one JSON object per line. Search
by `correlation_id` first, then narrow by `jam_id`, `generation`,
`participant_id`, `request_id`, or `message_type`.

Example `jq` queries:

```sh
jq 'select(.jam_id == "JAM_ID" and .generation == 2)' sync.log
jq 'select(.correlation_id == "CORRELATION_ID")' sync.log
jq 'select(.outcome == "failure" or .error_code != null)' sync.log
jq 'select(.event == "correction_issued")' sync.log
```

Tokens and complete signed stream URLs are deliberately excluded. HTTP and
gRPC callers may send `X-Correlation-ID`/`x-correlation-id`; WebSocket clients
may send the header where supported or the `correlation_id` query parameter.
Unsafe or missing values are replaced with a generated identifier.

## Physical-device acceptance run

The loopback result in the main README is not physical-device evidence. For
the final run:

1. Use desktop Chrome, desktop Safari, iPhone Safari and Android Chrome on the
   same documented Wi-Fi. If necessary, use two laptops so both desktop
   browsers can participate in the same run.
2. Synchronize each device through `/api/sync/demo` and confirm five clock
   samples complete before readiness.
3. Perform at least 20 fresh starts. Record every device's target timestamp,
   timer-start error, maximum absolute drift, and correction count.
4. Calculate each run's client-to-client spread as `max(start error) -
   min(start error)`, then report P50, P95, and maximum across the 20 runs.
5. Introduce one delayed client and show its drift returning to 30 ms or less.
6. Disconnect and reconnect one client; record recovery time and verify the
   room timeline does not restart.
7. On each phone, lock/background and restore the browser. Verify it remains
   Connected, becomes Not Ready, shows **Tap to resume audio** when automatic
   resume is blocked, and catches up after the tap. Exercise silent mode,
   media volume, speaker output, wired/Bluetooth output and route changes.
8. Pause from the owner and verify playback animation and local position stop
   on every device; resume and verify synchronized audio/animation returns.
9. Repeat a subset with injected latency/jitter/packet loss if the test
   environment supports it, recording the exact settings.
10. Export `/metrics`, the relevant correlation-filtered logs, device/browser
   versions, network conditions, and final configuration with the results.

Do not replace missing measurements with estimates. If P95 exceeds 100 ms,
report the actual value and conditions, then tune `START_LEAD_TIME_MS`, drift
thresholds, and clock sample policy before rerunning.

## Known scaling boundary

Live sockets and participant timing samples are process-local. A multi-instance
deployment needs sticky routing or a Jam-keyed connection registry plus shared
pub/sub (for example Redis or NATS) so a command received by one instance can
reach sockets owned by another. PostgreSQL remains the durable timeline store;
it is not used as a socket router.
