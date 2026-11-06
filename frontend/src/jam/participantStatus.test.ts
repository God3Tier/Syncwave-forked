import { describe, expect, it } from 'vitest';

import {
  connectionDotClasses,
  connectionStatusClasses,
  readinessDotClasses,
  readinessStatusClasses,
} from './participantStatus';

describe('Jam participant status colours', () => {
  it('uses coral primary for connected and mint secondary for ready', () => {
    expect(connectionStatusClasses(true)).toContain('text-primary');
    expect(connectionDotClasses(true)).toContain('bg-primary');
    expect(readinessStatusClasses(true)).toContain('text-secondary');
    expect(readinessDotClasses(true)).toContain('bg-secondary');
  });

  it('does not imply either state when disconnected and unready', () => {
    expect(connectionStatusClasses(false)).toBe('text-outline');
    expect(readinessStatusClasses(false)).toBe('text-outline');
  });
});
