import { useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import { createPlaylist, deletePlaylist, getPlaylist, renamePlaylist } from '../api/playlist';
import type { PlaylistSummary } from '../api/types';
import { Page } from '../components/Layout';
import { Button, Icon, IconButton, Notice, SectionTitle, SongArt, Spinner } from '../components/ui';
import { errorMessage } from '../errors';
import { relativeTime } from '../format';
import { useAsync } from '../hooks/useAsync';
import { refreshPlaylists, usePlaylists } from '../hooks/usePlaylists';
import { userId } from '../identity';

export function Mosaic({ songIds }: { songIds: string[] }) {
  const tiles = songIds.slice(0, 4);
  return (
    <div className="grid aspect-square w-full grid-cols-2 gap-1.5 rounded-xl border border-outline-variant/30 bg-surface-container p-1.5">
      {[0, 1, 2, 3].map((i) =>
        tiles[i] ? (
          <SongArt key={i} id={tiles[i]} size="lg" className="rounded-lg" />
        ) : (
          <div key={i} className="aspect-square rounded-lg border border-dashed border-outline-variant/40" />
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
    <div className="group relative rounded-xl border border-outline-variant/30 bg-surface-container-low p-3 transition-colors hover:border-primary/40">
      <Link to={`/playlists/${playlist.playlist_id}`} className="block">
        <Mosaic songIds={detail.data?.songs.map((s) => s.song_id) ?? []} />
        <p className="mt-3 truncate font-headline font-semibold">{playlist.name}</p>
        <p className="font-mono text-[11px] text-on-surface-variant">
          {playlist.song_count ? `${playlist.song_count} song${playlist.song_count === 1 ? '' : 's'}` : 'No songs yet'} · updated {relativeTime(playlist.updated_at)}
        </p>
      </Link>
      <div className="absolute right-4 top-4">
        <IconButton icon="more_vert" label="Playlist options" onClick={() => setMenu((v) => !v)} className="bg-surface-container-high/80 backdrop-blur" />
        {menu && (
          <div className="absolute right-0 z-20 mt-1 w-36 rounded-xl border border-outline-variant/40 bg-surface-container-high py-1 shadow-xl" role="menu">
            <button type="button" role="menuitem" onClick={() => void rename()} className="flex w-full items-center gap-2 px-3 py-2 text-sm hover:bg-surface-container-highest">
              <Icon name="edit" className="text-base" /> Rename
            </button>
            <button type="button" role="menuitem" onClick={() => void remove()} className="flex w-full items-center gap-2 px-3 py-2 text-sm text-error hover:bg-surface-container-highest">
              <Icon name="delete" className="text-base" /> Delete
            </button>
          </div>
        )}
      </div>
    </div>
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
      <SectionTitle
        aside={
          <Button variant="primary" icon="add" onClick={() => setCreating(true)}>
            New playlist
          </Button>
        }
      >
        Your playlists
      </SectionTitle>
      {creating && (
        <form onSubmit={(event) => void create(event)} className="mb-6 flex max-w-xl flex-wrap gap-2">
          <input
            autoFocus
            required
            maxLength={100}
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Playlist name"
            aria-label="Playlist name"
            className="min-w-0 flex-1 rounded-lg border border-outline-variant/40 bg-surface-container px-3 py-2 text-sm focus:border-primary focus:outline-none"
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
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        {playlists?.map((playlist) => <PlaylistCard key={playlist.playlist_id} playlist={playlist} />)}
      </div>
    </Page>
  );
}
