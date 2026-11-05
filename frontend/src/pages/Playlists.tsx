import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { createPlaylist, deletePlaylist, getPlaylist, renamePlaylist } from '../api/playlist';
import type { PlaylistSummary } from '../api/types';
import { Page } from '../components/Layout';
import { Button, Icon, IconButton, Notice, SongArt, Spinner } from '../components/ui';
import { errorMessage } from '../errors';
import { relativeTime } from '../format';
import { useAsync } from '../hooks/useAsync';
import { refreshPlaylists, usePlaylists } from '../hooks/usePlaylists';
import { useAuth } from '../auth/AuthProvider';

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

function PlaylistCard({ playlist, ownerId }: { playlist: PlaylistSummary; ownerId: string }) {
  // Summaries carry no songs; fetch the first few for the mosaic.
  const detail = useAsync((signal) => getPlaylist(playlist.playlist_id, signal), [playlist.playlist_id, playlist.updated_at]);
  const [menu, setMenu] = useState(false);

  const rename = async () => {
    const name = window.prompt('Rename playlist', playlist.name)?.trim();
    setMenu(false);
    if (name && name !== playlist.name) {
      await renamePlaylist(playlist.playlist_id, name.slice(0, 100));
      void refreshPlaylists(ownerId);
    }
  };
  const remove = async () => {
    setMenu(false);
    if (window.confirm(`Delete “${playlist.name}”?`)) {
      await deletePlaylist(playlist.playlist_id);
      void refreshPlaylists(ownerId);
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
  const { account, loading: authLoading } = useAuth();
  const playlists = usePlaylists(account?.id ?? null);
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const createIntentHandled = useRef(false);
  const [creating, setCreating] = useState(false);
  const createIntent = account && searchParams.get('intent') === 'create-playlist';
  const [name, setName] = useState('');
  const [error, setError] = useState<unknown>();

  useEffect(() => {
    if (account && searchParams.get('intent') === 'create-playlist' && !createIntentHandled.current) {
      createIntentHandled.current = true;
      navigate('/playlists', { replace: true });
    }
  }, [account, navigate, searchParams]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setError(undefined);
    try {
      await createPlaylist(name.trim());
      setName('');
      setCreating(false);
      await refreshPlaylists(account?.id ?? null);
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
        <Button variant="primary" icon="add" onClick={() => account ? setCreating(true) : navigate('/signup?returnTo=%2Fplaylists%3Fintent%3Dcreate-playlist')}>New playlist</Button>
      </header>
      {!account && !authLoading && (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-l-2 border-primary bg-surface-container-low px-4 py-3">
          <p className="text-sm text-on-surface-variant">Sign in to build a library. You can still listen to any playlist shared with you.</p>
          <Link to="/signup?returnTo=%2Fplaylists%3Fintent%3Dcreate-playlist" className="shrink-0 text-sm font-bold text-primary underline-offset-4 hover:underline">Create an account</Link>
        </div>
      )}
      {(creating || createIntent) && (
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
      {authLoading && <Spinner label="Checking account" />}
      {account && playlists === null && <Spinner label="Loading playlists" />}
      {account && playlists?.length === 0 && <p className="py-8 text-on-surface-variant">No playlists yet. Create one, or add songs from Discover or Search.</p>}
      <div className="grid grid-cols-2 gap-x-4 gap-y-8 sm:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
        {account && playlists?.map((playlist) => <PlaylistCard key={playlist.playlist_id} playlist={playlist} ownerId={account.id} />)}
      </div>
    </Page>
  );
}
