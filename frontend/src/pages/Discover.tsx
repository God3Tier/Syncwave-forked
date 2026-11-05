import { useCallback, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { listSongs } from '../api/catalogue';
import { browserLocation, getRecommendations } from '../api/recommendation';
import type { Recommendation, Recommendations, Song, WeatherCondition } from '../api/types';
import { Page } from '../components/Layout';
import { SongRow } from '../components/SongRow';
import { Button, Icon, Notice, SectionTitle, SongArt, Spinner } from '../components/ui';
import { errorMessage } from '../errors';
import { formatDuration } from '../format';
import { useAsync } from '../hooks/useAsync';
import { rememberSong } from '../hooks/useSongs';
import { usePlayer } from '../player/context';

const WEATHER_KEY = 'syncwave.use_weather';
const weatherIcon: Record<WeatherCondition, string> = {
  CLEAR: 'clear_day',
  CLOUDY: 'cloud',
  RAIN: 'rainy',
  STORM: 'thunderstorm',
  SNOW: 'weather_snowy',
  FOG: 'foggy',
  OTHER: 'partly_cloudy_day',
};

function readWeatherOptIn(): boolean {
  try {
    return localStorage.getItem(WEATHER_KEY) === '1';
  } catch {
    return false;
  }
}

function WeatherControl({ data, onEnable, enabled }: { data?: Recommendations; onEnable: () => void; enabled: boolean }) {
  if (data?.weather_used && data.weather) {
    const { condition, temperature_c } = data.weather;
    return (
      <span className="inline-flex items-center gap-2 rounded-lg bg-secondary/8 px-3 py-2 text-xs font-semibold text-secondary ring-1 ring-secondary/25">
        <Icon name={weatherIcon[condition]} className="text-base" />
        {condition.charAt(0) + condition.slice(1).toLowerCase()} · {Math.round(temperature_c)}°C
      </span>
    );
  }
  if (!enabled) {
    return (
      <Button variant="cyan" icon="my_location" onClick={onEnable} className="min-h-9 py-1.5 text-xs">
        Use local weather
      </Button>
    );
  }
  return <span className="text-xs text-on-surface-variant">Showing general picks</span>;
}

function RecommendationCard({ item, queue }: { item: Recommendation; queue: string[] }) {
  const player = usePlayer();
  const current = player.currentId === item.song_id;
  return (
    <article className="group flex w-44 shrink-0 flex-col gap-3 md:w-48">
      <div className="relative">
        <SongArt id={item.song_id} size="lg" />
        <button
          type="button"
          onClick={() => (current ? player.toggle() : player.playQueue(queue, queue.indexOf(item.song_id)))}
          aria-label={`Play ${item.title}`}
          className={`absolute bottom-2 right-2 flex size-11 items-center justify-center rounded-full bg-on-surface text-background shadow-[0_9px_22px_rgb(0_0_0/0.28)] transition-[opacity,transform] ${current ? 'opacity-100' : 'translate-y-1 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 focus:opacity-100'}`}
        >
          <Icon name={current && player.playing ? 'pause' : 'play_arrow'} fill className="text-2xl" />
        </button>
      </div>
      <Link to={`/songs/${item.song_id}`} className="min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <p className="truncate text-sm font-extrabold">{item.title}</p>
          <span className="font-mono text-[10px] text-on-surface-variant">{formatDuration(item.duration_ms)}</span>
        </div>
        <p className="truncate text-xs text-on-surface-variant">{item.artist}</p>
      </Link>
      {item.reason === 'WEATHER_MATCH' ? <span className="self-start text-[11px] font-bold text-secondary">Matched to your weather</span> : null}
    </article>
  );
}

export function Discover() {
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [useWeather, setUseWeather] = useState(readWeatherOptIn);
  const recommendations = useAsync(
    async (signal) => getRecommendations(useWeather ? await browserLocation() : null, 12, signal),
    [useWeather],
  );

  const [songs, setSongs] = useState<Song[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const recent = useAsync(async (signal) => {
    const page = await listSongs({ limit: 20 }, signal);
    page.items.forEach(rememberSong);
    setSongs(page.items);
    setCursor(page.next_cursor);
    return page;
  }, []);
  const [loadingMore, setLoadingMore] = useState(false);
  const loadMore = useCallback(async () => {
    if (!cursor) return;
    setLoadingMore(true);
    try {
      const page = await listSongs({ limit: 20, cursor });
      page.items.forEach(rememberSong);
      setSongs((existing) => [...existing, ...page.items]);
      setCursor(page.next_cursor);
    } finally {
      setLoadingMore(false);
    }
  }, [cursor]);

  const enableWeather = () => {
    try {
      localStorage.setItem(WEATHER_KEY, '1');
    } catch {
      // Keep the choice for this tab only.
    }
    setUseWeather(true);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`);
  };

  const recQueue = recommendations.data?.items.map((item) => item.song_id) ?? [];
  const playable = songs.filter((song) => song.processing_status === 'READY' || song.processing_status === 'PARTIAL').map((song) => song.song_id);

  return (
    <Page wide>
      <header className="mb-10 grid gap-6 border-b border-outline-variant/35 pb-8 lg:grid-cols-[minmax(0,1fr)_minmax(22rem,0.7fr)] lg:items-end">
        <div>
          <h1 className="max-w-3xl text-3xl font-extrabold tracking-[-0.035em] md:text-4xl">Music lands better together.</h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-on-surface-variant md:text-base">Find something worth sharing, build the queue, then bring everyone into the same moment.</p>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button variant="primary" icon="graphic_eq" onClick={() => navigate('/jam')}>Start a Jam</Button>
            <Button icon="upload" onClick={() => navigate('/upload')}>Upload a track</Button>
          </div>
        </div>
        <form onSubmit={submit} className="relative">
          <Icon name="search" className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-xl text-outline" />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            name="catalogue-search"
            autoComplete="off"
            placeholder="Search songs or artists…"
            aria-label="Search songs or artists"
            className="min-h-14 w-full rounded-2xl bg-surface-container-low py-3 pl-12 pr-4 text-sm ring-1 ring-outline-variant/45 placeholder:text-outline focus:ring-secondary focus:outline-none"
          />
        </form>
      </header>

      <section className="mb-12">
        <SectionTitle aside={<WeatherControl data={recommendations.data} enabled={useWeather} onEnable={enableWeather} />}>
          For you right now
          <span className="mt-1.5 block text-sm font-normal leading-6 text-on-surface-variant">Playable picks from the catalogue, with weather matching when you choose it.</span>
        </SectionTitle>
        {recommendations.loading ? <Spinner label="Finding songs" /> : null}
        {recommendations.error !== undefined ? <Notice tone="error">{errorMessage(recommendations.error)}</Notice> : null}
        {recommendations.data?.items.length === 0 ? <Notice>No playable songs yet. Upload one to get started.</Notice> : null}
        <div className="-mx-1 flex gap-5 overflow-x-auto px-1 pb-4">
          {recommendations.data?.items.map((item) => <RecommendationCard key={item.song_id} item={item} queue={recQueue} />)}
        </div>
      </section>

      <section>
        <SectionTitle aside={<span className="text-xs text-on-surface-variant">{songs.length} loaded</span>}>Recently added</SectionTitle>
        {recent.loading ? <Spinner label="Loading catalogue" /> : null}
        {recent.error !== undefined ? <Notice tone="error">{errorMessage(recent.error)}</Notice> : null}
        {!recent.loading && songs.length === 0 && recent.error === undefined ? (
          <Notice action={<Link to="/upload" className="text-sm font-bold text-primary">Upload music</Link>}>Your catalogue is empty. Add the first track.</Notice>
        ) : null}
        {songs.length > 0 ? (
          <div>
            <div className="hidden grid-cols-[2rem_minmax(0,1fr)_5rem_7rem_auto] gap-3 border-b border-outline-variant/35 px-3 py-2 text-[11px] font-bold uppercase tracking-wider text-outline md:grid">
              <span>#</span>
              <span>Track</span>
              <span>Duration</span>
              <span>Status</span>
              <span className="text-right">Processing</span>
            </div>
            <ul className="divide-y divide-outline-variant/25">
              {songs.map((song, index) => (
                <SongRow key={song.song_id} song={song} index={index} queue={playable} actions={<StageChips song={song} />} />
              ))}
            </ul>
          </div>
        ) : null}
        {cursor ? (
          <div className="mt-5 flex justify-center">
            <Button onClick={() => void loadMore()} disabled={loadingMore} icon="expand_more">
              {loadingMore ? 'Loading…' : 'Load more'}
            </Button>
          </div>
        ) : null}
      </section>
    </Page>
  );
}

function StageChips({ song }: { song: Song }) {
  return (
    <span className="mr-2 hidden items-center gap-2 text-[10px] text-on-surface-variant lg:flex" title="Lyrics and waveform processing">
      <span>Lyrics</span><StageDot status={song.lyrics_status} />
      <span>Waveform</span><StageDot status={song.waveform_status} />
    </span>
  );
}

function StageDot({ status }: { status: Song['lyrics_status'] }) {
  const color = { READY: 'bg-ok', PROCESSING: 'bg-warn animate-pulse-glow', PENDING: 'bg-outline', FAILED: 'bg-error' }[status];
  return <span className={`size-1.5 rounded-full ${color}`} title={status} />;
}
