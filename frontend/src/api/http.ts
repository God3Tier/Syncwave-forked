// Thin fetch wrapper for the gateway's /api/<service>/ routes.
//
// Services report errors in one of two shapes: the shared contract
// {"error": {"code", "message"}} (contracts/README.md), or FastAPI's default
// {"detail": ...} which Jam still uses. Both become an ApiError.

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }

  /** The gateway answers 502/503/504 when the upstream container is missing or down. */
  get unavailable(): boolean {
    return this.status === 0 || this.status === 502 || this.status === 503 || this.status === 504;
  }
}

export function parseError(status: number, body: unknown): ApiError {
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>;
    const error = record.error;
    if (error && typeof error === 'object') {
      const { code, message } = error as Record<string, unknown>;
      return new ApiError(status, String(code ?? `HTTP_${status}`), String(message ?? code ?? ''));
    }
    const detail = record.detail;
    if (typeof detail === 'string') return new ApiError(status, `HTTP_${status}`, detail);
    if (Array.isArray(detail)) {
      const message = detail
        .map((item) => (item && typeof item === 'object' ? String((item as { msg?: unknown }).msg) : String(item)))
        .join('; ');
      return new ApiError(status, 'INVALID_REQUEST', message);
    }
  }
  return new ApiError(status, `HTTP_${status}`, typeof body === 'string' && body ? body : `Request failed (${status})`);
}

export interface RequestOptions {
  method?: string;
  query?: Record<string, string | number | boolean | null | undefined>;
  json?: unknown;
  body?: BodyInit;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export function buildUrl(path: string, query?: RequestOptions['query']): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/**
 * The browser may only call the SyncWave gateway: a path under /api/ on this
 * page's own origin. URLs that services hand back (Streaming's stream_url,
 * Sync's PREPARE) go through this too, so a bad value cannot send the browser
 * to another host. Returns the path and query to fetch.
 */
export function gatewayPath(url: string): string {
  const resolved = new URL(url, window.location.origin);
  if (resolved.origin !== window.location.origin || !resolved.pathname.startsWith('/api/')) {
    throw new ApiError(0, 'URL_NOT_ALLOWED', `Refusing to fetch ${resolved.origin}${resolved.pathname}: not a SyncWave API path`);
  }
  return `${resolved.pathname}${resolved.search}`;
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = gatewayPath(buildUrl(path, options.query));
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers };
  let body = options.body;
  if (options.json !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.json);
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method: options.method ?? 'GET',
      headers,
      body,
      signal: options.signal,
    });
  } catch (cause) {
    if (cause instanceof DOMException && cause.name === 'AbortError') throw cause;
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the SyncWave gateway');
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let parsed: unknown = text;
  try {
    parsed = text ? JSON.parse(text) : undefined;
  } catch {
    // Non-JSON body (e.g. an nginx error page); keep the raw text.
  }
  if (!response.ok) throw parseError(response.status, parsed);
  return parsed as T;
}
