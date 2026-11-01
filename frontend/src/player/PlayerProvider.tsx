// Personal (non-Jam) playback for Scenario 1.
//
// The browser owns the logical buffer (plan.md §5): it downloads the current
// song and pre-buffers the next `config.prefetchAhead` songs of the queue,
// keeps the previous one, and evicts everything else. Streaming does not yet
// support HTTP Range requests, so each song is fetched whole and played from
// an object URL; the window logic stays the same once ranges arrive.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ApiError } from '../api/http';
import { getStreamInfo } from '../api/media';
import { config } from '../config';
import { PlayerContext, type BufferState, type Player, type PlayerState } from './context';

export function PlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const getAudio = useCallback((): HTMLAudioElement => {
    if (!audioRef.current) {
      audioRef.current = new Audio();
      audioRef.current.preload = 'auto';
    }
    return audioRef.current;
  }, []);
  const urls = useRef(new Map<string, string>());
  const loads = useRef(new Map<string, { controller: AbortController; promise: Promise<string> }>());
  const [state, setState] = useState<PlayerState>({
    queue: [],
    index: 0,
    playing: false,
    durationMs: 0,
    buffers: {},
    error: null,
    volume: 0.8,
  });
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const setBuffer = useCallback((id: string, value: BufferState | null) => {
    setState((s) => {
      const buffers = { ...s.buffers };
      if (value) buffers[id] = value;
      else delete buffers[id];
      return { ...s, buffers };
    });
  }, []);

  const ensureBuffered = useCallback(
    (id: string): Promise<string> => {
      const ready = urls.current.get(id);
      if (ready) return Promise.resolve(ready);
      const existing = loads.current.get(id);
      if (existing) return existing.promise;

      const controller = new AbortController();
      setBuffer(id, 'loading');
      const promise = (async () => {
        const info = await getStreamInfo(id, controller.signal);
        const response = await fetch(info.stream_url, { signal: controller.signal });
        if (!response.ok) throw new ApiError(response.status, 'STREAM_UNAVAILABLE', `Audio request failed (${response.status})`);
        const url = URL.createObjectURL(await response.blob());
        urls.current.set(id, url);
        setBuffer(id, 'ready');
        return url;
      })();
      promise
        .catch(() => {
          if (!controller.signal.aborted) setBuffer(id, 'error');
        })
        .finally(() => loads.current.delete(id));
      loads.current.set(id, { controller, promise });
      return promise;
    },
    [setBuffer],
  );

  // Keep [index-1, index+prefetchAhead] buffered and drop the rest.
  const maintainWindow = useCallback(
    (queue: string[], index: number) => {
      const keep = new Set(queue.slice(Math.max(0, index - 1), index + 1 + config.prefetchAhead));
      for (const [id, url] of urls.current) {
        if (!keep.has(id)) {
          URL.revokeObjectURL(url);
          urls.current.delete(id);
          setBuffer(id, null);
        }
      }
      for (const [id, load] of loads.current) {
        if (!keep.has(id)) {
          load.controller.abort();
          loads.current.delete(id);
          setBuffer(id, null);
        }
      }
      for (const id of queue.slice(index + 1, index + 1 + config.prefetchAhead)) void ensureBuffered(id).catch(() => undefined);
    },
    [ensureBuffered, setBuffer],
  );

  const loadIndex = useCallback(
    (queue: string[], index: number, autoplay: boolean) => {
      const id = queue[index];
      if (!id) return;
      setState((s) => ({ ...s, queue, index, error: null, durationMs: 0 }));
      stateRef.current = { ...stateRef.current, queue, index };
      const element = getAudio();
      element.pause();
      maintainWindow(queue, index);
      ensureBuffered(id)
        .then((url) => {
          const { queue: q, index: i } = stateRef.current;
          if (q[i] !== id) return; // the user moved on while this was loading
          element.src = url;
          element.volume = stateRef.current.volume;
          if (autoplay) void element.play().catch(() => undefined);
        })
        .catch((error: unknown) => {
          const message = error instanceof ApiError && error.status === 409 ? 'This song is still processing.' : 'Could not load the audio.';
          setState((s) => ({ ...s, error: message, playing: false }));
        });
    },
    [getAudio, ensureBuffered, maintainWindow],
  );

  useEffect(() => {
    const element = getAudio();
    const onPlay = () => setState((s) => ({ ...s, playing: true }));
    const onPause = () => setState((s) => ({ ...s, playing: false }));
    const onMetadata = () => setState((s) => ({ ...s, durationMs: Number.isFinite(element.duration) ? element.duration * 1000 : 0 }));
    const onEnded = () => {
      const { queue, index } = stateRef.current;
      if (index + 1 < queue.length) loadIndex(queue, index + 1, true);
    };
    element.addEventListener('play', onPlay);
    element.addEventListener('pause', onPause);
    element.addEventListener('loadedmetadata', onMetadata);
    element.addEventListener('ended', onEnded);
    return () => {
      element.removeEventListener('play', onPlay);
      element.removeEventListener('pause', onPause);
      element.removeEventListener('loadedmetadata', onMetadata);
      element.removeEventListener('ended', onEnded);
    };
  }, [getAudio, loadIndex]);

  useEffect(() => {
    const created = urls.current;
    return () => {
      audioRef.current?.pause();
      for (const url of created.values()) URL.revokeObjectURL(url);
    };
  }, []);

  const positionMs = useCallback(() => (audioRef.current ? audioRef.current.currentTime * 1000 : 0), []);

  const value = useMemo<Player>(
    () => ({
      ...state,
      currentId: state.queue[state.index] ?? null,
      playQueue: (songIds, startIndex = 0) => loadIndex(songIds, startIndex, true),
      enqueue: (songId) => {
        const { queue, index } = stateRef.current;
        if (!queue.length) {
          loadIndex([songId], 0, true);
          return;
        }
        const next = [...queue, songId];
        setState((s) => ({ ...s, queue: next }));
        maintainWindow(next, index);
      },
      toggle: () => {
        if (!getAudio().src) {
          const { queue, index } = stateRef.current;
          if (queue.length) loadIndex(queue, index, true);
          return;
        }
        if (getAudio().paused) void getAudio().play().catch(() => undefined);
        else getAudio().pause();
      },
      pause: () => getAudio().pause(),
      next: () => {
        const { queue, index } = stateRef.current;
        if (index + 1 < queue.length) loadIndex(queue, index + 1, true);
      },
      previous: () => {
        const { queue, index } = stateRef.current;
        if (getAudio().currentTime > 3 || index === 0) getAudio().currentTime = 0;
        else loadIndex(queue, index - 1, true);
      },
      seek: (ms) => {
        if (getAudio().src) getAudio().currentTime = Math.max(0, ms / 1000);
      },
      setVolume: (volume) => {
        getAudio().volume = volume;
        setState((s) => ({ ...s, volume }));
      },
      positionMs,
    }),
    [state, getAudio, loadIndex, maintainWindow, positionMs],
  );

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
}
