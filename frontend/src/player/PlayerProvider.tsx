import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { ApiError, gatewayPath } from '../api/http';
import { getStreamManifest } from '../api/media';
import type { StreamManifest } from '../api/types';
import { bufferSlots, DownloadPool } from './chunkBuffer';
import { PlayerContext, type BufferState, type Player, type PlayerState } from './context';
import { recordPlay } from '../api/catalogue';
import { uuid } from '../uuid';

type ChunkLoad = { controller: AbortController; promise: Promise<string> };

/** Browser-owned, two-download, nine-position chunk playback for solo listening. */
export function PlayerProvider({ children }: { children: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const getAudio = useCallback(() => {
    if (!audioRef.current) {
      audioRef.current = new Audio();
      audioRef.current.preload = 'auto';
    }
    return audioRef.current;
  }, []);
  const manifests = useRef(new Map<string, StreamManifest>());
  const manifestLoads = useRef(new Map<string, Promise<StreamManifest>>());
  const chunkUrls = useRef(new Map<string, string>());
  const chunkLoads = useRef(new Map<string, ChunkLoad>());
  const pool = useRef(new DownloadPool(2));
  const chunkIndex = useRef(0);
  const [state, setState] = useState<PlayerState>({
    queue: [], index: 0, playing: false, durationMs: 0, buffers: {}, error: null, volume: 0.8,
  });
  const stateRef = useRef(state);
  useEffect(() => { stateRef.current = state; }, [state]);

  const setBuffer = useCallback((id: string, value: BufferState | null) => {
    setState((current) => {
      const buffers = { ...current.buffers };
      if (value) buffers[id] = value;
      else delete buffers[id];
      return { ...current, buffers };
    });
  }, []);

  const ensureManifest = useCallback((songId: string) => {
    const ready = manifests.current.get(songId);
    if (ready) return Promise.resolve(ready);
    const pending = manifestLoads.current.get(songId);
    if (pending) return pending;
    const promise = getStreamManifest(songId).then((manifest) => {
      manifests.current.set(songId, manifest);
      return manifest;
    }).finally(() => manifestLoads.current.delete(songId));
    manifestLoads.current.set(songId, promise);
    return promise;
  }, []);

  const ensureChunk = useCallback(async (songId: string, manifest: StreamManifest, index: number, priority: number) => {
    const chunk = manifest.chunks[index];
    if (!chunk) throw new Error('Chunk is outside the track');
    const key = `${songId}:${manifest.media_version}:${index}`;
    const ready = chunkUrls.current.get(key);
    if (ready) return ready;
    const pending = chunkLoads.current.get(key);
    if (pending) return pending.promise;
    const controller = new AbortController();
    const promise = pool.current.schedule(priority, async () => {
      const response = await fetch(gatewayPath(chunk.url), { signal: controller.signal });
      if (!response.ok) throw new ApiError(response.status, 'CHUNK_UNAVAILABLE', `Audio chunk failed (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      chunkUrls.current.set(key, url);
      return url;
    }).finally(() => chunkLoads.current.delete(key));
    chunkLoads.current.set(key, { controller, promise });
    return promise;
  }, []);

  const bufferTrack = useCallback(async (songId: string, targetMs: number, priority: number) => {
    setBuffer(songId, 'loading');
    try {
      const manifest = await ensureManifest(songId);
      const count = Math.min(manifest.chunks.length, Math.ceil(targetMs / manifest.chunk_duration_ms));
      await Promise.all(Array.from({ length: count }, (_, index) => ensureChunk(songId, manifest, index, priority)));
      setBuffer(songId, 'ready');
      return manifest;
    } catch (error) {
      setBuffer(songId, 'error');
      throw error;
    }
  }, [ensureChunk, ensureManifest, setBuffer]);

  const maintainWindow = useCallback((queue: string[], index: number) => {
    const constrained = window.innerWidth < 768
      || ('deviceMemory' in navigator && Number(navigator.deviceMemory) <= 4);
    const slots = bufferSlots(queue, index, constrained);
    const keep = new Set(slots.flatMap((slot) => slot.songId ? [slot.songId] : []));
    for (const [key, url] of chunkUrls.current) {
      if (!keep.has(key.split(':', 1)[0])) {
        URL.revokeObjectURL(url);
        chunkUrls.current.delete(key);
      }
    }
    for (const [key, load] of chunkLoads.current) {
      if (!keep.has(key.split(':', 1)[0])) load.controller.abort();
    }
    for (const id of Object.keys(stateRef.current.buffers)) if (!keep.has(id)) setBuffer(id, null);
    for (const slot of slots.sort((a, b) => a.priority - b.priority)) {
      if (slot.songId) void bufferTrack(slot.songId, slot.targetMs, slot.priority).catch(() => undefined);
    }
  }, [bufferTrack, setBuffer]);

  const playChunk = useCallback(async (
    queue: string[], queueIndex: number, nextChunkIndex: number, autoplay: boolean, offsetMs = 0,
  ) => {
    const songId = queue[queueIndex];
    if (!songId) return;
    const manifest = await ensureManifest(songId);
    const url = await ensureChunk(songId, manifest, nextChunkIndex, -1);
    if (stateRef.current.queue[stateRef.current.index] !== songId) return;
    chunkIndex.current = nextChunkIndex;
    const audio = getAudio();
    audio.src = url;
    audio.volume = stateRef.current.volume;
    if (offsetMs > 0) {
      const applyOffset = () => { audio.currentTime = offsetMs / 1000; };
      if (audio.readyState >= HTMLMediaElement.HAVE_METADATA) applyOffset();
      else audio.addEventListener('loadedmetadata', applyOffset, { once: true });
    }
    setState((current) => ({ ...current, durationMs: manifest.duration_ms }));
    if (autoplay) await audio.play().catch(() => undefined);
  }, [ensureChunk, ensureManifest, getAudio]);

  const loadIndex = useCallback((queue: string[], index: number, autoplay: boolean) => {
    const songId = queue[index];
    if (!songId) return;
    getAudio().pause();
    setState((current) => ({ ...current, queue, index, error: null, durationMs: 0 }));
    stateRef.current = { ...stateRef.current, queue, index };
    const playbackId = uuid();
    void playChunk(queue, index, 0, autoplay).then(() => {
      if (autoplay) void recordPlay(songId, playbackId, 'SOLO').catch(() => undefined);
      return maintainWindow(queue, index);
    }).catch((error: unknown) => {
      const message = error instanceof ApiError && error.status === 409
        ? 'This song is still processing.' : 'Could not load the audio.';
      setState((current) => ({ ...current, error: message, playing: false }));
    });
  }, [getAudio, maintainWindow, playChunk]);

  useEffect(() => {
    const audio = getAudio();
    const onPlay = () => setState((current) => ({ ...current, playing: true }));
    const onPause = () => setState((current) => ({ ...current, playing: false }));
    const onEnded = () => {
      const { queue, index } = stateRef.current;
      const songId = queue[index];
      const manifest = songId ? manifests.current.get(songId) : null;
      if (manifest && chunkIndex.current + 1 < manifest.chunks.length) {
        void playChunk(queue, index, chunkIndex.current + 1, true);
      } else if (index + 1 < queue.length) loadIndex(queue, index + 1, true);
    };
    audio.addEventListener('play', onPlay);
    audio.addEventListener('pause', onPause);
    audio.addEventListener('ended', onEnded);
    return () => {
      audio.removeEventListener('play', onPlay);
      audio.removeEventListener('pause', onPause);
      audio.removeEventListener('ended', onEnded);
    };
  }, [getAudio, loadIndex, playChunk]);

  useEffect(() => {
    const urls = chunkUrls.current;
    const loads = chunkLoads.current;
    return () => {
      audioRef.current?.pause();
      for (const load of loads.values()) load.controller.abort();
      for (const url of urls.values()) URL.revokeObjectURL(url);
    };
  }, []);

  const positionMs = useCallback(() => {
    const songId = stateRef.current.queue[stateRef.current.index];
    const manifest = songId ? manifests.current.get(songId) : null;
    const base = manifest?.chunks[chunkIndex.current]?.start_ms ?? 0;
    return base + (audioRef.current?.currentTime ?? 0) * 1000;
  }, []);

  // Built on first use, after the user has pressed play: a media element can be
  // routed into Web Audio only once, and from then on it is heard only through
  // the graph, so the analyser passes the sound on to the speakers.
  const graphRef = useRef<{ context: AudioContext; analyser: AnalyserNode } | null>(null);
  const analyser = useCallback((): AnalyserNode | null => {
    if (!graphRef.current) {
      try {
        const context = new AudioContext();
        const node = context.createAnalyser();
        node.fftSize = 2048;
        node.smoothingTimeConstant = 0.75;
        node.minDecibels = -90;
        node.maxDecibels = -20;
        context.createMediaElementSource(getAudio()).connect(node);
        node.connect(context.destination);
        graphRef.current = { context, analyser: node };
      } catch {
        return null;
      }
    }
    if (graphRef.current.context.state === 'suspended') void graphRef.current.context.resume();
    return graphRef.current.analyser;
  }, [getAudio]);

  const value = useMemo<Player>(() => ({
    ...state,
    currentId: state.queue[state.index] ?? null,
    playQueue: (songIds, startIndex = 0) => loadIndex(songIds, startIndex, true),
    enqueue: (songId) => {
      const { queue, index } = stateRef.current;
      if (!queue.length) return loadIndex([songId], 0, true);
      const next = [...queue, songId];
      setState((current) => ({ ...current, queue: next }));
      stateRef.current = { ...stateRef.current, queue: next };
      maintainWindow(next, index);
    },
    toggle: () => {
      const audio = getAudio();
      if (!audio.src) {
        const { queue, index } = stateRef.current;
        if (queue.length) loadIndex(queue, index, true);
      } else if (audio.paused) void audio.play().catch(() => undefined);
      else audio.pause();
    },
    pause: () => getAudio().pause(),
    next: () => {
      const { queue, index } = stateRef.current;
      if (index + 1 < queue.length) loadIndex(queue, index + 1, true);
    },
    previous: () => {
      const { queue, index } = stateRef.current;
      if (positionMs() > 3_000 || index === 0) void playChunk(queue, index, 0, !getAudio().paused);
      else loadIndex(queue, index - 1, true);
    },
    seek: (ms) => {
      const { queue, index, playing } = stateRef.current;
      const songId = queue[index];
      const manifest = songId ? manifests.current.get(songId) : null;
      if (!manifest) return;
      const bounded = Math.max(0, Math.min(ms, manifest.duration_ms - 1));
      const nextChunk = Math.min(manifest.chunks.length - 1, Math.floor(bounded / manifest.chunk_duration_ms));
      const offset = bounded - manifest.chunks[nextChunk].start_ms;
      void playChunk(queue, index, nextChunk, playing, offset);
    },
    setVolume: (volume) => {
      getAudio().volume = volume;
      setState((current) => ({ ...current, volume }));
    },
    positionMs,
    analyser,
  }), [state, getAudio, loadIndex, maintainWindow, playChunk, positionMs, analyser]);

  return <PlayerContext.Provider value={value}>{children}</PlayerContext.Provider>;
}
