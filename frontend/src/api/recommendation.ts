import { request } from './http';
import type { Recommendations } from './types';

export function getRecommendations(
  location: Place | null,
  limit = 12,
  signal?: AbortSignal,
): Promise<Recommendations> {
  return request('/api/recommendation/recommendations', {
    query: { limit, lat: location?.lat, lon: location?.lon },
    signal,
  });
}

export interface Place {
  lat: number;
  lon: number;
}

/** Why the browser gave no location: it only shares one in a secure context (HTTPS or localhost). */
export type LocationProblem = 'insecure' | 'denied' | 'unavailable';

/**
 * Places whose live weather can stand in for the user's own, e.g. on the
 * plain-HTTP deployment where the browser will not share a location. Spread
 * over climates so different weather, and so different matches, can be shown.
 */
export const WEATHER_CITIES: Record<string, Place> = {
  Singapore: { lat: 1.35, lon: 103.82 },
  London: { lat: 51.51, lon: -0.13 },
  Reykjavik: { lat: 64.15, lon: -21.94 },
  Seattle: { lat: 47.61, lon: -122.33 },
  Dubai: { lat: 25.2, lon: 55.27 },
  Tokyo: { lat: 35.68, lon: 139.69 },
};

/** Coarse browser location for the weather signal, or why there is none. */
export function browserLocation(timeoutMs = 8000): Promise<Place | { problem: LocationProblem }> {
  if (!window.isSecureContext) return Promise.resolve({ problem: 'insecure' });
  if (!('geolocation' in navigator)) return Promise.resolve({ problem: 'unavailable' });
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) =>
        resolve({
          lat: Math.round(position.coords.latitude * 100) / 100,
          lon: Math.round(position.coords.longitude * 100) / 100,
        }),
      (error) => resolve({ problem: error.code === error.PERMISSION_DENIED ? 'denied' : 'unavailable' }),
      { enableHighAccuracy: false, timeout: timeoutMs, maximumAge: 30 * 60 * 1000 },
    );
  });
}
