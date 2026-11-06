import { describe, expect, it } from 'vitest';
import { guestNameFor } from './guestName';

// Same shape the Jam service accepts (services/jam/src/jam_service/guest_names.py)
const GUEST_NAME = /^[A-Z][a-z]{2,9}[A-Z][a-z]{2,9}[0-9]{2}$/;

describe('guestNameFor', () => {
  it('gives a readable name the Jam service accepts', () => {
    const name = guestNameFor('8f14e45f-ceea-4672-9c5e-3a7b1d2c4e60');
    expect(name).toMatch(GUEST_NAME);
  });

  it('is stable for the same id and varies between ids', () => {
    const id = '0b2f4b1c-1111-4c3d-8e9f-123456789abc';
    expect(guestNameFor(id)).toBe(guestNameFor(id));
    const names = new Set(
      Array.from({ length: 50 }, (_, index) => guestNameFor(`00000000-0000-4000-8000-${String(index).padStart(12, '0')}`)),
    );
    expect(names.size).toBeGreaterThan(40);
  });
});
