import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { createJam, recentJams, rememberJam } from '../api/jam';
import { Page } from '../components/Layout';
import { Button, Card, Icon, Notice, StatusChip } from '../components/ui';
import { errorMessage } from '../errors';
import { relativeTime, shortId } from '../format';
import { usePlaylists } from '../hooks/usePlaylists';
import { userId } from '../identity';

const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

export function JamLobby() {
  const navigate = useNavigate();
  const playlists = usePlaylists();
  const [playlistId, setPlaylistId] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [joinError, setJoinError] = useState<string | null>(null);
  const recent = recentJams();

  const create = async () => {
    setBusy(true);
    setError(undefined);
    try {
      const jam = await createJam(userId, playlistId || null);
      rememberJam(jam.jam_id, true);
      navigate(`/jam/${jam.jam_id}`);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  };

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
      <header className="mb-8">
        <h1 className="font-headline text-3xl font-bold tracking-tight md:text-5xl">
          Listen together, <span className="bg-gradient-to-r from-primary to-secondary bg-clip-text text-transparent">in sync</span>
        </h1>
        <p className="mt-3 max-w-2xl text-on-surface-variant">Play the same song at the same moment on every phone and laptop in the room.</p>
      </header>

      <div className="grid gap-6 md:grid-cols-2">
        <Card className="flex flex-col">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-primary/15">
            <Icon name="sensors" className="text-2xl text-primary" />
          </div>
          <h2 className="font-headline text-xl font-semibold">Start a Jam</h2>
          <label className="mt-4 block space-y-1.5">
            <span className="text-xs text-on-surface-variant">Seed the queue from a playlist (optional)</span>
            <select
              value={playlistId}
              onChange={(event) => setPlaylistId(event.target.value)}
              className="w-full rounded-lg border border-outline-variant/40 bg-surface-container px-3 py-2.5 text-sm focus:border-primary focus:outline-none"
            >
              <option value="">Empty queue</option>
              {playlists?.map((p) => (
                <option key={p.playlist_id} value={p.playlist_id}>
                  {p.name} · {p.song_count} songs
                </option>
              ))}
            </select>
          </label>
          <Button variant="primary" icon="add_circle" onClick={() => void create()} disabled={busy} className="mt-5 py-3">
            {busy ? 'Creating…' : 'Create Jam'}
          </Button>
          <p className="mt-3 text-xs text-on-surface-variant">You will be the Jam owner: only you can start, pause, seek or skip.</p>
          {error !== undefined && (
            <div className="mt-4">
              <Notice tone="error">{errorMessage(error)}</Notice>
            </div>
          )}
        </Card>

        <Card className="flex flex-col">
          <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-secondary/15">
            <Icon name="group_add" className="text-2xl text-secondary" />
          </div>
          <h2 className="font-headline text-xl font-semibold">Join a Jam</h2>
          <form onSubmit={join} className="mt-4 flex gap-2">
            <input
              value={code}
              onChange={(event) => {
                setCode(event.target.value);
                setJoinError(null);
              }}
              placeholder="Paste a Jam link or ID"
              aria-label="Jam link or ID"
              className="min-w-0 flex-1 rounded-lg border border-outline-variant/40 bg-surface-container px-3 py-2.5 font-mono text-sm focus:border-secondary focus:outline-none"
            />
            <Button type="submit" variant="cyan">
              Join
            </Button>
          </form>
          {joinError && <p className="mt-2 text-xs text-error">{joinError}</p>}
          <p className="mt-auto pt-6 text-xs text-on-surface-variant">
            Testing on one machine? Open the invite link in another tab with <code className="font-mono text-secondary">?user=new</code> to join as a different listener.
          </p>
        </Card>
      </div>

      {recent.length > 0 && (
        <section className="mt-10">
          <h2 className="mb-3 font-headline text-lg font-semibold">Your recent Jams</h2>
          <ul className="divide-y divide-outline-variant/20 rounded-xl border border-outline-variant/30 bg-surface-container-low">
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
