// A readable name for a guest, such as "SunnyOtter27", in place of an id.
// It is derived from the guest's user id, so it stays the same across visits
// (and per tab with ?user=new). It is sent when joining a Jam, and the Jam
// service keeps it unless someone in that Jam already has it. Keep the word
// lists in step with services/jam/src/jam_service/guest_names.py.

import { userId } from './identity';

const ADJECTIVES = [
  'Amber', 'Breezy', 'Bright', 'Calm', 'Clever', 'Cosmic', 'Dreamy', 'Electric',
  'Fuzzy', 'Gentle', 'Golden', 'Happy', 'Jazzy', 'Jolly', 'Lucky', 'Mellow',
  'Misty', 'Neon', 'Quiet', 'Rapid', 'Rosy', 'Silver', 'Sleepy', 'Snappy',
  'Sonic', 'Sunny', 'Swift', 'Velvet', 'Witty', 'Zesty',
];

const ANIMALS = [
  'Badger', 'Bear', 'Beaver', 'Crane', 'Dolphin', 'Falcon', 'Ferret', 'Finch',
  'Fox', 'Gecko', 'Heron', 'Koala', 'Lemur', 'Lynx', 'Moose', 'Narwhal',
  'Octopus', 'Otter', 'Owl', 'Panda', 'Puffin', 'Quokka', 'Raven', 'Robin',
  'Seal', 'Sparrow', 'Tiger', 'Turtle', 'Walrus', 'Wombat',
];

/** FNV-1a: a small, stable hash so the same id always gives the same name. */
function hash(value: string): number {
  let result = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 0x01000193) >>> 0;
  }
  return result;
}

export function guestNameFor(id: string): string {
  const value = hash(id);
  const adjective = ADJECTIVES[value % ADJECTIVES.length];
  const animal = ANIMALS[Math.floor(value / ADJECTIVES.length) % ANIMALS.length];
  const number = Math.floor(value / (ADJECTIVES.length * ANIMALS.length)) % 100;
  return `${adjective}${animal}${String(number).padStart(2, '0')}`;
}

export const guestName = guestNameFor(userId);
