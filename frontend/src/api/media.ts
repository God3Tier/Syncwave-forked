// Lyrics, Waveform and Streaming: the per-song media APIs used while listening.

import { request } from './http';
import type { Lyrics, StreamInfo, Waveform, WaveformBands } from './types';

export function getLyrics(songId: string, signal?: AbortSignal): Promise<Lyrics> {
  return request(`/api/lyrics/songs/${encodeURIComponent(songId)}/lyrics`, { signal });
}

export function getWaveform(songId: string, points?: number, signal?: AbortSignal): Promise<Waveform> {
  return request(`/api/waveform/songs/${encodeURIComponent(songId)}/waveform`, { query: { points }, signal });
}

export function getWaveformBands(songId: string, signal?: AbortSignal): Promise<WaveformBands> {
  return request(`/api/waveform/songs/${encodeURIComponent(songId)}/waveform/bands`, { signal });
}

export function getStreamInfo(songId: string, signal?: AbortSignal): Promise<StreamInfo> {
  return request(`/api/streaming/tracks/${encodeURIComponent(songId)}/stream-info`, { signal });
}

/** Index of the lyric line being sung at positionMs, or -1 before the first line. */
export function activeLineIndex(lines: { time_ms: number }[], positionMs: number): number {
  let low = 0;
  let high = lines.length - 1;
  let found = -1;
  while (low <= high) {
    const mid = (low + high) >> 1;
    if (lines[mid].time_ms <= positionMs) {
      found = mid;
      low = mid + 1;
    } else {
      high = mid - 1;
    }
  }
  return found;
}

/**
 * Decodes the base64 `levels` of GET /waveform/bands: frame f occupies bytes
 * [f*band_count, (f+1)*band_count), each 0-255 (contracts/api/waveform.openapi.yaml).
 */
export function decodeBands(levels: string, bandCount: number): Uint8Array[] {
  if (bandCount <= 0) return [];
  const binary = atob(levels);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  const frames: Uint8Array[] = [];
  for (let offset = 0; offset + bandCount <= bytes.length; offset += bandCount) {
    frames.push(bytes.subarray(offset, offset + bandCount));
  }
  return frames;
}

/** Levels of the frame playing at timeMs. */
export function bandFrameAt(frames: Uint8Array[], frameRate: number, timeMs: number): Uint8Array | null {
  if (!frames.length || frameRate <= 0) return null;
  const index = Math.min(frames.length - 1, Math.max(0, Math.floor((timeMs / 1000) * frameRate)));
  return frames[index];
}
