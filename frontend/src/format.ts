export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return '--:--';
  const total = Math.floor(ms / 1000);
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

/** Parses "m:ss", "mm:ss" or plain seconds into milliseconds. */
export function parseTimestamp(value: string): number | null {
  const text = value.trim();
  if (!text) return null;
  const parts = text.split(':');
  if (parts.length > 2 || parts.some((part) => !/^\d+(\.\d+)?$/.test(part))) return null;
  const seconds = parts.length === 2 ? Number(parts[0]) * 60 + Number(parts[1]) : Number(parts[0]);
  return Math.round(seconds * 1000);
}

export function formatMs(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${Math.abs(value).toFixed(digits)} ms`;
}

export function shortId(id: string | null | undefined): string {
  if (!id) return '—';
  return `${id.slice(0, 4)}…${id.slice(-4)}`;
}

export function initials(id: string): string {
  return id.replace(/[^0-9a-f]/gi, '').slice(0, 2).toUpperCase();
}

export function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diff)) return '';
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? '' : 's'} ago`;
}

/** Stable hue pair per song so its gradient tile looks the same everywhere. */
export function gradientFor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  const from = 250 + (hash % 70); // violet → magenta
  const to = 180 + ((hash >>> 8) % 50); // cyan → blue
  const angle = 120 + ((hash >>> 16) % 90);
  return `linear-gradient(${angle}deg, hsl(${from} 75% 55%), hsl(${to} 85% 45%))`;
}
