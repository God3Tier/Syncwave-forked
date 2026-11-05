import { describe, expect, it } from 'vitest';
import { DownloadPool, bufferSlots } from './chunkBuffer';

describe('bufferSlots', () => {
  it('represents the full -4 through +4 window at the middle of a queue', () => {
    const queue = Array.from({ length: 10 }, (_, index) => `song-${index}`);
    const slots = bufferSlots(queue, 4);
    expect(slots.map((slot) => slot.songId)).toEqual(queue.slice(0, 9));
    expect(slots.map((slot) => slot.targetMs)).toEqual([
      30_000, 30_000, 120_000, 120_000, 180_000, 120_000, 120_000, 30_000, 30_000,
    ]);
  });

  it('keeps edge positions explicit instead of wrapping the queue', () => {
    expect(bufferSlots(['a', 'b'], 0).map((slot) => slot.songId)).toEqual([
      null, null, null, null, 'a', 'b', null, null, null,
    ]);
  });

  it('keeps all nine positions while reducing constrained-device targets', () => {
    const slots = bufferSlots(Array.from({ length: 9 }, (_, index) => `${index}`), 4, true);
    expect(slots).toHaveLength(9);
    expect(slots.map((slot) => slot.targetMs)).toEqual([
      10_000, 10_000, 10_000, 30_000, 60_000, 30_000, 10_000, 10_000, 10_000,
    ]);
  });
});

describe('DownloadPool', () => {
  it('never runs more than two downloads concurrently', async () => {
    const pool = new DownloadPool(2);
    let active = 0;
    let peak = 0;
    const jobs = Array.from({ length: 6 }, (_, index) => pool.schedule(index, async () => {
      active += 1;
      peak = Math.max(peak, active);
      await new Promise((resolve) => setTimeout(resolve, 2));
      active -= 1;
    }));
    await Promise.all(jobs);
    expect(peak).toBe(2);
  });
});
