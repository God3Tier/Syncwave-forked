import { useEffect, useState } from 'react';
import { listPlaylists } from '../api/playlist';
import type { PlaylistSummary } from '../api/types';
import { userId } from '../identity';

// The current user's playlists, shared by every "Add to playlist" menu.
let current: PlaylistSummary[] | null = null;
let pending: Promise<void> | null = null;
const listeners = new Set<(value: PlaylistSummary[]) => void>();

export function refreshPlaylists(): Promise<void> {
  pending = listPlaylists(userId)
    .then((page) => {
      current = page.items;
      listeners.forEach((notify) => notify(page.items));
    })
    .catch(() => undefined)
    .finally(() => {
      pending = null;
    });
  return pending;
}

export function usePlaylists(): PlaylistSummary[] | null {
  const [value, setValue] = useState(current);
  useEffect(() => {
    listeners.add(setValue);
    if (!current && !pending) void refreshPlaylists();
    return () => {
      listeners.delete(setValue);
    };
  }, []);
  return value;
}
