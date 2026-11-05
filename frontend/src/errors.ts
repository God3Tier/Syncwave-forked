import { ApiError } from './api/http';

/** A short, user-facing explanation of a failed request. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.unavailable) return 'This service is not reachable right now. Is it running in the local stack?';
    return error.message || error.code;
  }
  return error instanceof Error ? error.message : String(error);
}
