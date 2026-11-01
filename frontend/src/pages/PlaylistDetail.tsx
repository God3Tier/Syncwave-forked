import { useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { createJam, rememberJam } from '../api/jam';
import { addSong, deletePlaylist, getPlaylist, removeSong, renamePlaylist, reorderSongs, shufflePlaylist } from '../api/playlist';
import { searchSongs } from '../api/search';
import type { Playlist } from '../api/types';
import { Page } from '../components/Layout';
import { Button, Card, EqualizerIcon, Icon, IconButton, Notice, SongArt, Spinner, StatusChip } from '../components/ui';
import { errorMessage } from '../errors';
import { formatDuration } from '../format';
import { useAsync, useDebounced } from '../hooks/useAsync';
import { moveItem, useDragReorder } from '../hooks/useDragReorder';
import { refreshPlaylists } from '../hooks/usePlaylists';
import { useSongs } from '../hooks/useSongs';
import { userId } from '../identity';
import { usePlayer } from '../player/context';
import { Mosaic } from './Playlists';

export function PlaylistDetail() {
  const { playlistId = '' } = useParams();
  const navigate = useNavigate();
  const player = usePlayer();
  const playlist = useAsync((signal) => getPlaylist(playlistId, signal), [playlistId]);
  const [error, setError] = useState<unknown>();
  const ids = playlist.data?.songs.map((s) => s.song_id) ?? [];
  const songs = useSongs(ids);

  const apply = async (action: () => Promise<Playlist | void>) => {
    setError(undefined);
    try {
      const result = await action();
      if (result) playlist.setData(result);
      void refreshPlaylists();
    } catch (cause) {
      setError(cause);
    }
  };

  const drag = useDragReorder((from, to) => void apply(() => reorderSongs(playlistId, moveItem(ids, from, to))));

  if (playlist.loading && !playlist.data) return <Page><Spinner label="Loading playlist" /></Page>;
  if (!playlist.data) return <Page><Notice tone="error">{errorMessage(playlist.error)}</Notice></Page>;
  const data = playlist.data;
  const totalMs = ids.reduce((sum, id) => sum + (songs.get(id)?.duration_ms ?? 0), 0);

  const rename = () => {
    const name = window.prompt('Rename playlist', data.name)?.trim();
    if (name && name !== data.name) void apply(() => renamePlaylist(playlistId, name.slice(0, 100)));
  };
  const remove = async () => {
    if (!window.confirm(`Delete “${data.name}”?`)) return;
    await apply(() => deletePlaylist(playlistId));
    navigate('/playlists');
  };
  const startJam = async () => {
    try {
      const jam = await createJam(userId, playlistId);
      rememberJam(jam.jam_id, true);
      navigate(`/jam/${jam.jam_id}`);
    } catch (cause) {
      setError(cause);
    }
  };

  return (
    <Page wide>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="min-w-0 space-y-6">
          <Card className="flex flex-col gap-6 sm:flex-row sm:items-end">
            <div className="w-40 shrink-0 md:w-48">
              <Mosaic songIds={ids} />
            </div>
            <div className="min-w-0 flex-1">
              <span className="rounded border border-secondary/40 bg-secondary/10 px-2 py-0.5 font-mono text-[11px] tracking-widest text-secondary">PLAYLIST</span>
              <h1 className="mt-3 flex items-center gap-2 font-headline text-3xl font-bold tracking-tight md:text-4xl">
                <span className="truncate">{data.name}</span>
                <IconButton icon="edit" label="Rename playlist" onClick={rename} />
              </h1>
              <p className="mt-1 font-mono text-sm text-on-surface-variant">
                {data.song_count} song{data.song_count === 1 ? '' : 's'} · {Math.round(totalMs / 60000)} min
              </p>
              <div className="mt-5 flex flex-wrap items-center gap-3">
                <Button variant="primary" icon="play_arrow" disabled={!ids.length} onClick={() => player.playQueue(ids)} className="px-6">
                  Play
                </Button>
                <Button icon="shuffle" disabled={ids.length < 2} onClick={() => void apply(() => shufflePlaylist(playlistId))}>
                  Shuffle
                </Button>
                <Button variant="cyan" icon="sensors" onClick={() => void startJam()}>
                  Start Jam with this playlist
                </Button>
                <IconButton icon="delete" label="Delete playlist" onClick={() => void remove()} className="ml-auto hover:text-error" />
              </div>
            </div>
          </Card>

          {error !== undefined && <Notice tone="error">{errorMessage(error)}</Notice>}

          <Card className="p-2">
            {ids.length === 0 && <p className="px-3 py-8 text-center text-on-surface-variant">No songs yet. Add some from the panel.</p>}
            <ol>
              {ids.map((id, i) => {
                const song = songs.get(id);
                const current = player.currentId === id;
                return (
                  <li key={id} {...drag.rowProps(i)} className={`relative ${drag.dragging === i ? 'opacity-40' : ''}`}>
                    {drag.gap === i && <DropLine />}
                    <div className={`group grid grid-cols-[auto_auto_minmax(0,1fr)_auto] items-center gap-3 rounded-xl px-2 py-2 hover:bg-surface-container-high md:grid-cols-[auto_2rem_minmax(0,1fr)_5rem_7rem_auto] ${current ? 'bg-surface-container-high' : ''}`}>
                      <Icon name="drag_indicator" className="cursor-grab text-lg text-outline" />
                      <span className="hidden font-mono text-xs text-outline md:block">{current && player.playing ? <EqualizerIcon /> : String(i + 1).padStart(2, '0')}</span>
                      <button type="button" onClick={() => player.playQueue(ids, i)} className="flex min-w-0 items-center gap-3 text-left">
                        <SongArt id={id} size="sm" />
                        <span className="min-w-0">
                          <span className={`block truncate font-headline text-sm font-semibold ${current ? 'text-primary' : ''}`}>{song?.title ?? (song === null ? 'Unknown song' : '…')}</span>
                          <span className="block truncate text-xs text-on-surface-variant">{song?.artist ?? ''}</span>
                        </span>
                      </button>
                      <span className="hidden font-mono text-xs text-on-surface-variant md:block">{formatDuration(song?.duration_ms)}</span>
                      <span className="hidden md:block">{song && <StatusChip status={song.processing_status} />}</span>
                      <IconButton icon="close" label="Remove from playlist" onClick={() => void apply(() => removeSong(playlistId, id))} />
                    </div>
                    {drag.gap === ids.length && i === ids.length - 1 && <DropLine bottom />}
                  </li>
                );
              })}
            </ol>
          </Card>
        </div>

        <AddSongsPanel existing={new Set(ids)} onAdd={(songId) => void apply(() => addSong(playlistId, songId))} />
      </div>
    </Page>
  );
}

function DropLine({ bottom = false }: { bottom?: boolean }) {
  return <div className={`pointer-events-none absolute inset-x-2 z-10 h-0.5 rounded-full bg-primary shadow-[0_0_8px_rgb(139_92_246/0.8)] ${bottom ? '-bottom-px' : '-top-px'}`} />;
}

export function AddSongsPanel({ existing, onAdd, title = 'Add songs' }: { existing: Set<string>; onAdd: (songId: string) => void; title?: string }) {
  const [query, setQuery] = useState('');
  const debounced = useDebounced(query.trim(), 300);
  const results = useAsync((signal) => (debounced ? searchSongs(debounced, null, signal) : Promise.resolve(null)), [debounced]);

  return (
    <Card className="h-fit">
      <h2 className="mb-4 flex items-center gap-2 font-headline text-lg font-semibold">
        <Icon name="playlist_add" className="text-primary" /> {title}
      </h2>
      <div className="relative mb-3">
        <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-lg text-outline" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search songs or artists"
          aria-label="Search songs to add"
          className="w-full rounded-lg border border-outline-variant/40 bg-surface-container py-2 pl-9 pr-3 text-sm focus:border-primary focus:outline-none"
        />
      </div>
      {results.loading && debounced && <Spinner label="Searching" />}
      {results.error !== undefined && <Notice tone="error">{errorMessage(results.error)}</Notice>}
      <ul className="space-y-2">
        {results.data?.items.map((item) => (
          <li key={item.song_id} className="flex items-center gap-3 rounded-xl border border-outline-variant/20 bg-surface-container p-2">
            <SongArt id={item.song_id} size="sm" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold">{item.title}</p>
              <p className="truncate text-xs text-on-surface-variant">{item.artist}</p>
            </div>
            {existing.has(item.song_id) ? (
              <span className="inline-flex items-center gap-1 rounded-lg border border-secondary/30 px-2 py-1 font-mono text-[11px] text-secondary">
                <Icon name="done" className="text-sm" /> Added
              </span>
            ) : (
              <Button onClick={() => onAdd(item.song_id)} icon="add" className="px-3 py-1 text-xs">
                Add
              </Button>
            )}
          </li>
        ))}
      </ul>
      {results.data && results.data.items.length === 0 && <p className="text-sm text-on-surface-variant">No songs match.</p>}
      {!debounced && <p className="text-sm text-on-surface-variant">Search the catalogue to add songs.</p>}
    </Card>
  );
}
