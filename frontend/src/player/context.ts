import { createContext, useContext, useEffect, useState } from 'react';

export type BufferState = 'loading' | 'ready' | 'error';

export interface PlayerState {
  queue: string[];
  index: number;
  playing: boolean;
  durationMs: number;
  buffers: Record<string, BufferState>;
  error: string | null;
  volume: number;
}

export interface Player extends PlayerState {
  currentId: string | null;
  playQueue: (songIds: string[], startIndex?: number) => void;
  enqueue: (songId: string) => void;
  toggle: () => void;
  pause: () => void;
  next: () => void;
  previous: () => void;
  seek: (ms: number) => void;
  setVolume: (value: number) => void;
  positionMs: () => number;
}

export const PlayerContext = createContext<Player | null>(null);

export function usePlayer(): Player {
  const player = useContext(PlayerContext);
  if (!player) throw new Error('usePlayer must be used inside <PlayerProvider>');
  return player;
}

/**
 * Returns getPosition(), refreshed every animation frame while `active` and
 * a few times a second otherwise (so a seek while paused still shows).
 */
export function usePosition(getPosition: () => number, active: boolean): number {
  const [position, setPosition] = useState(0);
  useEffect(() => {
    if (!active) {
      const timer = setInterval(() => setPosition(getPosition()), 250);
      return () => clearInterval(timer);
    }
    let frame = 0;
    const tick = () => {
      setPosition(getPosition());
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [getPosition, active]);
  return position;
}
