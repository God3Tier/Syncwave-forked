import { request } from './http';
import type { Recommendations } from './types';

export function getRecommendations(
  location: { lat: number; lon: number } | null,
  limit = 12,
  signal?: AbortSignal,
): Promise<Recommendations> {
  return request('/api/recommendation/recommendations', {
    query: { limit, lat: location?.lat, lon: location?.lon },
    signal,
  });
}

/** Coarse browser location for the weather signal; null if denied or unavailable. */
export function browserLocation(timeoutMs = 8000): Promise<{ lat: number; lon: number } | null> {
  if (!('geolocation' in navigator)) return Promise.resolve(null);
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (position) =>
        resolve({
          lat: Math.round(position.coords.latitude * 100) / 100,
          lon: Math.round(position.coords.longitude * 100) / 100,
        }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: timeoutMs, maximumAge: 30 * 60 * 1000 },
    );
  });
}
