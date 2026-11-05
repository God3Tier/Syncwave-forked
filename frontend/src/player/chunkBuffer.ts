export const BUFFER_OFFSETS = [-4, -3, -2, -1, 0, 1, 2, 3, 4] as const;
export const BUFFER_TARGETS_MS = [30_000, 30_000, 120_000, 120_000, 180_000, 120_000, 120_000, 30_000, 30_000] as const;
const PRIORITY = [0, 1, -1, 2, -2, 3, -3, 4, -4] as const;

export interface BufferSlot {
  offset: number;
  songId: string | null;
  targetMs: number;
  priority: number;
}

export function bufferSlots(queue: string[], index: number, constrained = false): BufferSlot[] {
  return BUFFER_OFFSETS.map((offset, slot) => {
    const queueIndex = index + offset;
    return {
      offset,
      songId: queueIndex >= 0 && queueIndex < queue.length ? queue[queueIndex] : null,
      targetMs: constrained
        ? offset === 0 ? 60_000 : Math.abs(offset) === 1 ? 30_000 : 10_000
        : BUFFER_TARGETS_MS[slot],
      priority: PRIORITY.indexOf(offset as (typeof PRIORITY)[number]),
    };
  });
}

type Pending<T> = {
  priority: number;
  run: () => Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
};

/** A tiny priority pool keeps media downloads bounded without a dependency. */
export class DownloadPool {
  private active = 0;
  private readonly pending: Pending<unknown>[] = [];

  constructor(private readonly limit = 2) {}

  schedule<T>(priority: number, run: () => Promise<T>): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      this.pending.push({ priority, run, resolve: resolve as (value: unknown) => void, reject });
      this.pending.sort((a, b) => a.priority - b.priority);
      this.drain();
    });
  }

  private drain() {
    while (this.active < this.limit && this.pending.length) {
      const job = this.pending.shift();
      if (!job) return;
      this.active += 1;
      job.run().then(job.resolve, job.reject).finally(() => {
        this.active -= 1;
        this.drain();
      });
    }
  }
}
