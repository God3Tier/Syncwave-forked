import { request } from './http';
import type { Page, Playlist, PlaylistSummary } from './types';

const BASE = '/api/playlist/playlists';
const one = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

export function listPlaylists(ownerId: string, cursor: string | null = null): Promise<Page<PlaylistSummary>> {
  return request(BASE, { query: { owner_id: ownerId, limit: 100, cursor } });
}

export function createPlaylist(ownerId: string, name: string): Promise<Playlist> {
  return request(BASE, { method: 'POST', json: { owner_id: ownerId, name } });
}

export function getPlaylist(id: string, signal?: AbortSignal): Promise<Playlist> {
  return request(one(id), { signal });
}

export function renamePlaylist(id: string, name: string): Promise<Playlist> {
  return request(one(id), { method: 'PATCH', json: { name } });
}

export function deletePlaylist(id: string): Promise<void> {
  return request(one(id), { method: 'DELETE' });
}

export function addSong(id: string, songId: string, position?: number): Promise<Playlist> {
  return request(`${one(id)}/songs`, { method: 'POST', json: { song_id: songId, position } });
}

export function reorderSongs(id: string, songIds: string[]): Promise<Playlist> {
  return request(`${one(id)}/songs`, { method: 'PUT', json: { song_ids: songIds } });
}

export function removeSong(id: string, songId: string): Promise<Playlist> {
  return request(`${one(id)}/songs/${encodeURIComponent(songId)}`, { method: 'DELETE' });
}

export function shufflePlaylist(id: string): Promise<Playlist> {
  return request(`${one(id)}/shuffle`, { method: 'POST' });
}
