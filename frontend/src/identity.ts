// There is no auth service yet. Following the proposal in contracts/README.md,
// the browser generates a user_id UUID once and keeps it in localStorage.
//
// To act as several Jam participants from one machine, open a tab with
// ?user=<uuid> (or ?user=new). The override is kept in sessionStorage, so it
// survives navigation within that tab only.

const LOCAL_KEY = 'syncwave.user_id';
const TAB_KEY = 'syncwave.tab_user_id';
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function safeGet(storage: Storage, key: string): string | null {
  try {
    return storage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value);
  } catch {
    // Private mode or blocked storage: the id lives for this page load only.
  }
}

function resolveUserId(): string {
  const requested = new URLSearchParams(window.location.search).get('user');
  if (requested === 'new') {
    const id = crypto.randomUUID();
    safeSet(sessionStorage, TAB_KEY, id);
    return id;
  }
  if (requested && UUID.test(requested)) {
    safeSet(sessionStorage, TAB_KEY, requested.toLowerCase());
    return requested.toLowerCase();
  }
  const tab = safeGet(sessionStorage, TAB_KEY);
  if (tab && UUID.test(tab)) return tab;

  const stored = safeGet(localStorage, LOCAL_KEY);
  if (stored && UUID.test(stored)) return stored;
  const id = crypto.randomUUID();
  safeSet(localStorage, LOCAL_KEY, id);
  return id;
}

export const userId = resolveUserId();

/** Starts this tab as a brand-new user (used by "Switch identity"). */
export function switchIdentity(): void {
  const url = new URL(window.location.href);
  url.searchParams.set('user', 'new');
  window.location.assign(url.toString());
}
