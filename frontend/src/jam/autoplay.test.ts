import { describe, expect, it } from 'vitest';

import { autoplaySecondsRemaining } from './autoplay';

describe('autoplay owner deadline', () => {
  it('counts down against the persisted server deadline', () => {
    expect(autoplaySecondsRemaining(20_000, 10_000)).toBe(10);
    expect(autoplaySecondsRemaining(20_000, 19_001)).toBe(1);
    expect(autoplaySecondsRemaining(20_000, 20_000)).toBe(0);
    expect(autoplaySecondsRemaining(20_000, 25_000)).toBe(0);
  });
});
