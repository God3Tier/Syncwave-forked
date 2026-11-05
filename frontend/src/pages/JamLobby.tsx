import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { createJam, recentJams, rememberJam } from '../api/jam';
import { useAuth } from '../auth/AuthProvider';
import { Page } from '../components/Layout';
import { Button, Icon, Notice, StatusChip } from '../components/ui';
import { errorMessage } from '../errors';
import { relativeTime, shortId } from '../format';
import { usePlaylists } from '../hooks/usePlaylists';

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

export function JamLobby() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const hostIntentHandled = useRef(false);
  const { account, loading: authLoading } = useAuth();
  const playlists = usePlaylists(account?.id ?? null);
  const [playlistId, setPlaylistId] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [joinError, setJoinError] = useState<string | null>(null);
  const recent = recentJams();

  const create = useCallback(async () => {
    if (!account) {
      navigate('/signup?returnTo=%2Fjam&intent=host');
      return;
    }
    setBusy(true);
    setError(undefined);
    try {
      const jam = await createJam(playlistId || null);
      rememberJam(jam.jam_id, true);
      navigate(`/jam/${jam.jam_id}`);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }, [account, navigate, playlistId]);

  useEffect(() => {
    if (account && !authLoading && searchParams.get('intent') === 'host' && !hostIntentHandled.current) {
      hostIntentHandled.current = true;
      void create();
    }
  }, [account, authLoading, create, searchParams]);

  const join = (event: FormEvent) => {
    event.preventDefault();
    const match = code.match(UUID);
    if (!match) {
      setJoinError('Paste a Jam link or its ID (a UUID).');
      return;
    }
    navigate(`/jam/${match[0].toLowerCase()}`);
  };

  return (
    <Page>
      <header className="mb-10 border-b border-outline-variant/35 pb-8">
        <div className="mb-5 flex -space-x-3" aria-hidden="true">
          {['bg-primary', 'bg-secondary', 'bg-tertiary', 'bg-on-surface'].map((color) => (
            <span key={color} className={`size-11 rounded-full border-[3px] border-background ${color}`} />
          ))}
        </div>
        <h1 className="max-w-3xl text-4xl font-extrabold tracking-[-0.04em] md:text-5xl">One queue. Every speaker. Same moment.</h1>
        <p className="mt-4 max-w-2xl text-base leading-7 text-on-surface-variant">Start a room for your friends or paste an invite to join theirs. SyncWave handles the timing once everyone enables audio.</p>
      </header>

      <div className="grid overflow-hidden rounded-2xl bg-surface-container-low ring-1 ring-outline-variant/45 md:grid-cols-2">
        <section className="flex flex-col p-6 md:p-8">
          <Icon name="sensors" className="mb-5 text-2xl text-primary" />
          <h2 className="text-xl font-extrabold">Start a Jam</h2>
          <p className="mt-2 text-sm leading-6 text-on-surface-variant">You own playback. Friends can join and add to the queue.</p>
          <label className="mt-4 block space-y-1.5">
            <span className="text-xs text-on-surface-variant">Seed the queue from a playlist (optional)</span>
            <select
              value={playlistId}
              disabled={!account}
              onChange={(event) => setPlaylistId(event.target.value)}
              className="min-h-11 w-full rounded-xl bg-surface-container px-3 py-2.5 text-sm ring-1 ring-outline-variant/45 focus:ring-secondary focus:outline-none"
            >
              <option value="">Empty queue</option>
              {playlists?.map((p) => (
                <option key={p.playlist_id} value={p.playlist_id}>
                  {p.name} · {p.song_count} songs
                </option>
              ))}
            </select>
          </label>
          <Button variant="primary" icon="add_circle" onClick={() => void create()} disabled={busy || authLoading} className="mt-5 py-3">
            {busy ? 'Creating…' : authLoading ? 'Checking account…' : account ? 'Create Jam' : 'Sign in to host a Jam'}
          </Button>
          <p className="mt-3 text-xs leading-5 text-on-surface-variant">As owner, only you can start, pause, seek, or skip.</p>
          {error !== undefined && (
            <div className="mt-4">
              <Notice tone="error">{errorMessage(error)}</Notice>
            </div>
          )}
        </section>

        <section className="flex flex-col border-t border-outline-variant/35 p-6 md:border-l md:border-t-0 md:p-8">
          <Icon name="group_add" className="mb-5 text-2xl text-secondary" />
          <h2 className="text-xl font-extrabold">Join a Jam</h2>
          <p className="mt-2 text-sm leading-6 text-on-surface-variant">Use the link your friend sent. Join as a guest and add songs to the queue.</p>
          <form onSubmit={join} className="mt-4 flex gap-2">
            <input
              value={code}
              onChange={(event) => {
                setCode(event.target.value);
                setJoinError(null);
              }}
              placeholder="Paste a Jam link or ID"
              aria-label="Jam link or ID"
              className="min-h-11 min-w-0 flex-1 rounded-xl bg-surface-container px-3 py-2.5 text-sm ring-1 ring-outline-variant/45 focus:ring-secondary focus:outline-none"
            />
            <Button type="submit" variant="cyan">
              Join
            </Button>
          </form>
          {joinError && <p className="mt-2 text-xs text-error">{joinError}</p>}
          <p className="mt-auto pt-6 text-xs text-on-surface-variant">
            You can join an invite without creating an account.
          </p>
        </section>
      </div>

      {recent.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-3 text-lg font-extrabold">Recent Jams</h2>
          <ul className="divide-y divide-outline-variant/25 border-y border-outline-variant/35">
            {recent.map((jam) => (
              <li key={jam.jam_id} className="flex items-center gap-4 px-4 py-3">
                <span className="font-mono text-sm">jam · {shortId(jam.jam_id)}</span>
                <StatusChip status={jam.owner ? 'OWNER' : 'MEMBER'} />
                <span className="ml-auto font-mono text-[11px] text-outline">{relativeTime(jam.visited_at)}</span>
                <Link to={`/jam/${jam.jam_id}`} className="font-headline text-sm font-semibold text-primary">
                  Rejoin
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </Page>
  );
}
