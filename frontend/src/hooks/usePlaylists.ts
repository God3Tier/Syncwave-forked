import { useEffect, useState } from 'react';
import { listPlaylists } from '../api/playlist';
import type { PlaylistSummary } from '../api/types';

// The current user's playlists, shared by every "Add to playlist" menu.
let current: PlaylistSummary[] | null = null;
let currentOwner: string | null = null;
let pending: Promise<void> | null = null;
const listeners = new Set<(value: PlaylistSummary[]) => void>();

export function refreshPlaylists(ownerId: string | null): Promise<void> {
  if (!ownerId) {
    currentOwner = null;
    current = [];
    listeners.forEach((notify) => notify([]));
    return Promise.resolve();
  }
  currentOwner = ownerId;
  pending = listPlaylists()
    .then((page) => {
      if (currentOwner !== ownerId) return;
      current = page.items;
      listeners.forEach((notify) => notify(page.items));
    })
    .catch(() => undefined)
    .finally(() => {
      pending = null;
    });
  return pending;
}

export function usePlaylists(ownerId: string | null): PlaylistSummary[] | null {
  const [value, setValue] = useState(ownerId && ownerId === currentOwner ? current : ownerId ? null : []);
  useEffect(() => {
    listeners.add(setValue);
    if (ownerId && (ownerId !== currentOwner || (!current && !pending))) void refreshPlaylists(ownerId);
    return () => {
      listeners.delete(setValue);
    };
  }, [ownerId]);
  return ownerId === null ? [] : ownerId === currentOwner ? value : null;
}
