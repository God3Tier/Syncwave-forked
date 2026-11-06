// Browser side of synchronised Jam playback. Joins the Sync Service's
// WebSocket, estimates the clock offset, buffers the song on PREPARE, answers
// READY and schedules Web Audio playback at the server time given by PLAY_AT,
// then reports its position so Sync can correct drift.
//
// The behaviour mirrors the reference harness in
// services/sync/src/sync_service/demo.py, with the real stream instead of a
// test tone.

import { gatewayPath } from '../api/http';
import { uuid } from '../uuid';
import { config } from '../config';
import { compensateSchedule, estimate, pushSample, toSample, delayUntil, type ClockSample } from './clock';
import {
  isStale,
  makeFrameFactory,
  type CorrectionPayload,
  type Frame,
  type ParticipantStatePayload,
  type PauseAtPayload,
  type PlayAtPayload,
  type PreparePayload,
  type SeekToPayload,
  type TransitionAtPayload,
} from './protocol';

export type SyncPhase =
  | 'CONNECTING'
  | 'JOINED'
  | 'PREPARING'
  | 'READY'
  | 'SCHEDULED'
  | 'PLAYING'
  | 'PAUSE_SCHEDULED'
  | 'PAUSED'
  | 'ENDED'
  | 'CLOSED';

export type LocalAudioState = 'LOCKED' | 'RUNNING' | 'SUSPENDED' | 'ERROR';

export interface SyncSnapshot {
  phase: SyncPhase;
  generation: number;
  songId: string | null;
  offsetMs: number | null;
  rttMs: number | null;
  samples: number;
  targetServerMs: number | null;
  startErrorMs: number | null;
  lastDriftMs: number | null;
  driftHistory: number[];
  lastCorrection: { method: 'RATE' | 'SEEK'; driftMs: number; rate: number } | null;
  bufferedMs: number;
  mediaMs: number;
  participants: Record<string, { connected: boolean; ready: boolean }>;
  error: { code: string; message: string } | null;
  closeCode: number | null;
  localAudioState: LocalAudioState;
}

const initial: SyncSnapshot = {
  phase: 'CONNECTING',
  generation: 0,
  songId: null,
  offsetMs: null,
  rttMs: null,
  samples: 0,
  targetServerMs: null,
  startErrorMs: null,
  lastDriftMs: null,
  driftHistory: [],
  lastCorrection: null,
  bufferedMs: 0,
  mediaMs: 0,
  participants: {},
  error: null,
  closeCode: null,
  localAudioState: 'LOCKED',
};

export interface SyncSessionOptions {
  jamId: string;
  participantId: string;
  token?: string;
  context: AudioContext;
  onChange: (snapshot: SyncSnapshot) => void;
}

const INITIAL_SAMPLES = 5;

export class SyncSession {
  private readonly options: SyncSessionOptions;
  private readonly frame;
  private socket: WebSocket | null = null;
  private snapshot: SyncSnapshot = initial;
  private samples: ClockSample[] = [];
  private initialSamplesTaken = 0;
  private buffers = new Map<string, AudioBuffer>();
  private buffer: AudioBuffer | null = null;
  private source: AudioBufferSourceNode | null = null;
  private nextSource: AudioBufferSourceNode | null = null;
  private transitionTimer: ReturnType<typeof setTimeout> | null = null;
  private pendingGeneration: number | null = null;
  private pendingSongId: string | null = null;
  private gain: GainNode;
  private anchorContextTime = 0;
  private anchorPositionMs = 0;
  private rate = 1;
  private pendingStartErrorMs: number | null = null;
  private timers = new Set<ReturnType<typeof setTimeout>>();
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private status: ReturnType<typeof setInterval> | null = null;
  private queue: Promise<void> = Promise.resolve();
  private closed = false;

  constructor(options: SyncSessionOptions) {
    this.options = options;
    this.frame = makeFrameFactory(options.jamId);
    this.gain = options.context.createGain();
    this.gain.connect(options.context.destination);
  }

  get state(): SyncSnapshot {
    return this.snapshot;
  }

