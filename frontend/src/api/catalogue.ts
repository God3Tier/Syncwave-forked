import { request } from './http';
import type { Page, ProcessingStatus, Song } from './types';

const BASE = '/api/catalogue';

export function listSongs(
  params: { limit?: number; cursor?: string | null; processing_status?: ProcessingStatus } = {},
  signal?: AbortSignal,
): Promise<Page<Song>> {
  return request(`${BASE}/songs`, { query: { limit: params.limit ?? 20, ...params }, signal });
}

export function getSong(songId: string, signal?: AbortSignal): Promise<Song> {
  return request(`${BASE}/songs/${encodeURIComponent(songId)}`, { signal });
}
