import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { Link } from 'react-router';
import { getSong } from '../api/catalogue';
import { ApiError } from '../api/http';
import { getUpload, MOODS, type Mood, uploadSong } from '../api/upload';
import type { Song, StageStatus, UploadReceipt } from '../api/types';
import { Page } from '../components/Layout';
import { Button, Card, Icon, Notice, StatusChip } from '../components/ui';
import { errorMessage } from '../errors';
import { relativeTime } from '../format';
import { useInterval } from '../hooks/useAsync';
import { rememberSong } from '../hooks/useSongs';

const RECENT_KEY = 'syncwave.recent_uploads';

interface RecentUpload {
  song_id: string;
  title: string;
  artist: string;
  at: string;
}

function loadRecent(): RecentUpload[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]') as RecentUpload[];
  } catch {
    return [];
  }
}

function saveRecent(item: RecentUpload): RecentUpload[] {
  const next = [item, ...loadRecent().filter((r) => r.song_id !== item.song_id)].slice(0, 6);
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // ignore
  }
  return next;
}

function FileDrop({ label, hint, accept, file, onFile, required }: { label: string; hint: string; accept: string; file: File | null; onFile: (file: File | null) => void; required?: boolean }) {
  const [over, setOver] = useState(false);
  return (
    <label
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setOver(false);
        onFile(event.dataTransfer.files[0] ?? null);
      }}
      className={`flex min-h-32 cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border border-dashed px-4 py-6 text-center transition-colors ${
        over ? 'border-primary bg-primary/5' : file ? 'border-secondary/50 bg-secondary/5' : 'border-outline-variant/50 hover:border-outline'
      }`}
    >
      <Icon name={file ? 'check_circle' : 'graphic_eq'} className={`text-3xl ${file ? 'text-secondary' : 'text-primary'}`} />
      <span className="font-headline text-sm font-semibold">{file ? file.name : label}</span>
      <span className="font-mono text-[11px] text-on-surface-variant">{file ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : hint}</span>
      <input type="file" accept={accept} required={required && !file} className="sr-only" onChange={(event) => onFile(event.target.files?.[0] ?? null)} />
    </label>
  );
}

const inputClass = 'min-h-11 w-full rounded-xl bg-surface-container px-3 py-2.5 text-sm ring-1 ring-outline-variant/45 placeholder:text-outline focus:ring-secondary focus:outline-none';

