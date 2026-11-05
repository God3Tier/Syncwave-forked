import { useEffect, useState } from 'react';
import { getSong } from '../api/catalogue';
import type { Song } from '../api/types';

// Playlists and Jam queues hold song IDs only, so titles and artists are
// looked up in the Catalogue. Results are shared across the whole app.
const cache = new Map<string, Song | null>();
const inflight = new Map<string, Promise<Song | null>>();
const listeners = new Set<() => void>();

function fetchSong(id: string): Promise<Song | null> {
  let pending = inflight.get(id);
  if (!pending) {
    pending = getSong(id)
      .then((song) => song as Song | null)
      .catch(() => null)
      .then((song) => {
        cache.set(id, song);
        inflight.delete(id);
        listeners.forEach((notify) => notify());
        return song;
      });
    inflight.set(id, pending);
  }
  return pending;
}

export function rememberSong(song: Song): void {
  cache.set(song.song_id, song);
}

/** Map of song_id → Song (null if the Catalogue does not know it, undefined while loading). */
export function useSongs(ids: readonly string[]): Map<string, Song | null> {
  const [, setVersion] = useState(0);
  const key = ids.join(',');

  useEffect(() => {
    const notify = () => setVersion((value) => value + 1);
    listeners.add(notify);
    for (const id of ids) if (!cache.has(id)) void fetchSong(id);
    return () => {
      listeners.delete(notify);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  const result = new Map<string, Song | null>();
  for (const id of ids) if (cache.has(id)) result.set(id, cache.get(id) ?? null);
  return result;
}

export function useSong(id: string | null | undefined): Song | null | undefined {
  const map = useSongs(id ? [id] : []);
  return id ? map.get(id) : undefined;
}
