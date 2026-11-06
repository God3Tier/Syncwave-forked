// Sync WebSocket frames (contracts/websocket/*.schema.json). Every frame is
// {type, jam_id, seq, sent_at_ms, payload}; the client's seq must strictly
// increase per connection.

export type ServerType =
  | 'JOINED'
  | 'TIME_PONG'
  | 'PREPARE'
  | 'PRELOAD'
  | 'PARTICIPANT_STATE'
  | 'PLAY_AT'
  | 'TRANSITION_AT'
  | 'RESUME_AT'
  | 'PAUSE_AT'
  | 'SEEK_TO'
  | 'SYNC_CORRECTION'
  | 'ERROR';

export type ClientType = 'TIME_PING' | 'READY' | 'NOT_READY' | 'PLAYBACK_STATUS';

export interface Frame<T extends string = string, P = Record<string, unknown>> {
  type: T;
  jam_id: string;
  seq: number;
  sent_at_ms: number;
  payload: P;
}

export interface PreparePayload {
  generation: number;
  queue_item_id: string;
  song_id: string;
  stream_url: string;
  manifest_url: string;
  start_position_ms: number;
}

export interface PlayAtPayload {
  generation: number;
  target_server_time_ms: number;
  start_position_ms: number;
  playback_rate?: number;
}

/** A committed next-track transition scheduled before the current source ends. */
export interface TransitionAtPayload extends PlayAtPayload {
  readonly queue_item_id: string;
  readonly song_id: string;
}

export interface PauseAtPayload {
  generation: number;
  target_server_time_ms: number;
  position_ms: number;
}

export interface SeekToPayload extends PauseAtPayload {
  resume_playback: boolean;
}

export interface CorrectionPayload {
  generation: number;
  method: 'RATE' | 'SEEK';
  drift_ms: number;
  target_position_ms: number;
  playback_rate: number;
  apply_at_server_time_ms: number;
  duration_ms: number | null;
}

export interface ParticipantStatePayload {
  participant_id: string;
  generation: number;
  connected: boolean;
  ready: boolean;
}

export function makeFrameFactory(jamId: string) {
  let seq = 0;
  return <P>(type: ClientType, payload: P): Frame<ClientType, P> => ({
    type,
    jam_id: jamId,
    seq: seq++,
    sent_at_ms: Date.now(),
    payload,
  });
}

/** Messages carrying an older playback generation must have no effect (plan.md §24.2.7). */
export function isStale(currentGeneration: number, payload: unknown): boolean {
  if (!payload || typeof payload !== 'object' || !('generation' in payload)) return false;
  const generation = (payload as { generation: unknown }).generation;
  return typeof generation === 'number' && generation < currentGeneration;
}
