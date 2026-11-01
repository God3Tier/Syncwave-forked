import { Link } from 'react-router';
import { getWaveform } from '../api/media';
import { config } from '../config';
import { formatDuration } from '../format';
import { useAsync } from '../hooks/useAsync';
import { useSong } from '../hooks/useSongs';
import { usePlayer, usePosition } from '../player/context';
import { IconButton, Icon, SongArt } from './ui';
import { Waveform } from './Waveform';

/** Persistent bottom player (Stitch "Discover" screen). */
export function PlayerBar() {
  const player = usePlayer();
  const song = useSong(player.currentId);
  const position = usePosition(player.positionMs, player.playing);
  const waveform = useAsync(
    (signal) => (player.currentId ? getWaveform(player.currentId, 90, signal) : Promise.resolve(null)),
    [player.currentId],
  );
  const durationMs = player.durationMs || song?.duration_ms || 0;
  const bufferWindow = player.queue.slice(player.index, player.index + 1 + config.prefetchAhead);

  if (!player.currentId) {
    return (
      <footer className="flex h-16 items-center justify-center border-t border-outline-variant/20 bg-surface-container-low/95 px-4 font-mono text-xs text-outline backdrop-blur">
        Nothing playing. Pick a song to start listening.
      </footer>
    );
  }

  return (
    <footer className="grid grid-cols-[1fr_auto] items-center gap-3 border-t border-outline-variant/20 bg-surface-container-low/95 px-3 py-2 backdrop-blur md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_minmax(0,1fr)] md:px-5">
      <Link to={`/songs/${player.currentId}`} className="flex min-w-0 items-center gap-3">
        <SongArt id={player.currentId} size="md" />
        <div className="min-w-0">
          <p className="truncate font-headline text-sm font-semibold">{song?.title ?? 'Loading…'}</p>
          <p className="truncate text-xs text-on-surface-variant">{song?.artist ?? ''}</p>
        </div>
      </Link>

      <div className="order-last col-span-2 flex flex-col items-center gap-1 md:order-none md:col-span-1">
        <div className="flex items-center gap-2">
          <IconButton icon="skip_previous" label="Previous" onClick={player.previous} />
          <button
            type="button"
            onClick={player.toggle}
            aria-label={player.playing ? 'Pause' : 'Play'}
            className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-on-primary shadow-lg shadow-primary/30 transition-transform hover:scale-105"
          >
            <Icon name={player.playing ? 'pause' : 'play_arrow'} fill className="text-2xl" />
          </button>
          <IconButton icon="skip_next" label="Next" onClick={player.next} disabled={player.index + 1 >= player.queue.length} />
        </div>
        <div className="flex w-full max-w-xl items-center gap-3">
          <span className="w-10 text-right font-mono text-[11px] tabular-nums text-on-surface-variant">{formatDuration(position)}</span>
          <Waveform peaks={waveform.data?.peaks ?? []} durationMs={durationMs} positionMs={position} onSeek={player.seek} height={28} className="flex-1" />
          <span className="w-10 font-mono text-[11px] tabular-nums text-on-surface-variant">{formatDuration(durationMs)}</span>
        </div>
        {player.error && <p className="font-mono text-[11px] text-error">{player.error}</p>}
      </div>

      <div className="flex items-center justify-end gap-3">
        <div
          className="hidden items-center gap-2 rounded-lg border border-outline-variant/30 bg-surface-container px-2.5 py-1.5 lg:flex"
          title="Browser-side buffer: current song and the next ones in the queue"
        >
          <span className="font-mono text-[10px] uppercase text-outline">Buffer</span>
          {bufferWindow.map((id, i) => (
            <span
              key={`${id}-${i}`}
              className={`h-3.5 w-1.5 rounded-sm ${
                player.buffers[id] === 'ready' ? 'bg-secondary' : player.buffers[id] === 'loading' ? 'animate-pulse bg-secondary/40' : player.buffers[id] === 'error' ? 'bg-error' : 'bg-outline-variant/40'
              }`}
            />
          ))}
        </div>
        <label className="hidden items-center gap-2 md:flex">
          <Icon name={player.volume === 0 ? 'volume_off' : 'volume_up'} className="text-lg text-on-surface-variant" />
          <span className="sr-only">Volume</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={player.volume}
            onChange={(event) => player.setVolume(Number(event.target.value))}
            className="w-24 accent-[var(--color-primary)]"
          />
        </label>
      </div>
    </footer>
  );
}
