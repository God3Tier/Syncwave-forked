import { useNavigate, useParams } from 'react-router';
import { getSong } from '../api/catalogue';
import { ApiError } from '../api/http';
import { getLyrics, getWaveform } from '../api/media';
import { createJam, queueSong, rememberJam } from '../api/jam';
import { config } from '../config';
import { formatDuration } from '../format';
import { AddToPlaylist } from '../components/AddToPlaylist';
import { Page } from '../components/Layout';
import { LyricsView } from '../components/LyricsView';
import { Waveform } from '../components/Waveform';
import { Button, Card, Icon, Notice, SongArt, Spinner, StatusChip } from '../components/ui';
import { errorMessage } from '../errors';
import { useAsync, useInterval } from '../hooks/useAsync';
import { rememberSong, useSongs } from '../hooks/useSongs';
import { userId } from '../identity';
import { usePlayer, usePosition, type BufferState } from '../player/context';

function optional<T>(promise: Promise<T>): Promise<T | null> {
  return promise.catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  });
}

/** "Now Playing" song page (Stitch): waveform, synced lyrics and the buffer window. */
export function SongPage() {
  const { songId = '' } = useParams();
  const navigate = useNavigate();
  const player = usePlayer();

  const song = useAsync(async (signal) => {
    const value = await getSong(songId, signal);
    rememberSong(value);
    return value;
  }, [songId]);
  const lyrics = useAsync((signal) => optional(getLyrics(songId, signal)), [songId]);
  const waveform = useAsync((signal) => optional(getWaveform(songId, 600, signal)), [songId]);

  // While processing is still running, refresh until both stages settle.
  const processing = song.data?.processing_status === 'PROCESSING' || lyrics.data?.status === 'PROCESSING' || waveform.data?.status === 'PROCESSING';
  useInterval(
    () => {
      void getSong(songId).then(song.setData).catch(() => undefined);
      if (lyrics.data?.status !== 'READY') lyrics.reload();
      if (waveform.data?.status !== 'READY') waveform.reload();
    },
    3000,
    processing,
  );

  const isCurrent = player.currentId === songId;
  const position = usePosition(player.positionMs, isCurrent && player.playing);
  const positionMs = isCurrent ? position : 0;
  const durationMs = (isCurrent && player.durationMs) || song.data?.duration_ms || waveform.data?.duration_ms || 0;
  const seek = (ms: number) => {
    if (isCurrent) player.seek(ms);
  };

  if (song.loading && !song.data) return <Page><Spinner label="Loading song" /></Page>;
  if (song.error !== undefined && !song.data) {
    return (
      <Page>
        <Notice tone="error">{song.error instanceof ApiError && song.error.status === 404 ? 'This song is not in the catalogue.' : errorMessage(song.error)}</Notice>
      </Page>
    );
  }
  const data = song.data!;
  const playable = data.processing_status === 'READY' || data.processing_status === 'PARTIAL';

  const startJam = async () => {
    const jam = await createJam(userId);
    await queueSong(jam.jam_id, userId, songId);
    rememberJam(jam.jam_id, true);
    navigate(`/jam/${jam.jam_id}`);
  };

  return (
    <Page wide>
      <header className="mb-8 flex flex-col gap-6 md:flex-row md:items-end">
        <SongArt id={songId} size="xl" />
        <div className="min-w-0 flex-1">
          <p className="font-mono text-xs uppercase tracking-widest text-secondary">Song</p>
          <h1 className="mt-1 font-headline text-3xl font-bold tracking-tight md:text-5xl">{data.title}</h1>
          <p className="mt-2 text-lg text-on-surface-variant">
            {data.artist} <span className="font-mono text-sm text-outline">· {formatDuration(data.duration_ms)}</span>
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <StatusChip status={data.lyrics_status} label={`Lyrics ${data.lyrics_status}`} />
            <StatusChip status={data.waveform_status} label={`Waveform ${data.waveform_status}`} />
            <StatusChip status={data.processing_status} label={`Song ${data.processing_status}`} />
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              icon={isCurrent && player.playing ? 'pause' : 'play_arrow'}
              disabled={!playable}
              onClick={() => (isCurrent ? player.toggle() : player.playQueue([songId]))}
              className="px-6 py-3 text-base"
            >
              {isCurrent && player.playing ? 'Pause' : 'Play'}
            </Button>
            <Button variant="cyan" icon="sensors" disabled={!playable} onClick={() => void startJam()}>
              Start a Jam with this song
            </Button>
            <AddToPlaylist songId={songId} />
          </div>
        </div>
      </header>

      <Card className="mb-6">
        {waveform.data?.status === 'READY' ? (
          <>
            <Waveform peaks={waveform.data.peaks} durationMs={durationMs} positionMs={positionMs} onSeek={isCurrent ? seek : undefined} height={140} />
            <div className="mt-2 flex justify-between font-mono text-xs tabular-nums text-on-surface-variant">
              <span className="text-secondary">{formatDuration(positionMs)}</span>
              <span>{formatDuration(durationMs)}</span>
            </div>
          </>
        ) : (
          <p className="py-10 text-center font-mono text-sm text-on-surface-variant">
            {waveform.data?.status === 'FAILED'
              ? `Waveform failed: ${waveform.data.error?.message ?? 'unknown error'}`
              : waveform.data?.status === 'PROCESSING' || data.waveform_status === 'PROCESSING' || data.waveform_status === 'PENDING'
                ? 'Waveform is being generated…'
                : 'No waveform for this song.'}
          </p>
        )}
      </Card>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card>
          <h2 className="mb-4 flex items-center gap-2 font-headline text-lg font-semibold">
            Lyrics <span className="font-mono text-xs font-normal text-secondary">· synced</span>
          </h2>
          {lyrics.data?.status === 'READY' && lyrics.data.lines.length > 0 ? (
            <LyricsView lines={lyrics.data.lines} positionMs={positionMs} onSeek={isCurrent ? seek : undefined} />
          ) : (
            <p className="py-6 text-sm text-on-surface-variant">
              {lyrics.data?.status === 'FAILED'
                ? `Lyrics failed: ${lyrics.data.error?.message ?? 'unknown error'}`
                : lyrics.data?.status === 'PROCESSING'
                  ? 'Lyrics are being processed…'
                  : 'No lyrics were uploaded for this song.'}
            </p>
          )}
          {!isCurrent && lyrics.data?.status === 'READY' && <p className="mt-3 font-mono text-[11px] text-outline">Press play to follow along.</p>}
        </Card>
        <BufferWindowCard />
      </div>
    </Page>
  );
}

