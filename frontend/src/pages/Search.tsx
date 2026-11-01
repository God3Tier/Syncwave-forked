import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { searchSongs } from '../api/search';
import type { SearchResult } from '../api/types';
import { Page } from '../components/Layout';
import { SongRow } from '../components/SongRow';
import { Button, Card, Icon, Notice, Spinner } from '../components/ui';
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
      <div className="relative mb-4 max-w-3xl">
        <Icon name="search" className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-2xl text-outline" />
        <input
          type="search"
          autoFocus
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="Search songs or artists"
          aria-label="Search songs or artists"
          className="w-full rounded-xl border border-outline-variant/40 bg-surface-container-low py-4 pl-14 pr-4 text-base placeholder:text-outline focus:border-primary focus:outline-none"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div>
          {q && results.data && (
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <p className="font-headline text-lg">
                {items.length}
                {cursor ? '+' : ''} result{items.length === 1 ? '' : 's'} for “{q}”
              </p>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-outline-variant/40 px-2.5 py-0.5 font-mono text-[11px] text-on-surface-variant">
                <span className={`h-1.5 w-1.5 rounded-full ${results.data.fallback ? 'bg-warn' : 'bg-secondary'}`} />
                {results.data.fallback ? 'Search service offline · filtering the catalogue' : 'Search service'}
              </span>
            </div>
          )}
          {!q && <p className="py-8 text-on-surface-variant">Type a title or an artist to search the catalogue.</p>}
          {results.loading && q && <Spinner label="Searching" />}
          {results.error !== undefined && <Notice tone="error">{errorMessage(results.error)}</Notice>}
          {items.length > 0 && (
            <ul className="rounded-xl border border-outline-variant/30 bg-surface-container-low p-2">
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

        <aside>
          <Card className="border-dashed text-center">
            <div className="mx-auto mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
              <Icon name="cloud_upload" className="text-2xl text-primary" />
            </div>
            <h3 className="font-headline font-semibold">No match? Upload your own track</h3>
            <p className="mt-2 text-sm text-on-surface-variant">Lyrics and waveform are processed automatically after upload.</p>
            <Link
              to="/upload"
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 font-headline text-sm font-semibold text-on-primary"
            >
              <Icon name="upload" className="text-lg" /> Upload
            </Link>
          </Card>
        </aside>
      </div>
    </Page>
  );
}
