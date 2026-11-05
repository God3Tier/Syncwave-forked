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
  const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  const minutes = Math.round(diff / 60000);
  if (minutes < 1) return relative.format(0, 'minute');
  if (minutes < 60) return relative.format(-minutes, 'minute');
  const hours = Math.round(minutes / 60);
  if (hours < 24) return relative.format(-hours, 'hour');
  return relative.format(-Math.round(hours / 24), 'day');
}

/** Stable hue pair per song so its gradient tile looks the same everywhere. */
export function gradientFor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  const palettes = [
    ['#f26b49', '#6e2b1d', '#f2c75b'],
    ['#75d8bd', '#173f38', '#f0eee4'],
    ['#e39b62', '#4c2c22', '#84d9bf'],
    ['#d8c76d', '#35452f', '#f57552'],
    ['#8abf9f', '#263d33', '#dda05f'],
    ['#e07b78', '#4d2d31', '#e7d9ad'],
  ] as const;
  const [accent, base, detail] = palettes[hash % palettes.length];
  const x = 22 + ((hash >>> 8) % 56);
  const y = 18 + ((hash >>> 16) % 62);
  return `radial-gradient(circle at ${x}% ${y}%, ${detail} 0 11%, transparent 11.5%), linear-gradient(135deg, ${accent} 0 46%, ${base} 46% 100%)`;
}