  connect(): void {
    const { jamId, participantId, token = config.syncToken } = this.options;
    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const params = new URLSearchParams({ jam_id: jamId, participant_id: participantId, token });
    const socket = new WebSocket(`${scheme}://${window.location.host}/api/sync/ws?${params}`);
    this.socket = socket;
    this.update({ localAudioState: this.options.context.state === 'running' ? 'RUNNING' : 'SUSPENDED' });
    this.options.context.addEventListener('statechange', this.onContextStateChange);
    socket.onmessage = (event) => {
      // Handle frames strictly in arrival order, even when one awaits audio decoding.
      this.queue = this.queue.then(() => this.handle(String(event.data))).catch((error) => {
        this.update({ error: { code: 'CLIENT_ERROR', message: String(error) } });
      });
    };
    socket.onopen = () => {
      this.heartbeat = setInterval(() => this.ping(), config.syncHeartbeatMs);
    };
    socket.onclose = (event) => {
      this.stopTimers();
      if (!this.closed) this.update({ phase: 'CLOSED', closeCode: event.code });
    };
  }

  close(): void {
    this.closed = true;
    this.stopTimers();
    this.stopSource();
    this.options.context.removeEventListener('statechange', this.onContextStateChange);
    this.socket?.close(1000, 'leaving');
    this.socket = null;
    this.gain.disconnect();
  }

  setVolume(value: number): void {
    this.gain.gain.value = value;
  }

  async resumeAudio(): Promise<boolean> {
    try {
      await this.options.context.resume();
      if (this.options.context.state !== 'running') {
        this.update({ localAudioState: 'SUSPENDED' });
        return false;
      }
      this.update({ localAudioState: 'RUNNING', error: null });
      this.sendBufferedReady();
      return true;
    } catch {
      this.update({
        localAudioState: 'ERROR',
        error: { code: 'AUDIO_RESUME_FAILED', message: 'This browser did not resume audio.' },
      });
      return false;
    }
  }

  /** Current playback position on this device. */
  positionMs(): number {
    const { context } = this.options;
    if (this.anchorContextTime === 0 || context.currentTime < this.anchorContextTime) return this.anchorPositionMs;
    return Math.max(0, this.anchorPositionMs + (context.currentTime - this.anchorContextTime) * 1000 * this.rate);
  }

  private update(patch: Partial<SyncSnapshot>): void {
    this.snapshot = { ...this.snapshot, ...patch };
    this.options.onChange(this.snapshot);
  }

