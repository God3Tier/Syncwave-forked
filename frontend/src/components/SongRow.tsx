import type { ReactNode } from 'react';
import { Link } from 'react-router';
import type { Song } from '../api/types';
import { formatDuration } from '../format';
import { highlightSegments } from '../highlight';
import { usePlayer } from '../player/context';
import { AddToPlaylist } from './AddToPlaylist';
import { EqualizerIcon, Icon, SongArt, StatusChip } from './ui';

export interface SongLike {
  song_id: string;
  title: string;
  artist: string;
  duration_ms?: number | null;
  processing_status?: Song['processing_status'];
}

/** Highlights query terms in a title (Stitch "Search results" screen). */
function highlight(text: string, query?: string): ReactNode {
  return highlightSegments(text, query).map((segment, i) =>
    segment.match ? (
      <mark key={i} className="rounded bg-primary/15 px-0.5 text-primary">
        {segment.text}
      </mark>
    ) : (
      segment.text
    ),
  );
}

/** One song in a list, with play and add-to-playlist actions. `queue` is what plays from here. */
export function SongRow({ song, index, queue, query, actions }: { song: SongLike; index?: number; queue: string[]; query?: string; actions?: ReactNode }) {
  const player = usePlayer();
  const current = player.currentId === song.song_id;
  const playable = !song.processing_status || song.processing_status === 'READY' || song.processing_status === 'PARTIAL';

  return (
    <li className={`group grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-1 py-2.5 transition-colors hover:bg-surface-container/55 md:grid-cols-[2rem_minmax(0,1fr)_5rem_7rem_auto] md:px-3 ${current ? 'bg-surface-container/70' : ''}`}>
      <span className="hidden text-center font-mono text-[11px] text-outline md:block">
        {current && player.playing ? <EqualizerIcon /> : index !== undefined ? String(index + 1).padStart(2, '0') : ''}
      </span>
      <div className="col-span-2 flex min-w-0 items-center gap-3 md:col-span-1">
        <button
          type="button"
          disabled={!playable}
          onClick={() => (current ? player.toggle() : player.playQueue(queue, Math.max(0, queue.indexOf(song.song_id))))}
          className="relative shrink-0 disabled:cursor-not-allowed"
          aria-label={current && player.playing ? `Pause ${song.title}` : `Play ${song.title}`}
        >
          <SongArt id={song.song_id} size="sm" />
          {playable && (
            <span className={`absolute inset-0 flex items-center justify-center rounded-[10px] bg-black/55 transition-opacity ${current ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 focus:opacity-100'}`}>
              <Icon name={current && player.playing ? 'pause' : 'play_arrow'} fill className="text-xl text-white" />
            </span>
          )}
        </button>
        <Link to={`/songs/${song.song_id}`} className="min-w-0">
          <p className={`truncate text-sm font-extrabold ${current ? 'text-primary' : ''}`}>{highlight(song.title, query)}</p>
          <p className="truncate text-xs text-on-surface-variant">{highlight(song.artist, query)}</p>
        </Link>
      </div>
      <span className="hidden font-mono text-xs tabular-nums text-on-surface-variant md:block">{formatDuration(song.duration_ms)}</span>
      <span className="hidden md:block">{song.processing_status && <StatusChip status={song.processing_status} />}</span>
      <div className="flex items-center justify-end gap-1">
        {actions}
        <AddToPlaylist songId={song.song_id} />
      </div>
    </li>
  );
}
