import { useEffect, useRef, useState } from 'react';
import { addSong, createPlaylist } from '../api/playlist';
import { ApiError } from '../api/http';
import { refreshPlaylists, usePlaylists } from '../hooks/usePlaylists';
import { userId } from '../identity';
import { Icon, IconButton } from './ui';

/** "+" button with the playlist dropdown from the Stitch "Search results" screen. */
export function AddToPlaylist({ songId }: { songId: string }) {
  const [open, setOpen] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const playlists = usePlaylists();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(null), 2500);
    return () => clearTimeout(timer);
  }, [message]);

  const add = async (playlistId: string, name: string) => {
    setOpen(false);
    try {
      await addSong(playlistId, songId);
      setMessage(`Added to ${name}`);
      void refreshPlaylists();
    } catch (error) {
      setMessage(error instanceof ApiError && error.status === 409 ? `Already in ${name}` : 'Could not add the song');
    }
  };

  const createAndAdd = async () => {
    const name = window.prompt('Playlist name')?.trim();
    if (!name) return;
    try {
      const playlist = await createPlaylist(userId, name.slice(0, 100));
      await add(playlist.playlist_id, playlist.name);
    } catch {
      setMessage('Could not create the playlist');
    }
  };

  return (
    <div ref={ref} className="relative">
      <IconButton icon="playlist_add" label="Add to playlist" onClick={() => setOpen((value) => !value)} aria-expanded={open} />
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-56 overflow-hidden rounded-xl border border-outline-variant/40 bg-surface-container-high py-1 shadow-2xl shadow-black/60" role="menu">
          {playlists === null && <p className="px-3 py-2 font-mono text-xs text-outline">Loading…</p>}
          {playlists?.length === 0 && <p className="px-3 py-2 text-xs text-on-surface-variant">No playlists yet</p>}
          {playlists?.map((playlist) => (
            <button
              key={playlist.playlist_id}
              type="button"
              role="menuitem"
              onClick={() => void add(playlist.playlist_id, playlist.name)}
              className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-surface-container-highest"
            >
              <span className="truncate">{playlist.name}</span>
              <span className="font-mono text-[10px] text-outline">{playlist.song_count}</span>
            </button>
          ))}
          <div className="my-1 border-t border-outline-variant/30" />
          <button type="button" role="menuitem" onClick={() => void createAndAdd()} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-primary hover:bg-surface-container-highest">
            <Icon name="add" className="text-base" /> New playlist
          </button>
        </div>
      )}
      {message && (
        <div role="status" className="absolute right-0 top-full z-30 mt-1 whitespace-nowrap rounded-lg border border-outline-variant/40 bg-surface-container-highest px-3 py-1.5 font-mono text-[11px] shadow-lg">
          {message}
        </div>
      )}
    </div>
  );
}