/** Upload & Process (Scenario 2): the form plus a live view of the choreography. */
export function Upload() {
  const [title, setTitle] = useState('');
  const [artist, setArtist] = useState('');
  const [audio, setAudio] = useState<File | null>(null);
  const [lyrics, setLyrics] = useState<File | null>(null);
  const [duration, setDuration] = useState('');
  const [mood, setMood] = useState<Mood | ''>('');
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<unknown>();
  const [receipt, setReceipt] = useState<UploadReceipt | null>(null);
  const [recent, setRecent] = useState(loadRecent);
  const [trackedId, setTrackedId] = useState<string | null>(() => loadRecent()[0]?.song_id ?? null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!audio) return;
    setError(undefined);
    setProgress(0);
    try {
      const result = await uploadSong(
        { title: title.trim(), artist: artist.trim(), audio, lyrics, durationMs: duration ? Number(duration) : null, mood: mood || null },
        setProgress,
      );
      setReceipt(result);
      setTrackedId(result.song_id);
      setRecent(saveRecent({ song_id: result.song_id, title: result.title, artist: result.artist, at: result.created_at }));
      setTitle('');
      setArtist('');
      setAudio(null);
      setLyrics(null);
      setDuration('');
      setMood('');
    } catch (cause) {
      setError(cause);
    } finally {
      setProgress(null);
    }
  };

  const uploadUnavailable = error instanceof ApiError && (error.unavailable || error.status === 404);

  return (
    <Page wide>
      <header className="mb-8 border-b border-outline-variant/35 pb-7">
        <h1 className="text-3xl font-extrabold tracking-[-0.035em]">Bring your own track</h1>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-on-surface-variant">Add audio to the shared catalogue. SyncWave prepares timed lyrics and a waveform in the background.</p>
      </header>
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(22rem,0.95fr)]">
        <Card className="p-6">
          <h2 className="mb-5 text-lg font-extrabold">Track details</h2>
          <form onSubmit={(event) => void submit(event)} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-on-surface-variant">Title</span>
                <input required name="title" autoComplete="off" maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} className={inputClass} placeholder="Midnight Run" />
              </label>
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-on-surface-variant">Artist</span>
                <input required name="artist" autoComplete="off" maxLength={200} value={artist} onChange={(e) => setArtist(e.target.value)} className={inputClass} placeholder="Velvet Synth" />
              </label>
            </div>
            <FileDrop label="Drop an audio file or browse" hint="MP3, WAV, FLAC or OGG · up to 200 MB" accept="audio/*,.mp3,.wav,.flac,.ogg" file={audio} onFile={setAudio} required />
            <FileDrop label="Lyrics (optional)" hint=".lrc timestamped lyrics" accept=".lrc,text/plain" file={lyrics} onFile={setLyrics} />
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-on-surface-variant">Mood (optional)</span>
                <select name="mood" autoComplete="off" value={mood} onChange={(e) => setMood(e.target.value as Mood | '')} className={inputClass}>
                  <option value="">No mood</option>
                  {MOODS.map((m) => (
                    <option key={m} value={m}>
                      {m[0].toUpperCase() + m.slice(1)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1.5">
                <span className="text-xs font-medium text-on-surface-variant">Duration in ms (optional)</span>
                <input type="number" name="duration-ms" autoComplete="off" min={1} value={duration} onChange={(e) => setDuration(e.target.value)} className={inputClass} placeholder="Measured automatically if blank" />
              </label>
            </div>
            <p className="-mt-2 text-xs text-on-surface-variant">Recommendations put songs whose mood suits the listener's weather first.</p>
            <Button type="submit" variant="primary" icon="upload" disabled={!audio || progress !== null} className="w-full py-3">
              {progress !== null ? `Uploading… ${Math.round(progress * 100)}%` : 'Upload & process'}
            </Button>
            {progress !== null && (
              <div className="h-1.5 overflow-hidden rounded-full bg-surface-container-highest">
                <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${progress * 100}%` }} />
              </div>
            )}
            {error !== undefined && (
              <Notice tone="error">
                {uploadUnavailable ? 'The Upload service is not reachable right now, so songs cannot be uploaded. Try again shortly.' : errorMessage(error)}
              </Notice>
            )}
            {receipt && <Notice>Uploaded “{receipt.title}”. Processing has started.</Notice>}
          </form>
        </Card>

        <div className="space-y-6">
          {trackedId ? <ProcessingCard key={trackedId} songId={trackedId} /> : (
            <Card>
              <h2 className="text-lg font-extrabold">Processing</h2>
              <p className="mt-2 text-sm text-on-surface-variant">After an upload, its lyrics and waveform are processed here in parallel.</p>
            </Card>
          )}
          {recent.length > 0 && (
            <Card>
              <h2 className="mb-3 text-base font-extrabold">Recent uploads</h2>
              <ul className="space-y-1">
                {recent.map((item) => (
                  <li key={item.song_id}>
                    <button
                      type="button"
                      onClick={() => setTrackedId(item.song_id)}
                      className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-container-high ${trackedId === item.song_id ? 'bg-surface-container-high' : ''}`}
                    >
                      <span className="truncate">
                        {item.title} <span className="text-on-surface-variant">· {item.artist}</span>
                      </span>
                      <span className="font-mono text-[11px] text-outline">{relativeTime(item.at)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </Page>
  );
}

type Step = 'done' | 'active' | 'failed' | 'waiting';

function TimelineStep({ state, title, detail, children }: { state: Step; title: string; detail?: ReactNode; children?: ReactNode }) {
  const dot = {
    done: 'bg-ok/15 text-ok border-ok/40',
    active: 'bg-warn/15 text-warn border-warn/40 animate-pulse-glow',
    failed: 'bg-error/15 text-error border-error/40',
    waiting: 'bg-surface-container-highest text-outline border-outline-variant/40',
  }[state];
  const icon = { done: 'check', active: 'sync', failed: 'close', waiting: 'more_horiz' }[state];
  return (
    <li className="relative flex gap-4 pb-6 last:pb-0">
      <span className={`z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border ${dot}`}>
        <Icon name={icon} className="text-base" />
      </span>
      <div className="min-w-0 flex-1 pt-1">
        <p className="font-headline text-sm font-semibold">{title}</p>
        {detail && <div className="mt-0.5 font-mono text-[11px] text-on-surface-variant">{detail}</div>}
        {children}
      </div>
    </li>
  );
}

/**
 * Polls Upload and Catalogue to show SongUploaded → Lyrics ∥ Waveform → Catalogue.
 * Rendered with key={songId}, so switching songs starts from a fresh state.
 */
function ProcessingCard({ songId }: { songId: string }) {
  const [upload, setUpload] = useState<UploadReceipt | null>(null);
  const [song, setSong] = useState<Song | null>(null);
  const settled = song && song.processing_status !== 'PROCESSING';

  const poll = useCallback(() => {
    // The Catalogue only knows the song once it has consumed SongUploaded, so 404s are expected at first.
    void getUpload(songId).then(setUpload).catch(() => undefined);
    void getSong(songId)
      .then((value) => {
        rememberSong(value);
        setSong(value);
      })
      .catch(() => undefined);
  }, [songId]);
  useEffect(poll, [poll]);
  useInterval(poll, 2000, !settled);

  const published = Boolean(upload?.published_at) || Boolean(song);
  return (
    <Card>
      <div className="mb-5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-headline text-lg font-semibold">Processing</h2>
          <p className="truncate text-sm text-on-surface-variant">{song?.title ?? upload?.title ?? songId}</p>
        </div>
        {song && <StatusChip status={song.processing_status} />}
      </div>
      <ol className="relative before:absolute before:bottom-4 before:left-4 before:top-4 before:w-px before:bg-outline-variant/40">
        <TimelineStep state={upload || song ? 'done' : 'active'} title="Uploaded to storage" detail={upload ? new Date(upload.created_at).toLocaleTimeString() : 'waiting for the Upload service'} />
        <TimelineStep
          state={published ? 'done' : upload?.last_error_code ? 'failed' : 'active'}
          title="SongUploaded event published"
          detail={upload?.published_at ? new Date(upload.published_at).toLocaleTimeString() : upload?.last_error_code ?? (upload ? `attempts: ${upload.publish_attempts}` : undefined)}
        />
        <li className="relative pb-6">
          <div className="ml-12 grid gap-3 sm:grid-cols-2">
            <Lane name="Lyrics service" status={song?.lyrics_status} />
            <Lane name="Waveform service" status={song?.waveform_status} />
          </div>
        </li>
        <TimelineStep
          state={song?.processing_status === 'READY' ? 'done' : song?.processing_status === 'FAILED' ? 'failed' : song?.processing_status === 'PARTIAL' ? 'failed' : 'waiting'}
          title="Catalogue updated"
          detail={song ? `processing_status = ${song.processing_status}` : 'waiting for the catalogue'}
        />
      </ol>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-outline-variant/20 pt-4">
        <p className="text-xs text-on-surface-variant">Lyrics and waveform run independently and in parallel.</p>
        {song && (song.processing_status === 'READY' || song.processing_status === 'PARTIAL') ? (
          <Link to={`/songs/${songId}`} className="inline-flex items-center gap-1.5 font-headline text-sm font-semibold text-primary">
            Open song page <Icon name="arrow_forward" className="text-base" />
          </Link>
        ) : (
          <span className="font-headline text-sm text-outline">Open song page</span>
        )}
      </div>
    </Card>
  );
}

function Lane({ name, status }: { name: string; status: StageStatus | undefined }) {
  return (
    <div className="rounded-xl border border-outline-variant/30 bg-surface-container p-3">
      <p className="mb-2 font-headline text-sm font-semibold">{name}</p>
      <StatusChip status={status ?? 'PENDING'} />
    </div>
  );
}
