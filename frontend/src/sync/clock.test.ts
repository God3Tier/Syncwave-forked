import { describe, expect, it } from 'vitest';
import { compensateSchedule, delayUntil, estimate, pushSample, toSample } from './clock';
import { isStale, makeFrameFactory } from './protocol';

describe('toSample', () => {
  it('computes offset and round-trip delay for symmetric latency', () => {
    // Server clock is 1000 ms ahead; 20 ms each way; server spends 2 ms.
    const sample = toSample({ client_sent_ms: 0, server_received_ms: 1020, server_sent_ms: 1022 }, 42);
    expect(sample).toEqual({ offsetMs: 1000, delayMs: 40 });
  });

  it('attributes asymmetric latency half to each direction', () => {
    // 30 ms out, 10 ms back, true offset 500: estimate is off by (30-10)/2 = 10.
    const sample = toSample({ client_sent_ms: 0, server_received_ms: 530, server_sent_ms: 530 }, 40);
    expect(sample).toEqual({ offsetMs: 510, delayMs: 40 });
  });

  it('rejects impossible timings', () => {
    expect(toSample({ client_sent_ms: 100, server_received_ms: 5, server_sent_ms: 6 }, 90)).toBeNull();
    expect(toSample({ client_sent_ms: 0, server_received_ms: 10, server_sent_ms: 5 }, 20)).toBeNull();
    expect(toSample({ client_sent_ms: 0, server_received_ms: 0, server_sent_ms: 50 }, 10)).toBeNull();
  });
});

describe('estimate', () => {
  it('uses the median offset of the three lowest-delay samples', () => {
    const result = estimate([
      { offsetMs: 100, delayMs: 10 },
      { offsetMs: 300, delayMs: 200 }, // slow outlier, ignored
      { offsetMs: 104, delayMs: 12 },
      { offsetMs: 98, delayMs: 11 },
      { offsetMs: -50, delayMs: 150 }, // slow outlier, ignored
    ]);
    expect(result).toEqual({ offsetMs: 100, rttMs: 10, samples: 5 });
  });

  it('returns null without samples and works with one', () => {
    expect(estimate([])).toBeNull();
    expect(estimate([{ offsetMs: 7, delayMs: 3 }])).toEqual({ offsetMs: 7, rttMs: 3, samples: 1 });
  });

  it('keeps a bounded window of recent samples', () => {
    let samples: { offsetMs: number; delayMs: number }[] = [];
    for (let i = 0; i < 12; i++) samples = pushSample(samples, { offsetMs: i, delayMs: 1 }, 8);
    expect(samples).toHaveLength(8);
    expect(samples[0].offsetMs).toBe(4);
  });
});

describe('delayUntil', () => {
  it('converts a server target into a local delay', () => {
    // Local clock reads 1000, server is 250 ms ahead, so server now = 1250.
    expect(delayUntil(3250, 250, 1000)).toBe(2000);
    expect(delayUntil(1200, 250, 1000)).toBe(-50);
  });
});

describe('compensateSchedule', () => {
  it('keeps future targets at their requested position', () => {
    expect(compensateSchedule(2_000, 500, 1, 10_000, 0, 1_000)).toEqual({
      delayMs: 1_000,
      latenessMs: 0,
      positionMs: 500,
      ended: false,
    });
  });

  it('advances late targets by playback rate and clamps at the end', () => {
    expect(compensateSchedule(950, 2_000, 1.5, 10_000, 0, 1_000).positionMs).toBe(2_075);
    expect(compensateSchedule(0, 9_900, 1, 10_000, 0, 1_000)).toMatchObject({
      delayMs: 0,
      positionMs: 10_000,
      ended: true,
    });
  });
});

describe('protocol', () => {
  it('numbers client frames with a strictly increasing seq', () => {
    const frame = makeFrameFactory('jam-1');
    const a = frame('TIME_PING', {});
    const b = frame('READY', { generation: 1 });
    expect(a.seq).toBe(0);
    expect(b.seq).toBe(1);
    expect(b).toMatchObject({ type: 'READY', jam_id: 'jam-1', payload: { generation: 1 } });
  });

  it('treats messages from older generations as stale', () => {
    expect(isStale(3, { generation: 2 })).toBe(true);
    expect(isStale(3, { generation: 3 })).toBe(false);
    expect(isStale(3, { generation: 4 })).toBe(false);
    expect(isStale(3, { sample_id: 'x' })).toBe(false);
  });
});
