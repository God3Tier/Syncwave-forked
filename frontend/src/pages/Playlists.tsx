import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { createPlaylist, deletePlaylist, getPlaylist, renamePlaylist } from '../api/playlist';
import type { PlaylistSummary } from '../api/types';
import { Page } from '../components/Layout';
import { Button, Icon, IconButton, Notice, SongArt, Spinner } from '../components/ui';
import { errorMessage } from '../errors';
import { relativeTime } from '../format';
import { useAsync } from '../hooks/useAsync';
import { refreshPlaylists, usePlaylists } from '../hooks/usePlaylists';
import { userId } from '../identity';

export function Mosaic({ songIds }: { songIds: string[] }) {
  const tiles = songIds.slice(0, 4);
  return (
    <div className="grid aspect-square w-full grid-cols-2 gap-1 overflow-hidden rounded-2xl bg-surface-container">
      {[0, 1, 2, 3].map((i) =>
        tiles[i] ? (
          <SongArt key={i} id={tiles[i]} size="lg" className="rounded-none shadow-none" />
        ) : (
          <div key={i} className="aspect-square bg-surface-container-high" />
        ),
      )}
    </div>
  );
}

function PlaylistCard({ playlist }: { playlist: PlaylistSummary }) {
  // Summaries carry no songs; fetch the first few for the mosaic.
  const detail = useAsync((signal) => getPlaylist(playlist.playlist_id, signal), [playlist.playlist_id, playlist.updated_at]);
  const [menu, setMenu] = useState(false);

  const rename = async () => {
    const name = window.prompt('Rename playlist', playlist.name)?.trim();
    setMenu(false);
    if (name && name !== playlist.name) {
      await renamePlaylist(playlist.playlist_id, name.slice(0, 100));
      void refreshPlaylists();
    }
  };
  const remove = async () => {
    setMenu(false);
    if (window.confirm(`Delete “${playlist.name}”?`)) {
      await deletePlaylist(playlist.playlist_id);
      void refreshPlaylists();
    }
  };

  return (
    <article className="group relative">
      <Link to={`/playlists/${playlist.playlist_id}`} className="block">
        <Mosaic songIds={detail.data?.songs.map((s) => s.song_id) ?? []} />
        <p className="mt-3 truncate text-sm font-extrabold">{playlist.name}</p>
        <p className="mt-1 text-xs text-on-surface-variant">
          {playlist.song_count ? `${playlist.song_count} song${playlist.song_count === 1 ? '' : 's'}` : 'No songs yet'} · updated {relativeTime(playlist.updated_at)}
        </p>
      </Link>
      <div className="absolute right-4 top-4">
        <IconButton icon="more_vert" label="Playlist options" onClick={() => setMenu((v) => !v)} className="bg-surface-container-low/90" />
        {menu && (
          <div className="absolute right-0 z-20 mt-1 w-36 rounded-xl bg-surface-container-high py-1 shadow-[0_14px_38px_rgb(0_0_0/0.35)] ring-1 ring-outline-variant/55" role="menu">
            <button type="button" role="menuitem" onClick={() => void rename()} className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-surface-container-highest">
              <Icon name="edit" className="text-base" /> Rename
            </button>
            <button type="button" role="menuitem" onClick={() => void remove()} className="flex w-full items-center gap-2 px-3 py-2 text-sm text-error hover:bg-surface-container-highest">
              <Icon name="delete" className="text-base" /> Delete
            </button>
          </div>
        )}
      </div>
    </article>
  );
}

export function Playlists() {
  const playlists = usePlaylists();
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [error, setError] = useState<unknown>();

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await createPlaylist(userId, name.trim());
      setName('');
      setCreating(false);
      await refreshPlaylists();
    } catch (cause) {
      setError(cause);
    }
  };

  return (
    <Page wide>
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4 border-b border-outline-variant/35 pb-7">
        <div>
          <h1 className="text-3xl font-extrabold tracking-[-0.035em]">Your library</h1>
          <p className="mt-2 text-sm text-on-surface-variant">Build the set, change the order, then take it into a Jam.</p>
        </div>
        <Button variant="primary" icon="add" onClick={() => setCreating(true)}>New playlist</Button>
      </header>
      {creating && (
        <form onSubmit={(event) => void create(event)} className="mb-8 flex max-w-xl flex-wrap gap-2 rounded-2xl bg-surface-container-low p-4 ring-1 ring-outline-variant/45">
          <input
            autoFocus
            required
            maxLength={100}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Playlist name"
            aria-label="Playlist name"
            className="min-w-0 flex-1 rounded-xl bg-surface-container px-3 py-2 text-sm ring-1 ring-outline-variant/45 focus:ring-secondary focus:outline-none"
          />
          <Button type="submit" variant="primary">
            Create
          </Button>
          <Button variant="ghost" onClick={() => setCreating(false)}>
            Cancel
          </Button>
        </form>
      )}
      {error !== undefined && <Notice tone="error">{errorMessage(error)}</Notice>}
      {playlists === null && <Spinner label="Loading playlists" />}
      {playlists?.length === 0 && <p className="py-8 text-on-surface-variant">No playlists yet. Create one, or add songs from Discover or Search.</p>}
      <div className="grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        {playlists?.map((playlist) => <PlaylistCard key={playlist.playlist_id} playlist={playlist} />)}
      </div>
    </Page>
  );
}
