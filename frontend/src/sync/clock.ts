// Clock-offset estimation for the Sync protocol (plan.md §24.5), ported from
// the Sync demo client (services/sync/src/sync_service/demo.py).
//
//   t0 = client send, t1 = server receive, t2 = server send, t3 = client receive
//   round_trip_delay = (t3 - t0) - (t2 - t1)
//   clock_offset     = ((t1 - t0) + (t2 - t3)) / 2     (server = client + offset)

export interface ClockSample {
  offsetMs: number;
  delayMs: number;
}

export interface Pong {
  client_sent_ms: number;
  server_received_ms: number;
  server_sent_ms: number;
}

export interface ClockEstimate {
  offsetMs: number;
  rttMs: number;
  samples: number;
}

/** Converts one TIME_PONG into a sample, or null if its timings are impossible. */
export function toSample(pong: Pong, clientReceivedMs: number): ClockSample | null {
  const { client_sent_ms: t0, server_received_ms: t1, server_sent_ms: t2 } = pong;
  const t3 = clientReceivedMs;
  if (![t0, t1, t2, t3].every(Number.isFinite) || t3 < t0 || t2 < t1) return null;
  const delayMs = t3 - t0 - (t2 - t1);
  if (delayMs < 0) return null;
  return { offsetMs: (t1 - t0 + (t2 - t3)) / 2, delayMs };
}

/** Median offset of the three lowest-delay samples; the lowest delay is reported as the RTT. */
export function estimate(samples: readonly ClockSample[]): ClockEstimate | null {
  if (!samples.length) return null;
  const byDelay = [...samples].sort((a, b) => a.delayMs - b.delayMs);
  const best = byDelay.slice(0, 3).map((sample) => sample.offsetMs).sort((a, b) => a - b);
  return { offsetMs: best[Math.floor(best.length / 2)], rttMs: byDelay[0].delayMs, samples: samples.length };
}

/** Keeps the most recent `size` samples so the estimate follows slow drift. */
export function pushSample(samples: readonly ClockSample[], sample: ClockSample, size = 8): ClockSample[] {
  return [...samples, sample].slice(-size);
}

/** Milliseconds from now (local clock) until a server timestamp. */
export function delayUntil(targetServerMs: number, offsetMs: number, nowLocalMs: number = Date.now()): number {
  return targetServerMs - (nowLocalMs + offsetMs);
}
