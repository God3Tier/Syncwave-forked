import { listSongs } from './catalogue';
import { ApiError, request } from './http';
import type { Page, SearchResult, Song } from './types';

export interface SearchOutcome extends Page<SearchResult> {
  /** True when the Search Service was unavailable and the catalogue was filtered instead. */
  fallback: boolean;
}

/** Case-insensitive title/artist match, used only by the catalogue fallback. */
export function matchesQuery(song: Pick<Song, 'title' | 'artist'>, query: string): boolean {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const haystack = `${song.title} ${song.artist}`.toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

const FALLBACK_SCAN_PAGES = 5;
// An undeployed service costs a few seconds at the gateway (DNS lookup, then
// 502), so after one failure go straight to the fallback for a while.
const RETRY_SEARCH_AFTER_MS = 60_000;
let searchDownUntil = 0;

async function catalogueFallback(query: string, signal?: AbortSignal): Promise<SearchOutcome> {
  const items: SearchResult[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < FALLBACK_SCAN_PAGES; page++) {
    const result: Page<Song> = await listSongs({ limit: 100, cursor, processing_status: 'READY' }, signal);
    for (const song of result.items) {
      if (matchesQuery(song, query)) items.push({ song_id: song.song_id, title: song.title, artist: song.artist });
    }
    cursor = result.next_cursor;
    if (!cursor) break;
  }
  return { items, next_cursor: null, fallback: true };
}

/**
 * Searches through the Search Service (GET /api/search/search). While that
 * service is not deployed (gateway 502/404) the browser filters READY
 * catalogue songs itself, so the page keeps working.
 */
export async function searchSongs(
  query: string,
  cursor: string | null = null,
  signal?: AbortSignal,
): Promise<SearchOutcome> {
  if (Date.now() < searchDownUntil) return catalogueFallback(query, signal);
  try {
    const page = await request<Page<SearchResult>>('/api/search/search', {
      query: { q: query, limit: 20, cursor },
      signal,
    });
    return { ...page, fallback: false };
  } catch (error) {
    if (error instanceof ApiError && (error.unavailable || error.status === 404)) {
      searchDownUntil = Date.now() + RETRY_SEARCH_AFTER_MS;
      return catalogueFallback(query, signal);
    }
    throw error;
  }
}
