import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router';
import { getSong } from '../api/catalogue';
import { ApiError } from '../api/http';
import { useAuth } from '../auth/AuthProvider';
import { getLyrics } from '../api/media';
import { createJam, queueSong, rememberJam } from '../api/jam';
import { formatDuration } from '../format';
import { AddToPlaylist } from '../components/AddToPlaylist';
import { Page } from '../components/Layout';
import { LyricsView } from '../components/LyricsView';
import { Visualizer } from '../components/Visualizer';
import { LyricsDisclosure } from '../components/LyricsDisclosure';
import { Button, Icon, Notice, SongArt, Spinner, StatusChip } from '../components/ui';
import { errorMessage } from '../errors';
import { useAsync, useInterval } from '../hooks/useAsync';
import { rememberSong, useSongs } from '../hooks/useSongs';
import { usePlayer, usePosition, type BufferState } from '../player/context';
import { bufferSlots } from '../player/chunkBuffer';
import { useJamSession } from '../jam/JamProvider';

function optional<T>(promise: Promise<T>): Promise<T | null> {
  return promise.catch((error: unknown) => {
    if (error instanceof ApiError && error.status === 404) return null;
    throw error;
  });
}

/** "Now Playing" song page (Stitch): waveform, synced lyrics, the buffer window and a live visualiser. */
export function SongPage() {
  const { songId = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { account, loading: authLoading } = useAuth();
  const hostIntentHandled = useRef(false);
  const [jamError, setJamError] = useState<unknown>();
  const player = usePlayer();
  const liveJam = useJamSession();

  const song = useAsync(async (signal) => {
    const value = await getSong(songId, signal);
    rememberSong(value);
    return value;
  }, [songId]);
  const lyrics = useAsync((signal) => optional(getLyrics(songId, signal)), [songId]);

  // While processing is still running, refresh until both stages settle.
  const processing = song.data?.processing_status === 'PROCESSING' || lyrics.data?.status === 'PROCESSING';
  useInterval(
    () => {
      void getSong(songId).then(song.setData).catch(() => undefined);
      if (lyrics.data?.status !== 'READY') lyrics.reload();
    },
    3000,
    processing,
  );

  const jamCurrent = liveJam.sync?.songId === songId;
  const soloCurrent = player.currentId === songId;
  const isCurrent = jamCurrent || soloCurrent;
  const jamPlaying = jamCurrent && liveJam.sync?.phase === 'PLAYING' && liveJam.localAudioState === 'RUNNING';
  const playing = jamPlaying || (soloCurrent && player.playing);
  const getPosition = useCallback(
    () => (jamCurrent ? liveJam.positionMs() : player.positionMs()),
    [jamCurrent, liveJam, player],
  );
  const position = usePosition(getPosition, playing);
  const positionMs = isCurrent ? position : 0;
  const durationMs = (jamCurrent ? liveJam.sync?.mediaMs : soloCurrent ? player.durationMs : 0) || song.data?.duration_ms || 0;
  const seek = (ms: number) => {
    if (jamCurrent && liveJam.owner) void liveJam.control('seek', { position_ms: ms });
    else if (soloCurrent) player.seek(ms);
  };

  const startJam = useCallback(async () => {
    if (authLoading) return;
    if (!account) {
      navigate(`/signup?returnTo=${encodeURIComponent(`/songs/${songId}`)}&intent=host`);
      return;
    }
    try {
      const jam = await createJam();
      const queued = await queueSong(jam.jam_id, songId);
      rememberJam(jam.jam_id, true);
      liveJam.adoptJam(queued);
      navigate(`/jam/${jam.jam_id}`);
    } catch (cause) {
      setJamError(cause);
    }
  }, [account, authLoading, liveJam, navigate, songId]);

  useEffect(() => {
    if (account && !authLoading && searchParams.get('intent') === 'host' && !hostIntentHandled.current) {
      hostIntentHandled.current = true;
      void startJam();
    }
  }, [account, authLoading, searchParams, startJam]);

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

  return (
    <Page wide>
      <header className="mb-8 flex flex-col gap-7 border-b border-outline-variant/35 pb-8 md:flex-row md:items-end">
        <SongArt id={songId} size="xl" />
        <div className="min-w-0 flex-1">
          <h1 className="text-3xl font-extrabold tracking-[-0.04em] md:text-5xl">{data.title}</h1>
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
              icon={playing ? 'pause' : 'play_arrow'}
              disabled={!playable || (jamCurrent && !liveJam.owner)}
              onClick={() => {
                if (jamCurrent) void liveJam.control(playing ? 'pause' : 'resume');
                else if (soloCurrent) player.toggle();
                else player.playQueue([songId]);
              }}
              className="px-6 py-3 text-base"
            >
              {jamCurrent && !liveJam.owner ? 'Playing in Jam' : playing ? 'Pause' : 'Play'}
            </Button>
            <Button variant="cyan" icon="sensors" disabled={!playable || authLoading} onClick={() => void startJam()}>
              {account ? 'Start a Jam with this song' : 'Sign in to host this song'}
            </Button>
            <AddToPlaylist songId={songId} />
          </div>
        </div>
      </header>

      {jamError !== undefined && <Notice tone="error">{errorMessage(jamError)}</Notice>}

      <section className="mb-8 overflow-hidden rounded-2xl bg-surface-container-low p-5 ring-1 ring-outline-variant/45">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="font-headline text-lg font-semibold">Live sound</h2>
          <span className="font-mono text-xs tabular-nums text-on-surface-variant">{formatDuration(positionMs)} / {formatDuration(durationMs)}</span>
        </div>
        <Visualizer active={playing} source={jamCurrent ? liveJam.analyser : undefined} height={180} />
        {!playing && <p className="mt-3 font-mono text-[11px] text-outline">Press play to see the music move.</p>}
      </section>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <LyricsDisclosure>
              {lyrics.data?.status === 'READY' && lyrics.data.lines.length > 0 ? (
                <LyricsView lines={lyrics.data.lines} positionMs={positionMs} onSeek={isCurrent && (!jamCurrent || liveJam.owner) ? seek : undefined} />
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
        </LyricsDisclosure>
        <BufferWindowCard />
      </div>
    </Page>
  );
}

function BufferWindowCard() {
  const player = usePlayer();
  const slots = bufferSlots(player.queue, player.index).filter((slot) => slot.songId !== null);
  const songs = useSongs(player.queue.slice(player.index + 1, player.index + 6));
  const upNext = player.queue.slice(player.index + 1, player.index + 5);
  const fill: Record<BufferState | 'none', string> = { ready: 'w-full bg-secondary', loading: 'w-1/2 animate-pulse bg-secondary/60', error: 'w-full bg-error', none: 'w-0' };

  return (
    <details className="group h-fit rounded-2xl bg-surface-container-low ring-1 ring-outline-variant/45 open:bg-surface-container open:ring-primary/45">
      <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-3 rounded-2xl px-5 text-sm font-extrabold hover:bg-surface-container-high focus:outline-none focus-visible:ring-2 focus-visible:ring-primary">
        Playback details
        <Icon name="expand_more" className="text-xl text-primary transition-transform group-open:rotate-180" />
      </summary>
      <div className="px-5 pb-5">
      <p className="mb-4 text-xs leading-5 text-on-surface-variant">SyncWave preloads the next songs in this browser. Open this when playback needs troubleshooting.</p>
      {slots.length === 0 && <p className="font-mono text-xs text-outline">Queue is empty.</p>}
      <ul className="space-y-2">
        {slots.map(({ songId: id, offset }) => {
          if (!id) return null;
          return (
            <BufferRow key={`${id}-${offset}`} id={id} label={offset === 0 ? 'NOW' : offset > 0 ? `+${offset}` : `${offset}`} fill={fill[player.buffers[id] ?? 'none']} />
          );
        })}
      </ul>
      {upNext.length > 0 && (
        <>
          <h3 className="mb-2 mt-6 text-xs font-bold text-on-surface-variant">Up next</h3>
          <ul className="space-y-1 text-sm">
            {upNext.map((id, i) => (
              <li key={`${id}-${i}`} className="truncate text-on-surface-variant">
                {songs.get(id)?.title ?? '…'} <span className="text-outline">· {songs.get(id)?.artist ?? ''}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      </div>
    </details>
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
          <div className={`h-full rounded-full transition-[width] ${fill}`} />
        </div>
      </div>
      <Icon name={fill.includes('error') ? 'error' : 'graphic_eq'} className={`text-base ${fill.includes('error') ? 'text-error' : 'text-outline'}`} />
    </li>
  );
}
