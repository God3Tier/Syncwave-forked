import { useCallback, useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router';
import { listSongs } from '../api/catalogue';
import { browserLocation, getRecommendations, WEATHER_CITIES, type LocationProblem } from '../api/recommendation';
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
const SOURCE_KEY = 'syncwave.weather_source';
const MY_LOCATION = 'location';
const weatherIcon: Record<WeatherCondition, string> = {
  CLEAR: 'clear_day',
  CLOUDY: 'cloud',
  RAIN: 'rainy',
  STORM: 'thunderstorm',
  SNOW: 'weather_snowy',
  FOG: 'foggy',
  OTHER: 'partly_cloudy_day',
};
const locationProblems: Record<LocationProblem, string> = {
  insecure: 'Your browser only shares your location over HTTPS, and this site is served over HTTP.',
  denied: 'Location access is blocked for this site.',
  unavailable: 'Your browser could not find your location.',
};

function readSetting(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function saveSetting(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // per-tab only
  }
}

/** One load of recommendations; `problem` says why the browser gave no location. */
interface Picks {
  result: Recommendations;
  problem: LocationProblem | null;
}

function WeatherToggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  const option = (value: boolean, icon: string, label: string) => (
    <button
      type="button"
      role="radio"
      aria-checked={on === value}
      onClick={() => onChange(value)}
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-mono text-xs transition-colors ${
        on === value ? 'bg-secondary/15 text-secondary shadow-[0_0_12px_rgb(58_223_250/0.12)]' : 'text-on-surface-variant hover:text-on-surface'
      }`}
    >
      <Icon name={icon} className="text-base" />
      {label}
    </button>
  );
  return (
    <div role="radiogroup" aria-label="Recommendations" className="inline-flex rounded-full border border-outline-variant/40 p-0.5">
      {option(false, 'auto_awesome', 'General')}
      {option(true, 'partly_cloudy_day', 'Match weather')}
    </div>
  );
}

function WeatherStatus({ picks, loading }: { picks?: Picks; loading: boolean }) {
  if (loading) return <span className="font-mono text-xs text-on-surface-variant">Checking the weather…</span>;
  if (!picks) return null;
  if (picks.problem) {
    return (
      <span className="text-xs text-warn">
        {locationProblems[picks.problem]} Showing general picks; choose a city to use its weather instead.
      </span>
    );
  }
  const { weather, items } = picks.result;
  if (!picks.result.weather_used || !weather) {
    return <span className="text-xs text-warn">The weather service did not answer, so these are general picks.</span>;
  }
  const matches = items.filter((item) => item.reason === 'WEATHER_MATCH').length;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-2 rounded-full border border-secondary/40 bg-secondary/5 px-3 py-1 font-mono text-xs text-secondary">
        <Icon name={weatherIcon[weather.condition]} className="text-base" />
        {weather.condition.charAt(0) + weather.condition.slice(1).toLowerCase()} · {Math.round(weather.temperature_c)}°C
      </span>
      <span className="text-xs text-on-surface-variant">
        {matches > 0 ? `${matches} song${matches === 1 ? '' : 's'} suit this weather and come first.` : 'No song suits this weather; general picks follow.'}
      </span>
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
  const [useWeather, setUseWeather] = useState(() => readSetting(WEATHER_KEY) === '1');
  const [source, setSource] = useState(() => {
    const saved = readSetting(SOURCE_KEY);
    return saved && saved in WEATHER_CITIES ? saved : MY_LOCATION;
  });

  const recommendations = useAsync(
    async (signal): Promise<Picks> => {
      if (!useWeather) return { result: await getRecommendations(null, 12, signal), problem: null };
      const place = source === MY_LOCATION ? await browserLocation() : WEATHER_CITIES[source];
      if ('problem' in place) return { result: await getRecommendations(null, 12, signal), problem: place.problem };
      return { result: await getRecommendations(place, 12, signal), problem: null };
    },
    [useWeather, source],
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

  const changeWeather = (on: boolean) => {
    saveSetting(WEATHER_KEY, on ? '1' : '0');
    setUseWeather(on);
  };
  const changeSource = (value: string) => {
    saveSetting(SOURCE_KEY, value);
    setSource(value);
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`);
  };

  const picks = recommendations.data?.result;
  const recQueue = picks?.items.map((item) => item.song_id) ?? [];
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
        <SectionTitle aside={<WeatherToggle on={useWeather} onChange={changeWeather} />}>
          For you right now
          <span className="mt-1 block font-body text-sm font-normal text-on-surface-variant">
            {useWeather
              ? 'Songs whose mood suits the current weather come first, marked Weather match.'
              : 'General picks from the catalogue; the weather is not used.'}
          </span>
        </SectionTitle>
        {useWeather && (
          <div className="-mt-1 mb-4 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-xs text-on-surface-variant">
              Weather in
              <select
                value={source}
                onChange={(event) => changeSource(event.target.value)}
                className="rounded-lg border border-outline-variant/40 bg-surface-container-high px-2 py-1 font-mono text-xs text-on-surface focus:border-secondary focus:outline-none"
              >
                <option value={MY_LOCATION}>my location</option>
                {Object.keys(WEATHER_CITIES).map((city) => (
                  <option key={city} value={city}>
                    {city}
                  </option>
                ))}
              </select>
            </label>
            <WeatherStatus picks={recommendations.data} loading={recommendations.loading} />
          </div>
        )}
        {recommendations.loading && !picks && <Spinner label="Finding songs" />}
        {recommendations.error !== undefined && <Notice tone="error">{errorMessage(recommendations.error)}</Notice>}
        {picks && picks.items.length === 0 && <Notice>No playable songs yet. Upload one to get started.</Notice>}
        <div className={`-mx-1 flex gap-4 overflow-x-auto px-1 pb-2 transition-opacity ${recommendations.loading ? 'opacity-50' : ''}`}>
          {picks?.items.map((item) => <RecommendationCard key={item.song_id} item={item} queue={recQueue} />)}
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
