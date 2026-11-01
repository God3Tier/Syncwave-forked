import { parseError, request } from './http';
import type { UploadReceipt } from './types';

export interface UploadInput {
  title: string;
  artist: string;
  audio: File;
  lyrics?: File | null;
  durationMs?: number | null;
  mood?: Mood | null;
}

/** The moods Recommendation matches to the weather (services/recommendation/README.md). */
export const MOODS = ['calm', 'mellow', 'upbeat', 'energetic'] as const;
export type Mood = (typeof MOODS)[number];

export function uploadForm(input: UploadInput): FormData {
  const form = new FormData();
  form.set('title', input.title);
  form.set('artist', input.artist);
  form.set('audio', input.audio);
  if (input.lyrics) form.set('lyrics', input.lyrics);
  if (input.durationMs) form.set('duration_ms', String(input.durationMs));
  if (input.mood) form.set('mood', input.mood);
  return form;
}

/**
 * POST /api/upload/uploads as multipart/form-data. XMLHttpRequest instead of
 * fetch because fetch cannot report upload progress.
 */
export function uploadSong(input: UploadInput, onProgress: (fraction: number) => void): Promise<UploadReceipt> {
  const form = uploadForm(input);

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload/uploads');
    xhr.setRequestHeader('Accept', 'application/json');
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      let body: unknown = xhr.responseText;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // keep text
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadReceipt);
      else reject(parseError(xhr.status, body));
    };
    xhr.onerror = () => reject(parseError(0, 'Could not reach the SyncWave gateway'));
    xhr.send(form);
  });
}

export function getUpload(songId: string, signal?: AbortSignal): Promise<UploadReceipt> {
  return request(`/api/upload/uploads/${encodeURIComponent(songId)}`, { signal });
}
