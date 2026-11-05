import { describe, expect, it } from 'vitest';
import { formatDuration, formatMs, gradientFor, parseTimestamp, shortId } from './format';
import { moveItem } from './hooks/useDragReorder';

describe('format', () => {
  it('formats durations as mm:ss', () => {
    expect(formatDuration(0)).toBe('00:00');
    expect(formatDuration(222_900)).toBe('03:42');
    expect(formatDuration(null)).toBe('--:--');
  });

  it('parses seek input', () => {
    expect(parseTimestamp('1:30')).toBe(90_000);
    expect(parseTimestamp('01:05.5')).toBe(65_500);
    expect(parseTimestamp('45')).toBe(45_000);
    expect(parseTimestamp('')).toBeNull();
    expect(parseTimestamp('1:2:3')).toBeNull();
    expect(parseTimestamp('abc')).toBeNull();
  });

  it('formats signed milliseconds', () => {
    expect(formatMs(12.44, 1)).toBe('+12.4 ms');
    expect(formatMs(-21)).toBe('−21 ms');
    expect(formatMs(null)).toBe('—');
  });

  it('shortens ids and gives each song a stable gradient', () => {
    expect(shortId('7c1e0000-0000-4000-8000-00000000a90b')).toBe('7c1e…a90b');
    expect(gradientFor('a')).toBe(gradientFor('a'));
    expect(gradientFor('a')).not.toBe(gradientFor('b'));
  });
});

describe('moveItem', () => {
  it('moves an item into a gap of the original list', () => {
    expect(moveItem(['a', 'b', 'c', 'd'], 0, 2)).toEqual(['b', 'a', 'c', 'd']);
    expect(moveItem(['a', 'b', 'c', 'd'], 3, 0)).toEqual(['d', 'a', 'b', 'c']);
    expect(moveItem(['a', 'b', 'c', 'd'], 1, 4)).toEqual(['a', 'c', 'd', 'b']);
  });
});

describe('uuid', () => {
  it('builds a v4 UUID without crypto.randomUUID (plain-HTTP pages)', async () => {
    const { uuid } = await import('./uuid');
    const original = crypto.randomUUID;
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
    try {
      const id = uuid();
      expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
      expect(uuid()).not.toBe(id);
    } finally {
      Object.defineProperty(crypto, 'randomUUID', { value: original, configurable: true });
    }
  });
});

describe('highlightSegments', () => {
  it('marks every term case-insensitively without regular expressions', async () => {
    const { highlightSegments } = await import('./highlight');
    expect(highlightSegments('Late Night Drive', 'night')).toEqual([
      { text: 'Late ', match: false },
      { text: 'Night', match: true },
      { text: ' Drive', match: false },
    ]);
    expect(highlightSegments('Daisy Bell', 'bell dai')).toEqual([
      { text: 'Dai', match: true },
      { text: 'sy ', match: false },
      { text: 'Bell', match: true },
    ]);
    // Regex metacharacters are just text.
    expect(highlightSegments('a+b (live)', '(live) .*')).toEqual([
      { text: 'a+b ', match: false },
      { text: '(live)', match: true },
    ]);
    expect(highlightSegments('Glow', '')).toEqual([{ text: 'Glow', match: false }]);
  });
});