  private send(type: Parameters<typeof this.frame>[0], payload: unknown): void {
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify(this.frame(type, payload)));
  }

  private ping(): void {
    this.send('TIME_PING', { sample_id: uuid(), client_sent_ms: Date.now() });
  }

  private later(fn: () => void, delayMs: number): void {
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      fn();
    }, Math.max(0, delayMs));
    this.timers.add(timer);
  }

  private stopTimers(): void {
    for (const timer of this.timers) clearTimeout(timer);
    this.timers.clear();
    if (this.heartbeat) clearInterval(this.heartbeat);
    if (this.status) clearInterval(this.status);
    this.heartbeat = null;
    this.status = null;
  }

  private stopSource(): void {
    if (this.source) {
      this.source.onended = null;
      try {
        this.source.stop();
      } catch {
        // never started or already stopped
      }
      this.source.disconnect();
      this.source = null;
    }
    if (this.nextSource) {
      this.nextSource.onended = null;
      try {
        this.nextSource.stop();
      } catch {
        // never started or already stopped
      }
      this.nextSource.disconnect();
      this.nextSource = null;
    }
    if (this.transitionTimer) clearTimeout(this.transitionTimer);
    this.transitionTimer = null;
  }

  private readonly onContextStateChange = (): void => {
    if (this.options.context.state === 'running') {
      this.update({ localAudioState: 'RUNNING' });
      this.sendBufferedReady();
      return;
    }
    this.update({ localAudioState: 'SUSPENDED' });
    this.send('NOT_READY', {
      generation: this.snapshot.generation,
      reason: this.options.context.state === 'suspended' ? 'AUDIO_SUSPENDED' : 'AUDIO_ERROR',
    });
  };

  private sendBufferedReady(): void {
    if (this.buffer) {
      const mediaMs = Math.round(this.buffer.duration * 1000);
      this.send('READY', { generation: this.snapshot.generation, buffered_duration_ms: mediaMs, media_duration_ms: mediaMs });
    }
    if (this.pendingGeneration !== null && this.pendingSongId) {
      const pending = this.buffers.get(this.pendingSongId);
      if (pending) {
        const mediaMs = Math.round(pending.duration * 1000);
        this.send('READY', { generation: this.pendingGeneration, buffered_duration_ms: mediaMs, media_duration_ms: mediaMs });
      }
    }
  }

  private offset(): number {
    return this.snapshot.offsetMs ?? 0;
  }

  private async handle(raw: string): Promise<void> {
    const message = JSON.parse(raw) as Frame;
    const payload = message.payload as Record<string, unknown>;
    if (isStale(this.snapshot.generation, payload)) return;

    switch (message.type) {
      case 'JOINED':
        this.update({
          phase: 'JOINED',
          generation: Number(payload.generation ?? 0),
          songId: (payload.song_id as string | null) ?? null,
          error: null,
          participants: (payload.participants as SyncSnapshot['participants'] | undefined) ?? {},
        });
        this.ping();
        return;
      case 'TIME_PONG':
        this.onPong(payload as unknown as Parameters<typeof toSample>[0]);
        return;
      case 'PREPARE':
        await this.prepare(payload as unknown as PreparePayload);
        return;
      case 'PRELOAD':
        await this.preload(payload as unknown as PreparePayload);
        return;
      case 'PARTICIPANT_STATE': {
        const p = payload as unknown as ParticipantStatePayload;
        this.update({ participants: { ...this.snapshot.participants, [p.participant_id]: { connected: p.connected, ready: p.ready } } });
        return;
      }
      case 'PLAY_AT':
      case 'RESUME_AT':
        this.schedulePlay(payload as unknown as PlayAtPayload);
        return;
      case 'TRANSITION_AT':
        this.scheduleTransition(payload as unknown as TransitionAtPayload);
        return;
      case 'PAUSE_AT':
        this.schedulePause(payload as unknown as PauseAtPayload);
        return;
      case 'SEEK_TO': {
        const seek = payload as unknown as SeekToPayload;
        if (seek.resume_playback) {
          this.schedulePlay({ generation: seek.generation, target_server_time_ms: seek.target_server_time_ms, start_position_ms: seek.position_ms });
        } else {
          this.schedulePause(seek);
        }
        return;
      }
      case 'SYNC_CORRECTION':
        this.correct(payload as unknown as CorrectionPayload);
        return;
      case 'ERROR':
        this.update({ error: { code: String(payload.code), message: String(payload.message ?? '') } });
        return;
    }
  }

  private onPong(pong: Parameters<typeof toSample>[0]): void {
    const sample = toSample(pong, Date.now());
    if (sample) this.samples = pushSample(this.samples, sample);
    const result = estimate(this.samples);
    if (result) this.update({ offsetMs: result.offsetMs, rttMs: result.rttMs, samples: result.samples });
    // Take the initial burst of samples back to back, then rely on the heartbeat.
    if (this.initialSamplesTaken < INITIAL_SAMPLES - 1) {
      this.initialSamplesTaken++;
      this.ping();
    }
  }

  private async prepare(payload: PreparePayload): Promise<void> {
    this.stopSource();
    this.update({ phase: 'PREPARING', generation: payload.generation, songId: payload.song_id, bufferedMs: 0, startErrorMs: null, error: null });
    let buffer = this.buffers.get(payload.song_id);
    if (!buffer) {
      let streamPath: string;
      try {
        streamPath = gatewayPath(payload.stream_url);
      } catch {
        this.update({ error: { code: 'STREAM_UNAVAILABLE', message: 'The stream URL is not a SyncWave API path' } });
        return;
      }
      const response = await fetch(streamPath);
      if (!response.ok) {
        this.update({ error: { code: 'STREAM_UNAVAILABLE', message: `Audio request failed (${response.status})` } });
        return;
      }
      buffer = await this.options.context.decodeAudioData(await response.arrayBuffer());
      this.buffers.set(payload.song_id, buffer);
    }
    // A newer PREPARE may have arrived while this one was decoding.
    if (payload.generation !== this.snapshot.generation) return;
    this.buffer = buffer;
    this.anchorContextTime = 0;
    this.anchorPositionMs = payload.start_position_ms;
    const mediaMs = Math.round(buffer.duration * 1000);
    this.send('READY', { generation: payload.generation, buffered_duration_ms: mediaMs, media_duration_ms: mediaMs });
    this.update({ phase: 'READY', bufferedMs: mediaMs, mediaMs });
  }

  private async preload(payload: PreparePayload): Promise<void> {
    this.pendingGeneration = payload.generation;
    this.pendingSongId = payload.song_id;
    let buffer = this.buffers.get(payload.song_id);
    if (!buffer) {
      let streamPath: string;
      try {
        streamPath = gatewayPath(payload.stream_url);
      } catch {
        this.update({ error: { code: 'STREAM_UNAVAILABLE', message: 'The next stream URL is invalid' } });
        return;
      }
      const response = await fetch(streamPath);
      if (!response.ok) {
        this.update({ error: { code: 'STREAM_UNAVAILABLE', message: `Next audio request failed (${response.status})` } });
        return;
      }
      try {
        buffer = await this.options.context.decodeAudioData(await response.arrayBuffer());
      } catch {
        this.update({ error: { code: 'DECODE_FAILED', message: 'The next song could not be decoded' } });
        return;
      }
      this.buffers.set(payload.song_id, buffer);
      while (this.buffers.size > 2) {
        const oldest = this.buffers.keys().next().value;
        if (typeof oldest !== 'string') break;
        this.buffers.delete(oldest);
      }
    }
    const mediaMs = Math.round(buffer.duration * 1000);
    this.send('READY', {
      generation: payload.generation,
      buffered_duration_ms: mediaMs,
      media_duration_ms: mediaMs,
    });
  }

  private scheduleTransition(payload: TransitionAtPayload): void {
    const buffer = this.buffers.get(payload.song_id);
    const { context } = this.options;
    if (!buffer || context.state !== 'running') {
      this.send('NOT_READY', {
        generation: payload.generation,
        reason: buffer ? 'AUDIO_SUSPENDED' : 'BUFFER_LOST',
      });
      return;
    }
    if (this.nextSource) {
      try { this.nextSource.stop(); } catch { /* already stopped */ }
      this.nextSource.disconnect();
      this.nextSource = null;
    }
    if (this.transitionTimer) clearTimeout(this.transitionTimer);
    const schedule = compensateSchedule(
      payload.target_server_time_ms,
      payload.start_position_ms,
      payload.playback_rate || 1,
      Math.round(buffer.duration * 1000),
      this.offset(),
    );
    if (schedule.ended) {
      this.update({ phase: 'ENDED', generation: payload.generation, songId: payload.song_id });
      return;
    }
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(this.gain);
    source.start(context.currentTime + schedule.delayMs / 1000, schedule.positionMs / 1000);
    this.nextSource = source;
    this.transitionTimer = setTimeout(() => {
      this.transitionTimer = null;
      if (this.source) {
        this.source.onended = null;
        this.source.disconnect();
      }
      this.source = source;
      this.nextSource = null;
      this.buffer = buffer;
      this.anchorContextTime = context.currentTime;
      this.anchorPositionMs = schedule.positionMs;
      this.rate = payload.playback_rate || 1;
      const mediaMs = Math.round(buffer.duration * 1000);
      this.update({
        phase: 'PLAYING',
        generation: payload.generation,
        songId: payload.song_id,
        targetServerMs: payload.target_server_time_ms,
        bufferedMs: mediaMs,
        mediaMs,
      });
      this.pendingGeneration = null;
      this.pendingSongId = null;
      source.onended = () => {
        if (this.source === source && this.snapshot.phase === 'PLAYING') this.update({ phase: 'ENDED' });
      };
      this.startStatusReports();
    }, schedule.delayMs);
  }

  private schedulePlay(payload: PlayAtPayload): void {
    if (!this.buffer) {
      this.update({ error: { code: 'NOT_BUFFERED', message: 'Playback was scheduled before the song finished buffering' } });
      return;
    }
    const { context } = this.options;
    if (context.state !== 'running') {
      void context.resume().then(() => {
        if (context.state === 'running') this.schedulePlay(payload);
        else this.send('NOT_READY', { generation: payload.generation, reason: 'AUDIO_SUSPENDED' });
      }).catch(() => this.send('NOT_READY', { generation: payload.generation, reason: 'AUDIO_ERROR' }));
      return;
    }
    this.stopSource();
    const source = context.createBufferSource();
    source.buffer = this.buffer;
    source.connect(this.gain);
    this.rate = payload.playback_rate || 1;
    source.playbackRate.value = this.rate;

    const schedule = compensateSchedule(
      payload.target_server_time_ms,
      payload.start_position_ms,
      payload.playback_rate || 1,
      Math.round(this.buffer.duration * 1000),
      this.offset(),
    );
    if (schedule.ended) {
      this.update({ phase: 'ENDED', generation: payload.generation });
      return;
    }
    const when = context.currentTime + schedule.delayMs / 1000;
    this.anchorContextTime = when;
    this.anchorPositionMs = schedule.positionMs;
    source.onended = () => {
      if (this.source === source && this.snapshot.phase === 'PLAYING') {
        if (this.status) clearInterval(this.status);
        this.update({ phase: 'ENDED' });
      }
    };
    source.start(when, schedule.positionMs / 1000);
    this.source = source;
    this.update({ phase: 'SCHEDULED', targetServerMs: payload.target_server_time_ms, generation: payload.generation });

    this.later(() => {
      const errorMs = Math.round(schedule.latenessMs);
      this.pendingStartErrorMs = errorMs;
      this.update({ phase: 'PLAYING', startErrorMs: errorMs });
      this.startStatusReports();
    }, schedule.delayMs);
  }

  private schedulePause(payload: PauseAtPayload): void {
    if (this.nextSource) {
      try { this.nextSource.stop(); } catch { /* already stopped */ }
      this.nextSource.disconnect();
      this.nextSource = null;
    }
    if (this.transitionTimer) clearTimeout(this.transitionTimer);
    this.transitionTimer = null;
    const delayMs = Math.max(0, delayUntil(payload.target_server_time_ms, this.offset()));
    if (this.source) {
      try {
        this.source.stop(this.options.context.currentTime + delayMs / 1000);
      } catch {
        // already stopped
      }
    }
    this.update({ phase: 'PAUSE_SCHEDULED', targetServerMs: payload.target_server_time_ms });
    this.later(() => {
      if (this.status) clearInterval(this.status);
      this.anchorPositionMs = payload.position_ms;
      this.anchorContextTime = 0;
      this.update({ phase: 'PAUSED' });
    }, delayMs);
  }

  private correct(payload: CorrectionPayload): void {
    this.update({
      lastCorrection: { method: payload.method, driftMs: payload.drift_ms, rate: payload.playback_rate },
      lastDriftMs: payload.drift_ms,
      driftHistory: [...this.snapshot.driftHistory, payload.drift_ms].slice(-24),
    });
    if (payload.method === 'SEEK') {
      this.schedulePlay({
        generation: payload.generation,
        target_server_time_ms: payload.apply_at_server_time_ms,
        start_position_ms: payload.target_position_ms,
        playback_rate: 1,
      });
      return;
    }
    this.later(() => {
      this.reanchor(payload.playback_rate);
      if (payload.duration_ms) this.later(() => this.reanchor(1), payload.duration_ms);
    }, delayUntil(payload.apply_at_server_time_ms, this.offset()));
  }

  private reanchor(rate: number): void {
    const { context } = this.options;
    this.anchorPositionMs = this.positionMs();
    this.anchorContextTime = context.currentTime;
    this.rate = rate;
    this.source?.playbackRate.setValueAtTime(rate, context.currentTime);
  }

  private startStatusReports(): void {
    if (this.status) clearInterval(this.status);
    this.reportStatus();
    this.status = setInterval(() => this.reportStatus(), config.syncStatusIntervalMs);
  }

  private reportStatus(): void {
    if (this.snapshot.phase !== 'PLAYING') return;
    // Refresh the four-timestamp clock estimate while playback is active. This
    // catches mobile clock changes and foreground resumes faster than the idle heartbeat.
    this.ping();
    this.send('PLAYBACK_STATUS', {
      generation: this.snapshot.generation,
      measured_server_time_ms: Math.round(Date.now() + this.offset()),
      position_ms: Math.round(this.positionMs()),
      buffering: false,
      clock_offset_ms: this.snapshot.offsetMs ?? undefined,
      round_trip_delay_ms: this.snapshot.rttMs ?? undefined,
      start_error_ms: this.pendingStartErrorMs ?? undefined,
    });
    this.pendingStartErrorMs = null;
  }
}
