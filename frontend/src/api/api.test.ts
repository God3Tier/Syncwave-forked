import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, buildUrl, parseError } from './http';
import { activeLineIndex, bandFrameAt, decodeBands } from './media';
import { matchesQuery, searchSongs } from './search';
import { uploadForm } from './upload';

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

afterEach(() => vi.unstubAllGlobals());

describe('parseError', () => {
  it('reads the shared {"error": {code, message}} shape', () => {
    const error = parseError(404, { error: { code: 'SONG_NOT_FOUND', message: 'No such song' } });
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 404, code: 'SONG_NOT_FOUND', message: 'No such song' });
  });

  it("reads Jam's FastAPI {detail} shapes", () => {
    expect(parseError(403, { detail: 'only the owner may perform this action' })).toMatchObject({
      code: 'HTTP_403',
      message: 'only the owner may perform this action',
    });
    expect(parseError(422, { detail: [{ msg: 'field required' }, { msg: 'bad uuid' }] })).toMatchObject({
      code: 'INVALID_REQUEST',
      message: 'field required; bad uuid',
    });
  });

  it('flags gateway errors as unavailable', () => {
    expect(parseError(502, '<html>Bad Gateway</html>').unavailable).toBe(true);
    expect(parseError(409, {}).unavailable).toBe(false);
  });
});

describe('buildUrl', () => {
  it('drops empty query values', () => {
    expect(buildUrl('/api/x', { a: 1, b: undefined, c: null, d: '', e: 'y z' })).toBe('/api/x?a=1&e=y+z');
    expect(buildUrl('/api/x')).toBe('/api/x');
  });
});

describe('activeLineIndex', () => {
  const lines = [{ time_ms: 1000 }, { time_ms: 2500 }, { time_ms: 4000 }];
  it('finds the line being sung', () => {
    expect(activeLineIndex(lines, 0)).toBe(-1);
    expect(activeLineIndex(lines, 1000)).toBe(0);
    expect(activeLineIndex(lines, 2499)).toBe(0);
    expect(activeLineIndex(lines, 2500)).toBe(1);
    expect(activeLineIndex(lines, 99999)).toBe(2);
    expect(activeLineIndex([], 5)).toBe(-1);
  });
});

describe('waveform bands', () => {
  it('splits levels into frames of band_count bytes', () => {
    const levels = btoa(String.fromCharCode(0, 10, 20, 255, 128, 64, 1, 2));
    const frames = decodeBands(levels, 3);
    expect(frames.map((f) => Array.from(f))).toEqual([
      [0, 10, 20],
      [255, 128, 64],
    ]); // trailing partial frame is dropped
    expect(Array.from(bandFrameAt(frames, 10, 0)!)).toEqual([0, 10, 20]);
    expect(Array.from(bandFrameAt(frames, 10, 150)!)).toEqual([255, 128, 64]);
    expect(Array.from(bandFrameAt(frames, 10, 60_000)!)).toEqual([255, 128, 64]);
    expect(decodeBands(levels, 0)).toEqual([]);
  });
});

describe('searchSongs', () => {
  it('uses the Search Service when it is available', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { items: [{ song_id: 's1', title: 'Night', artist: 'A' }], next_cursor: null }));
    vi.stubGlobal('fetch', fetchMock);
    const result = await searchSongs('night');
    expect(result.fallback).toBe(false);
    expect(result.items).toHaveLength(1);
    expect(String(fetchMock.mock.calls[0][0])).toBe('/api/search/search?q=night&limit=20');
  });

  it('falls back to filtering READY catalogue songs when Search is down', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('Bad Gateway', { status: 502 }))
      .mockResolvedValueOnce(
        jsonResponse(200, {
          items: [
            { song_id: 's1', title: 'Late Night Drive', artist: 'Velvet' },
            { song_id: 's2', title: 'Morning', artist: 'Sun' },
            { song_id: 's3', title: 'Glow', artist: 'Night Owls' },
          ],
          next_cursor: null,
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const result = await searchSongs('night');
    expect(result.fallback).toBe(true);
    expect(result.items.map((item) => item.song_id)).toEqual(['s1', 's3']);
    expect(String(fetchMock.mock.calls[1][0])).toContain('/api/catalogue/songs?limit=100&processing_status=READY');
  });

  it('matches every term against title and artist', () => {
    expect(matchesQuery({ title: 'Late Night Drive', artist: 'Velvet Synth' }, 'night velvet')).toBe(true);
    expect(matchesQuery({ title: 'Late Night Drive', artist: 'Velvet Synth' }, 'night rain')).toBe(false);
  });
});

describe('gatewayPath', () => {
  it('allows only /api/ paths on this origin', async () => {
    const { gatewayPath } = await import('./http');
    expect(gatewayPath('/api/streaming/tracks/x/audio')).toBe('/api/streaming/tracks/x/audio');
    expect(gatewayPath(`${window.location.origin}/api/catalogue/songs?limit=5`)).toBe('/api/catalogue/songs?limit=5');
    expect(() => gatewayPath('http://169.254.169.254/latest/meta-data')).toThrow(ApiError);
    expect(() => gatewayPath('//evil.example/api/x')).toThrow(ApiError);
    expect(() => gatewayPath('/admin')).toThrow(ApiError);
  });
});

describe('uploadForm', () => {
  const audio = new File(['ID3'], 'song.mp3', { type: 'audio/mpeg' });

  it('sends the chosen mood', () => {
    const form = uploadForm({ title: 'T', artist: 'A', audio, mood: 'calm' });
    expect(form.get('mood')).toBe('calm');
    expect(form.get('title')).toBe('T');
  });

  it('leaves optional fields out when they are not set', () => {
    const form = uploadForm({ title: 'T', artist: 'A', audio, mood: null, durationMs: null });
    expect(form.has('mood')).toBe(false);
    expect(form.has('duration_ms')).toBe(false);
    expect(form.has('lyrics')).toBe(false);
  });
});
