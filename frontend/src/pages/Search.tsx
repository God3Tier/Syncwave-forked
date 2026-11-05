import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { searchSongs } from '../api/search';
import type { SearchResult } from '../api/types';
import { Page } from '../components/Layout';
import { SongRow } from '../components/SongRow';
import { Button, Icon, Notice, Spinner } from '../components/ui';
import { errorMessage } from '../errors';
import { useAsync, useDebounced } from '../hooks/useAsync';

export function Search() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const [input, setInput] = useState(q);
  const debounced = useDebounced(input.trim(), 300);

  useEffect(() => {
    if (debounced !== q) setParams(debounced ? { q: debounced } : {}, { replace: true });
  }, [debounced, q, setParams]);

  const [items, setItems] = useState<SearchResult[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const results = useAsync(
    async (signal) => {
      if (!q) {
        setItems([]);
        setCursor(null);
        return null;
      }
      const page = await searchSongs(q, null, signal);
      setItems(page.items);
      setCursor(page.next_cursor);
      return page;
    },
    [q],
  );
  const [loadingMore, setLoadingMore] = useState(false);
  const loadMore = async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await searchSongs(q, cursor);
      setItems((existing) => [...existing, ...page.items]);
      setCursor(page.next_cursor);
    } finally {
      setLoadingMore(false);
    }
  };

  const queue = items.map((item) => item.song_id);

  return (
    <Page wide>
      <header className="mb-8 border-b border-outline-variant/35 pb-7">
        <h1 className="text-3xl font-extrabold tracking-[-0.035em]">Search the catalogue</h1>
        <p className="mt-2 text-sm text-on-surface-variant">Find a track, play it now, or save it for later.</p>
      </header>
      <div className="relative mb-6 max-w-4xl">
        <Icon name="search" className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-xl text-outline" />
        <input
          type="search"
          name="catalogue-search"
          autoComplete="off"
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Search songs or artists…"
          aria-label="Search songs or artists"
          className="min-h-14 w-full rounded-2xl bg-surface-container-low py-3 pl-12 pr-4 text-sm ring-1 ring-outline-variant/45 placeholder:text-outline focus:ring-secondary focus:outline-none"
        />
      </div>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_17rem]">
        <div>
          {q && results.data && (
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <p className="text-lg font-extrabold">
                {items.length}
                {cursor ? '+' : ''} result{items.length === 1 ? '' : 's'} for “{q}”
              </p>
              <span className="inline-flex items-center gap-1.5 rounded-md bg-surface-container px-2.5 py-1 text-[11px] text-on-surface-variant">
                <span className={`h-1.5 w-1.5 rounded-full ${results.data.fallback ? 'bg-warn' : 'bg-secondary'}`} />
                {results.data.fallback ? 'Search service offline · filtering the catalogue' : 'Search service'}
              </span>
            </div>
          )}
          {!q && <p className="py-10 text-on-surface-variant">Start with a title or artist.</p>}
          {results.loading && q && <Spinner label="Searching" />}
          {results.error !== undefined && <Notice tone="error">{errorMessage(results.error)}</Notice>}
          {items.length > 0 && (
            <ul className="divide-y divide-outline-variant/25">
              {items.map((item, i) => (
                <SongRow key={item.song_id} song={item} index={i} queue={queue} query={q} />
              ))}
            </ul>
          )}
          {cursor && (
            <div className="mt-4 flex justify-center">
              <Button onClick={() => void loadMore()} disabled={loadingMore} icon="expand_more">
                {loadingMore ? 'Loading…' : 'Load more results'}
              </Button>
            </div>
          )}
          {q && results.data && items.length === 0 && <p className="py-8 text-on-surface-variant">No songs match “{q}”.</p>}
        </div>

        <aside className="h-fit border-l border-outline-variant/35 pl-6 lg:mt-2">
            <Icon name="cloud_upload" className="text-2xl text-primary" />
            <h2 className="mt-4 font-extrabold">Missing something?</h2>
            <p className="mt-2 text-sm leading-6 text-on-surface-variant">Upload your own track. Lyrics and waveform processing happen automatically.</p>
            <Link
              to="/upload"
              className="mt-4 inline-flex min-h-10 items-center gap-2 rounded-xl bg-primary px-4 py-2 text-sm font-bold text-on-primary"
            >
              <Icon name="upload" className="text-lg" /> Upload
            </Link>
        </aside>
      </div>
    </Page>
  );
}