function BufferWindowCard() {
  const player = usePlayer();
  const start = Math.max(0, player.index - 1);
  const ids = player.queue.slice(start, player.index + 1 + config.prefetchAhead);
  const songs = useSongs(player.queue.slice(player.index + 1, player.index + 6));
  const upNext = player.queue.slice(player.index + 1, player.index + 5);
  const fill: Record<BufferState | 'none', string> = { ready: 'w-full bg-secondary', loading: 'w-1/2 animate-pulse bg-secondary/60', error: 'w-full bg-error', none: 'w-0' };

  return (
    <Card>
      <h2 className="font-headline text-lg font-semibold">Buffer window</h2>
      <p className="mb-4 mt-1 text-xs text-on-surface-variant">Audio is fetched by the browser; the next songs are pre-buffered and older ones evicted.</p>
      {ids.length === 0 && <p className="font-mono text-xs text-outline">Queue is empty.</p>}
      <ul className="space-y-2">
        {ids.map((id, i) => {
          const offset = start + i - player.index;
          return (
            <BufferRow key={`${id}-${offset}`} id={id} label={offset === 0 ? 'NOW' : offset > 0 ? `+${offset}` : `${offset}`} fill={fill[player.buffers[id] ?? 'none']} />
          );
        })}
      </ul>
      {upNext.length > 0 && (
        <>
          <h3 className="mb-2 mt-6 font-mono text-[11px] uppercase tracking-wider text-outline">Up next</h3>
          <ul className="space-y-1 text-sm">
            {upNext.map((id, i) => (
              <li key={`${id}-${i}`} className="truncate text-on-surface-variant">
                {songs.get(id)?.title ?? '…'} <span className="text-outline">· {songs.get(id)?.artist ?? ''}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

function BufferRow({ id, label, fill }: { id: string; label: string; fill: string }) {
  const songs = useSongs([id]);
  return (
    <li className="flex items-center gap-3">
      <span className={`w-9 font-mono text-[11px] ${label === 'NOW' ? 'text-secondary' : 'text-outline'}`}>{label}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm">{songs.get(id)?.title ?? '…'}</p>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-container-highest">
          <div className={`h-full rounded-full transition-all ${fill}`} />
        </div>
      </div>
      <Icon name={fill.includes('error') ? 'error' : 'graphic_eq'} className={`text-base ${fill.includes('error') ? 'text-error' : 'text-outline'}`} />
    </li>
  );
}
