import { request } from './http';
import type { Page, ProcessingStatus, Song } from './types';

const BASE = '/api/catalogue';

export function listSongs(
  params: { limit?: number; cursor?: string | null; processing_status?: ProcessingStatus; uploader_id?: string; sort?: 'newest' | 'top' } = {},
  signal?: AbortSignal,
): Promise<Page<Song>> {
  return request(`${BASE}/songs`, { query: { limit: params.limit ?? 20, ...params }, signal });
}

/** Record one real playback start using an idempotency key. */
export function recordPlay(songId: string, playbackId: string, source: 'SOLO' | 'JAM'): Promise<void> {
  return request(`${BASE}/songs/${encodeURIComponent(songId)}/plays`, {
    method: 'POST',
    json: { playback_id: playbackId, source },
  }).then(() => undefined);
}

export function getSong(songId: string, signal?: AbortSignal): Promise<Song> {
  return request(`${BASE}/songs/${encodeURIComponent(songId)}`, { signal });
}
