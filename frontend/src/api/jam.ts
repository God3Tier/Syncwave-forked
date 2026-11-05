import { uuid } from '../uuid';
import { getSignedInAccount } from '../auth/session';
import { request } from './http';
import type { Jam, Readiness } from './types';

const BASE = '/api/jam/jams';
const MEMBERS_KEY = 'syncwave.jam_members';
interface Membership { member_id: string; token: string | null }

function loadMemberships(): Record<string, Membership> {
  try {
    return JSON.parse(sessionStorage.getItem(MEMBERS_KEY) ?? '{}') as Record<string, Membership>;
  } catch {
    return {};
  }
}

function remember(jam: Jam): Jam {
  if (jam.member_id) {
    try {
      sessionStorage.setItem(MEMBERS_KEY, JSON.stringify({
        ...loadMemberships(),
        [jam.jam_id]: { member_id: jam.member_id, token: jam.member_token },
      }));
    } catch {
      // The current room remains active for this page load if storage is blocked.
    }
  }
  return jam;
}

export function jamMemberId(jamId: string, accountId?: string): string | null {
  return accountId ?? loadMemberships()[jamId]?.member_id ?? null;
}

function call<T>(jamId: string | null, path: string, options: Parameters<typeof request>[1] = {}): Promise<T> {
  const memberToken = jamId && !getSignedInAccount() ? loadMemberships()[jamId]?.token : null;
  return request<T>(`${BASE}${path}`, {
    ...options,
    headers: { ...(memberToken ? { 'X-Jam-Token': memberToken } : {}), ...options.headers },
  });
}

const id = (jamId: string) => `/${encodeURIComponent(jamId)}`;

export async function createJam(playlistId?: string | null): Promise<Jam> {
  return remember(await call<Jam>(null, '', { method: 'POST', json: { playlist_id: playlistId || undefined } }));
}

export function getJam(jamId: string, signal?: AbortSignal): Promise<Jam> {
  return call(jamId, id(jamId), { signal });
}

export async function joinJam(jamId: string): Promise<Jam> {
  return remember(await call<Jam>(jamId, `${id(jamId)}/members`, { method: 'POST' }));
}

export function leaveJam(jamId: string, participantId: string): Promise<void> {
  return call(jamId, `${id(jamId)}/members/${encodeURIComponent(participantId)}`, { method: 'DELETE' });
}

export function transferOwnership(jamId: string, participantId: string): Promise<Jam> {
  return call(jamId, `${id(jamId)}/owner`, { method: 'PUT', json: { participant_id: participantId } });
}

export function transferAndLeave(jamId: string, participantId: string): Promise<Jam> {
  return call(jamId, `${id(jamId)}/owner/transfer-and-leave`, { method: 'POST', json: { participant_id: participantId } });
}

export function endJam(jamId: string): Promise<Jam> {
  return call(jamId, `${id(jamId)}/end`, { method: 'POST' });
}

export function queueSong(jamId: string, songId: string): Promise<Jam> {
  return call(jamId, `${id(jamId)}/queue`, { method: 'POST', json: { song_id: songId } });
}

export function removeQueueItem(jamId: string, queueItemId: string): Promise<Jam> {
  return call(jamId, `${id(jamId)}/queue/${encodeURIComponent(queueItemId)}`, { method: 'DELETE' });
}

export function reorderQueue(jamId: string, queueItemIds: string[]): Promise<Jam> {
  return call(jamId, `${id(jamId)}/queue`, { method: 'PUT', json: { queue_item_ids: queueItemIds } });
}

type Control = 'start' | 'pause' | 'resume' | 'skip' | 'seek';

/** Owner playback controls. Each carries a fresh request_id so Jam/Sync can de-duplicate retries. */
export function playback(
  jamId: string,
  action: Control,
  extra: { queue_item_id?: string; position_ms?: number } = {},
): Promise<Jam> {
  return call(jamId, `${id(jamId)}/playback/${action}`, {
    method: 'POST',
    json: { request_id: uuid(), ...extra },
  });
}

export function getReadiness(jamId: string, signal?: AbortSignal): Promise<Readiness> {
  return call(jamId, `${id(jamId)}/playback/readiness`, { signal });
}

export function decideReadiness(jamId: string, decision: 'CONTINUE' | 'WAIT' | 'CANCEL'): Promise<Jam> {
  return call(jamId, `${id(jamId)}/playback/readiness-decision`, {
    method: 'POST',
    json: { request_id: uuid(), decision },
  });
}

export function jamSocketUrl(jamId: string, participantId: string): string {
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  const params = new URLSearchParams({ participant_id: participantId });
  const memberToken = getSignedInAccount() ? null : loadMemberships()[jamId]?.token;
  if (memberToken) params.set('token', memberToken);
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

export function removeRecentJam(jamId: string): void {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(recentJams().filter((jam) => jam.jam_id !== jamId)));
  } catch {
    // ignore
  }
}

export function clearRecentJams(): void {
  try {
    localStorage.removeItem(RECENT_KEY);
  } catch {
    // ignore
  }
}
