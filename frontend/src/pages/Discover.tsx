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

function WeatherChip({ data, onEnable, enabled }: { data?: Recommendations; onEnable: () => void; enabled: boolean }) {
  if (data?.weather_used && data.weather) {
    const { condition, temperature_c } = data.weather;
    return (
      <span className="inline-flex items-center gap-2 rounded-full border border-secondary/40 bg-secondary/5 px-4 py-1.5 font-mono text-xs text-secondary shadow-[0_0_16px_rgb(58_223_250/0.12)]">
        <Icon name={weatherIcon[condition]} className="text-base" />
        {condition.charAt(0) + condition.slice(1).toLowerCase()} · {Math.round(temperature_c)}°C · weather-matched
      </span>
    );
  }
  if (!enabled) {
    return (
      <Button variant="cyan" icon="my_location" onClick={onEnable} className="rounded-full py-1.5 text-xs">
        Match my weather
      </Button>
    );
  }
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-outline-variant/40 px-4 py-1.5 font-mono text-xs text-on-surface-variant">
      <Icon name="auto_awesome" className="text-base" />
      General picks
    </span>
  );
}

function RecommendationCard({ item, queue }: { item: Recommendation; queue: string[] }) {
  const player = usePlayer();
  const current = player.currentId === item.song_id;
  return (
    <div className="group flex w-44 shrink-0 flex-col gap-3 rounded-xl border border-outline-variant/30 bg-surface-container-low p-3 transition-colors hover:border-primary/40 md:w-48">
      <div className="relative">
        <SongArt id={item.song_id} size="lg" />
        <button
          type="button"
          onClick={() => (current ? player.toggle() : player.playQueue(queue, queue.indexOf(item.song_id)))}
          aria-label={`Play ${item.title}`}
          className={`absolute bottom-2 right-2 flex h-11 w-11 items-center justify-center rounded-full bg-primary text-on-primary shadow-xl shadow-black/50 transition-all ${current ? 'opacity-100' : 'translate-y-1 opacity-0 group-hover:translate-y-0 group-hover:opacity-100 focus:opacity-100'}`}
        >
          <Icon name={current && player.playing ? 'pause' : 'play_arrow'} fill className="text-2xl" />
        </button>
      </div>
      <Link to={`/songs/${item.song_id}`} className="min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <p className="truncate font-headline text-sm font-semibold">{item.title}</p>
          <span className="font-mono text-[11px] text-on-surface-variant">{formatDuration(item.duration_ms)}</span>
        </div>
        <p className="truncate text-xs text-on-surface-variant">{item.artist}</p>
      </Link>
      <span
        className={`self-start rounded-full border px-2 py-0.5 font-mono text-[10px] ${
          item.reason === 'WEATHER_MATCH' ? 'border-secondary/40 bg-secondary/10 text-secondary' : 'border-outline-variant/40 text-on-surface-variant'
        }`}
      >
        {item.reason === 'WEATHER_MATCH' ? 'Weather match' : 'General'}
      </span>
    </div>
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
      // per-tab only
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
      <form onSubmit={submit} className="relative mb-10 max-w-3xl">
        <Icon name="search" className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-2xl text-outline" />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search songs or artists"
          aria-label="Search songs or artists"
          className="w-full rounded-xl border border-outline-variant/40 bg-surface-container-low py-4 pl-14 pr-4 text-base placeholder:text-outline focus:border-primary focus:outline-none"
        />
      </form>

      <section className="mb-12">
        <SectionTitle aside={<WeatherChip data={recommendations.data} enabled={useWeather} onEnable={enableWeather} />}>
          For you right now
          <span className="mt-1 block font-body text-sm font-normal text-on-surface-variant">
            Recommendations from the catalogue, using your local weather when you allow it.
          </span>
        </SectionTitle>
        {recommendations.loading && <Spinner label="Finding songs" />}
        {recommendations.error !== undefined && <Notice tone="error">{errorMessage(recommendations.error)}</Notice>}
        {recommendations.data && recommendations.data.items.length === 0 && (
          <Notice>No playable songs yet. Upload one to get started.</Notice>
        )}
        <div className="-mx-1 flex gap-4 overflow-x-auto px-1 pb-2">
          {recommendations.data?.items.map((item) => <RecommendationCard key={item.song_id} item={item} queue={recQueue} />)}
        </div>
      </section>

      <section>
        <SectionTitle aside={<span className="font-mono text-xs text-outline">{songs.length} songs loaded</span>}>Recently added</SectionTitle>
        {recent.loading && <Spinner label="Loading catalogue" />}
        {recent.error !== undefined && <Notice tone="error">{errorMessage(recent.error)}</Notice>}
        {!recent.loading && songs.length === 0 && recent.error === undefined && (
          <Notice action={<Link to="/upload" className="font-headline text-sm text-primary">Upload</Link>}>The catalogue is empty.</Notice>
        )}
        {songs.length > 0 && (
          <div className="rounded-xl border border-outline-variant/30 bg-surface-container-low p-2">
            <div className="hidden grid-cols-[2rem_minmax(0,1fr)_5rem_7rem_auto] gap-3 px-3 py-2 font-mono text-[11px] uppercase tracking-wider text-outline md:grid">
              <span>#</span>
              <span>Track</span>
              <span>Duration</span>
              <span>Status</span>
              <span className="text-right">Lyrics · Waveform</span>
            </div>
            <ul>
              {songs.map((song, i) => (
                <SongRow key={song.song_id} song={song} index={i} queue={playable} actions={<StageChips song={song} />} />
              ))}
            </ul>
          </div>
        )}
        {cursor && (
          <div className="mt-4 flex justify-center">
            <Button onClick={() => void loadMore()} disabled={loadingMore} icon="expand_more">
              {loadingMore ? 'Loading…' : 'Load more'}
            </Button>
          </div>
        )}
      </section>
    </Page>
  );
}

function StageChips({ song }: { song: Song }) {
  return (
    <span className="mr-2 hidden items-center gap-1.5 font-mono text-[10px] lg:flex" title="Lyrics and waveform processing">
      <span className="text-outline">LYR</span>
      <StageDot status={song.lyrics_status} />
      <span className="ml-1 text-outline">WAV</span>
      <StageDot status={song.waveform_status} />
    </span>
  );
}

function StageDot({ status }: { status: Song['lyrics_status'] }) {
  const color = { READY: 'bg-ok', PROCESSING: 'bg-warn animate-pulse-glow', PENDING: 'bg-outline', FAILED: 'bg-error' }[status];
  return <span className={`h-2 w-2 rounded-full ${color}`} title={status} />;
}
