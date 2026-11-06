import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { SyncSession } from './syncSession';

class FakeSource {
  buffer: AudioBuffer | null = null;
  onended: (() => void) | null = null;
  playbackRate = { value: 1, setValueAtTime: vi.fn() };
  starts: Array<{ when: number; offset: number }> = [];
  stopped = false;

  connect(): void {}
  disconnect(): void {}
  start(when: number, offset: number): void { this.starts.push({ when, offset }); }
  stop(): void { this.stopped = true; }
}

class FakeSocket {
  static readonly OPEN = 1;
  static instance: FakeSocket;
  readyState = FakeSocket.OPEN;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  sent: string[] = [];

  constructor() { FakeSocket.instance = this; }
  send(value: string): void { this.sent.push(value); }
  close(): void {}
  emit(type: string, payload: Record<string, unknown>): void {
    this.onmessage?.({
      data: JSON.stringify({ type, jam_id: 'jam', seq: 1, sent_at_ms: Date.now(), payload }),
    } as MessageEvent);
  }
}

describe('SyncSession gapless playback', () => {
  const sources: FakeSource[] = [];
  const buffers = [
    { duration: 10 } as AudioBuffer,
    { duration: 12 } as AudioBuffer,
  ];

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(100_000);
    sources.length = 0;
    vi.stubGlobal('WebSocket', FakeSocket);
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      arrayBuffer: async () => new ArrayBuffer(1),
    })));
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('keeps the current source while decoding and scheduling the next source', async () => {
    const context = {
      state: 'running',
      currentTime: 10,
      destination: {},
      createGain: () => ({ gain: { value: 1 }, connect: vi.fn(), disconnect: vi.fn() }),
      createBufferSource: () => {
        const source = new FakeSource();
        sources.push(source);
        return source;
      },
      decodeAudioData: vi.fn(async () => buffers.shift() ?? ({ duration: 1 } as AudioBuffer)),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      resume: vi.fn(async () => undefined),
    } as unknown as AudioContext;
    const changes: string[] = [];
    const session = new SyncSession({
      jamId: 'jam',
      participantId: 'listener',
      context,
      onChange: (snapshot) => changes.push(`${snapshot.generation}:${snapshot.phase}`),
    });
    session.connect();
    const socket = FakeSocket.instance;
    const prepare = {
      queue_item_id: 'queue-1', song_id: 'song-1', stream_url: '/api/streaming/one',
      manifest_url: '/api/streaming/one/manifest', start_position_ms: 0,
    };

    socket.emit('PREPARE', { ...prepare, generation: 1 });
    await vi.waitFor(() => expect(session.state.phase).toBe('READY'));
    socket.emit('PLAY_AT', {
      generation: 1, target_server_time_ms: 100_100, start_position_ms: 0, playback_rate: 1,
    });
    await vi.waitFor(() => expect(sources).toHaveLength(1));
    const current = sources[0];

    socket.emit('PRELOAD', {
      ...prepare, generation: 2, queue_item_id: 'queue-2', song_id: 'song-2',
      stream_url: '/api/streaming/two',
    });
    await vi.waitFor(() => expect(socket.sent.some((value) => value.includes('"generation":2'))).toBe(true));
    expect(current.stopped).toBe(false);
    expect(sources).toHaveLength(1);

    socket.emit('TRANSITION_AT', {
      generation: 2,
      queue_item_id: 'queue-2',
      song_id: 'song-2',
      target_server_time_ms: 110_100,
      start_position_ms: 0,
      playback_rate: 1,
    });
    await vi.waitFor(() => expect(sources).toHaveLength(2));
    expect(sources[1].starts).toHaveLength(1);
    expect(sources[1].starts[0].offset).toBe(0);
    expect(sources[1].starts[0].when).toBeGreaterThan(current.starts[0].when);
    expect(current.stopped).toBe(false);

    await vi.advanceTimersByTimeAsync(10_100);
    expect(session.state.generation).toBe(2);
    expect(session.state.songId).toBe('song-2');
    expect(session.state.phase).toBe('PLAYING');
    expect(changes).toContain('2:PLAYING');
    session.close();
  });
});
