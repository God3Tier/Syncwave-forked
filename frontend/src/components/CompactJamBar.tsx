import { Link } from 'react-router';
import { getWaveform } from '../api/media';
import { formatDuration } from '../format';
import { useAsync } from '../hooks/useAsync';
import { useJamSession } from '../jam/JamProvider';
import { usePosition } from '../player/context';
import { useSong } from '../hooks/useSongs';
import { Icon, IconButton, SongArt } from './ui';
import { Waveform } from './Waveform';

/** Compact synchronized playback controls shown while an active Jam is off-screen. */
export function CompactJamBar() {
  const live = useJamSession();
  const songId = live.sync?.songId
    ?? live.jam?.queue.find((item) => item.queue_item_id === live.jam?.current_queue_item_id)?.song_id
    ?? null;
  const song = useSong(songId);
  const moving = live.sync?.phase === 'PLAYING' && live.localAudioState === 'RUNNING';
  const position = usePosition(live.positionMs, moving);
  const durationMs = live.sync?.mediaMs || song?.duration_ms || 0;
  const waveform = useAsync(
    (signal) => (songId ? getWaveform(songId, 90, signal).catch(() => null) : Promise.resolve(null)),
    [songId],
  );
  const paused = live.jam?.state === 'PAUSED';

  if (!live.jamId || !live.jam || live.jam.lifecycle_state !== 'ACTIVE') return null;

  return (
    <footer className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-t border-primary/30 bg-surface-container-lowest px-3 py-2 shadow-[0_-12px_30px_rgb(0_0_0/0.16)] md:grid-cols-[minmax(12rem,1fr)_minmax(20rem,2fr)_minmax(12rem,1fr)] md:px-5">
      <Link to={`/jam/${live.jamId}`} className="flex min-w-0 items-center gap-3 rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-primary">
        {songId ? <SongArt id={songId} size="md" /> : <span className="flex size-11 items-center justify-center rounded-xl bg-primary/15 text-primary"><Icon name="graphic_eq" /></span>}
        <div className="min-w-0">
          <p className="truncate text-sm font-extrabold">{song?.title ?? 'Your Jam is live'}</p>
          <p className="truncate text-xs text-on-surface-variant">{song?.artist ?? 'Open the room to manage the queue'}</p>
        </div>
      </Link>

      <div className="order-last col-span-2 flex min-w-0 items-center gap-3 md:order-none md:col-span-1">
        {live.owner && live.jam.state !== 'IDLE' ? (
          <IconButton
            icon={paused ? 'play_arrow' : 'pause'}
            label={paused ? 'Resume Jam' : 'Pause Jam'}
            onClick={() => void live.control(paused ? 'resume' : 'pause')}
            className="size-10 border border-primary/35 bg-primary/10 text-primary"
          />
        ) : (
          <span className={`size-2 shrink-0 rounded-full ${moving ? 'animate-pulse-glow bg-secondary' : 'bg-outline'}`} aria-hidden="true" />
        )}
        <span className="hidden w-9 text-right font-mono text-[10px] tabular-nums text-on-surface-variant sm:block">{formatDuration(position)}</span>
        <Waveform
          peaks={waveform.data?.peaks ?? []}
          durationMs={durationMs}
          positionMs={position}
          onSeek={live.owner ? (ms) => void live.control('seek', { position_ms: ms }) : undefined}
          height={38}
          className="min-w-0 flex-1 rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        />
        <span className="hidden w-9 font-mono text-[10px] tabular-nums text-on-surface-variant sm:block">{formatDuration(durationMs)}</span>
        {live.owner && <IconButton icon="skip_next" label="Skip Jam track" onClick={() => void live.control('skip')} className="size-9" />}
      </div>

      <div className="flex items-center justify-end gap-2">
        {live.localAudioState !== 'RUNNING' && (
          <button type="button" onClick={() => void live.enableAudio()} className="min-h-10 rounded-xl bg-primary px-3 text-xs font-extrabold text-on-primary">
            Join playback
          </button>
        )}
        <label className="hidden items-center gap-2 lg:flex">
          <Icon name={live.volume === 0 ? 'volume_off' : 'volume_up'} className="text-lg text-on-surface-variant" />
          <span className="sr-only">Jam volume</span>
          <input type="range" min={0} max={1} step={0.01} value={live.volume} onChange={(event) => live.setVolume(Number(event.target.value))} className="w-20 accent-[var(--color-primary)]" />
        </label>
        <Link to={`/jam/${live.jamId}`} className="hidden min-h-10 items-center rounded-xl px-3 text-xs font-bold text-primary hover:bg-primary/10 sm:flex">
          Open Jam
        </Link>
      </div>
    </footer>
  );
}
