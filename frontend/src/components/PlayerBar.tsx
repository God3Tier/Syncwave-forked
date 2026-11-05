import { Link } from 'react-router';
import { getWaveform } from '../api/media';
import { formatDuration } from '../format';
import { useAsync } from '../hooks/useAsync';
import { useSong } from '../hooks/useSongs';
import { usePlayer, usePosition } from '../player/context';
import { bufferSlots } from '../player/chunkBuffer';
import { Icon, IconButton, SongArt } from './ui';
import { Waveform } from './Waveform';

export function PlayerBar() {
  const player = usePlayer();
  const song = useSong(player.currentId);
  const position = usePosition(player.positionMs, player.playing);
  const waveform = useAsync(
    (signal) => (player.currentId ? getWaveform(player.currentId, 90, signal) : Promise.resolve(null)),
    [player.currentId],
  );
  const durationMs = player.durationMs || song?.duration_ms || 0;
  const bufferWindow = bufferSlots(player.queue, player.index);

  if (!player.currentId) {
    return (
      <footer className="flex min-h-12 items-center justify-center border-t border-outline-variant/35 bg-surface-container-lowest px-4 text-center text-xs text-on-surface-variant">
        Choose a track to start listening.
      </footer>
    );
  }

  return (
    <footer className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-t border-outline-variant/40 bg-surface-container-lowest px-3 py-2 md:grid-cols-[minmax(12rem,1fr)_minmax(20rem,2fr)_minmax(12rem,1fr)] md:px-5">
      <Link to={`/songs/${player.currentId}`} className="flex min-w-0 items-center gap-3 rounded-xl">
        <SongArt id={player.currentId} size="md" />
        <div className="min-w-0">
          <p className="truncate text-sm font-extrabold">{song?.title ?? 'Loading…'}</p>
          <p className="truncate text-xs text-on-surface-variant">{song?.artist ?? ''}</p>
        </div>
      </Link>

      <div className="order-last col-span-2 flex min-w-0 items-center gap-3 md:order-none md:col-span-1">
        <div className="flex shrink-0 items-center gap-1">
          <IconButton icon="skip_previous" label="Previous" onClick={player.previous} className="size-9" />
          <button
            type="button"
            onClick={player.toggle}
            aria-label={player.playing ? 'Pause' : 'Play'}
            className="flex size-10 items-center justify-center rounded-full bg-on-surface text-background transition-transform hover:scale-[1.04] active:scale-95"
          >
            <Icon name={player.playing ? 'pause' : 'play_arrow'} fill className="text-2xl" />
          </button>
          <IconButton icon="skip_next" label="Next" onClick={player.next} disabled={player.index + 1 >= player.queue.length} className="size-9" />
        </div>
        <span className="hidden w-9 text-right font-mono text-[10px] tabular-nums text-on-surface-variant sm:block">{formatDuration(position)}</span>
        <Waveform
          peaks={waveform.data?.peaks ?? []}
          durationMs={durationMs}
          positionMs={position}
          onSeek={player.seek}
          height={30}
          className="min-w-0 flex-1"
        />
        <span className="hidden w-9 font-mono text-[10px] tabular-nums text-on-surface-variant sm:block">{formatDuration(durationMs)}</span>
        {player.error ? <span className="sr-only" role="alert">{player.error}</span> : null}
      </div>

      <div className="flex items-center justify-end gap-3">
        <div className="hidden items-center gap-1.5 lg:flex" title="Current browser buffer">
          {bufferWindow.map((slot) => (
            <span
              key={slot.offset}
              className={`h-4 w-1 rounded-full ${slot.offset === 0 ? 'h-5' : ''} ${slot.songId && player.buffers[slot.songId] === 'ready' ? 'bg-secondary' : slot.songId && player.buffers[slot.songId] === 'loading' ? 'animate-pulse bg-secondary/45' : slot.songId && player.buffers[slot.songId] === 'error' ? 'bg-error' : 'bg-outline-variant'}`}
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
            className="w-20 accent-[var(--color-primary)]"
          />
        </label>
      </div>
    </footer>
  );
}
