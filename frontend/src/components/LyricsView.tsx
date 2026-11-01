import { useEffect, useRef } from 'react';
import { activeLineIndex } from '../api/media';
import type { LyricLine } from '../api/types';

function stamp(ms: number): string {
  const total = ms / 1000;
  const minutes = Math.floor(total / 60);
  return `${String(minutes).padStart(2, '0')}:${(total - minutes * 60).toFixed(2).padStart(5, '0')}`;
}

/** Synced lyrics: past lines dimmed, the current one large with a violet accent. */
export function LyricsView({ lines, positionMs, onSeek }: { lines: LyricLine[]; positionMs: number; onSeek?: (ms: number) => void }) {
  const active = activeLineIndex(lines, positionMs);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => {
    const element = listRef.current?.querySelector<HTMLElement>(`[data-line="${active}"]`);
    element?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [active]);

  return (
    <ol ref={listRef} className="max-h-[28rem] space-y-1 overflow-y-auto pr-2" aria-live="off">
      {lines.map((line, i) => {
        const state = i === active ? 'current' : i < active ? 'past' : 'next';
        return (
          <li key={`${line.time_ms}-${i}`} data-line={i}>
            <button
              type="button"
              onClick={() => onSeek?.(line.time_ms)}
              aria-current={state === 'current' ? 'true' : undefined}
              className={`flex w-full items-baseline gap-4 rounded-lg border-l-2 px-3 py-1.5 text-left transition-all ${
                state === 'current'
                  ? 'border-primary bg-primary/5 font-headline text-xl font-semibold text-on-surface md:text-2xl'
                  : state === 'past'
                    ? 'border-transparent text-on-surface-variant/50 hover:text-on-surface-variant'
                    : 'border-transparent text-on-surface-variant hover:text-on-surface'
              }`}
            >
              <span className="w-16 shrink-0 font-mono text-[11px] tabular-nums text-outline">{stamp(line.time_ms)}</span>
              <span>{line.text || '♪'}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}
