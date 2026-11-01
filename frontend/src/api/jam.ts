import { uuid } from '../uuid';
import { config } from '../config';
import { request } from './http';
import type { Jam, Readiness } from './types';

const BASE = '/api/jam/jams';
const TOKENS_KEY = 'syncwave.jam_tokens';

// Jam returns a member_token on create/join; it is remembered per Jam and
// falls back to the configured mock token.
function loadTokens(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(TOKENS_KEY) ?? '{}') as Record<string, string>;
  } catch {
    return {};
  }
}

function remember(jam: Jam): Jam {
  if (jam.member_token) {
    try {
      localStorage.setItem(TOKENS_KEY, JSON.stringify({ ...loadTokens(), [jam.jam_id]: jam.member_token }));
    } catch {
      // storage unavailable: the default token still works locally
    }
  }
  return jam;
}

export function jamToken(jamId: string): string {
  return loadTokens()[jamId] ?? config.jamToken;
}

function call<T>(jamId: string | null, path: string, options: Parameters<typeof request>[1] = {}): Promise<T> {
  return request<T>(`${BASE}${path}`, {
    ...options,
    headers: { 'X-Jam-Token': jamId ? jamToken(jamId) : config.jamToken, ...options.headers },
  });
}

const id = (jamId: string) => `/${encodeURIComponent(jamId)}`;

export async function createJam(ownerId: string, playlistId?: string | null): Promise<Jam> {
  return remember(await call<Jam>(null, '', { method: 'POST', json: { owner_id: ownerId, playlist_id: playlistId || undefined } }));
}

export function getJam(jamId: string, signal?: AbortSignal): Promise<Jam> {
  return call(jamId, id(jamId), { signal });
}

export async function joinJam(jamId: string, participantId: string): Promise<Jam> {
  return remember(await call<Jam>(jamId, `${id(jamId)}/members`, { method: 'POST', json: { participant_id: participantId } }));
}

export function leaveJam(jamId: string, participantId: string): Promise<void> {
  return call(jamId, `${id(jamId)}/members/${encodeURIComponent(participantId)}`, { method: 'DELETE' });
}

export function queueSong(jamId: string, actorId: string, songId: string): Promise<Jam> {
  return call(jamId, `${id(jamId)}/queue`, { method: 'POST', json: { actor_id: actorId, song_id: songId } });
}

export function removeQueueItem(jamId: string, actorId: string, queueItemId: string): Promise<Jam> {
  return call(jamId, `${id(jamId)}/queue/${encodeURIComponent(queueItemId)}`, { method: 'DELETE', json: { actor_id: actorId } });
}

export function reorderQueue(jamId: string, actorId: string, queueItemIds: string[]): Promise<Jam> {
  return call(jamId, `${id(jamId)}/queue`, { method: 'PUT', json: { actor_id: actorId, queue_item_ids: queueItemIds } });
}

type Control = 'start' | 'pause' | 'resume' | 'skip' | 'seek';

/** Owner playback controls. Each carries a fresh request_id so Jam/Sync can de-duplicate retries. */
export function playback(
  jamId: string,
  actorId: string,
  action: Control,
  extra: { queue_item_id?: string; position_ms?: number } = {},
): Promise<Jam> {
  return call(jamId, `${id(jamId)}/playback/${action}`, {
    method: 'POST',
    json: { actor_id: actorId, request_id: uuid(), ...extra },
  });
}

export function getReadiness(jamId: string, actorId: string, signal?: AbortSignal): Promise<Readiness> {
  return call(jamId, `${id(jamId)}/playback/readiness`, { query: { actor_id: actorId }, signal });
}

export function decideReadiness(jamId: string, actorId: string, decision: 'CONTINUE' | 'WAIT' | 'CANCEL'): Promise<Jam> {
  return call(jamId, `${id(jamId)}/playback/readiness-decision`, {
    method: 'POST',
    json: { actor_id: actorId, request_id: uuid(), decision },
  });
}

export function jamSocketUrl(jamId: string, participantId: string): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const params = new URLSearchParams({ participant_id: participantId, token: jamToken(jamId) });
  return `${scheme}://${window.location.host}${BASE}${id(jamId)}/ws?${params}`;
}

// Recently visited Jams, for the lobby's "Your recent Jams" list.
const RECENT_KEY = 'syncwave.recent_jams';
export interface RecentJam {
  jam_id: string;
  owner: boolean;
  visited_at: string;
}

export function recentJams(): RecentJam[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]') as RecentJam[];
  } catch {
    return [];
  }
}

export function rememberJam(jamId: string, owner: boolean): void {
  const next = [{ jam_id: jamId, owner, visited_at: new Date().toISOString() }, ...recentJams().filter((j) => j.jam_id !== jamId)].slice(0, 8);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // ignore
  }
}
