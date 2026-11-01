// Jam room (Scenario 3). Jam owns membership, the shared queue and owner-only
// controls; its WebSocket pushes the full room state after every change. Once
// the owner starts playback, every device also joins the Sync Service's
// WebSocket (SyncSession) which buffers the song and schedules it with PLAY_AT.

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { ApiError } from '../api/http';
import {
  decideReadiness,
  getJam,
  getReadiness,
  jamSocketUrl,
  joinJam,
  leaveJam,
  playback,
  queueSong,
  rememberJam,
  removeQueueItem,
  reorderQueue,
} from '../api/jam';
import { getWaveform } from '../api/media';
import type { Jam, Readiness } from '../api/types';
import { copyText } from '../clipboard';
import { Waveform } from '../components/Waveform';
import { Button, Card, EqualizerIcon, Icon, IconButton, Notice, SongArt, Spinner, StatusChip } from '../components/ui';
import { errorMessage } from '../errors';
import { formatDuration, formatMs, initials, parseTimestamp, shortId } from '../format';
import { useAsync, useInterval } from '../hooks/useAsync';
import { moveItem, useDragReorder } from '../hooks/useDragReorder';
import { useSongs } from '../hooks/useSongs';
import { userId } from '../identity';
import { usePlayer, usePosition } from '../player/context';
import { SyncSession, type SyncSnapshot } from '../sync/syncSession';
import { AddSongsPanel } from './PlaylistDetail';

const JAM_CLOSE_REASONS: Record<number, string> = {
  4401: 'The Jam rejected this device’s token.',
  4403: 'You are no longer a member of this Jam.',
  4404: 'This Jam does not exist.',
};

/** Keeps the Jam state live through the Jam room WebSocket, reconnecting after drops. */
function useJamSocket(jamId: string, enabled: boolean, onJam: (jam: Jam) => void) {
  const [closeCode, setCloseCode] = useState<number | null>(null);
  const onJamRef = useRef(onJam);
  useEffect(() => {
    onJamRef.current = onJam;
  }, [onJam]);

  useEffect(() => {
    if (!enabled) return;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const open = () => {
      socket = new WebSocket(jamSocketUrl(jamId, userId));
      socket.onopen = () => setCloseCode(null);
      socket.onmessage = (event) => onJamRef.current(JSON.parse(String(event.data)) as Jam);
      socket.onclose = (event) => {
        if (stopped) return;
        setCloseCode(event.code);
        if (!JAM_CLOSE_REASONS[event.code]) retry = setTimeout(open, 2000);
      };
    };
    open();
    return () => {
      stopped = true;
      clearTimeout(retry);
      socket?.close(1000);
    };
  }, [jamId, enabled]);

  return closeCode;
}

export function JamRoom() {
  const { jamId = '' } = useParams();
  const navigate = useNavigate();
  const personalPlayer = usePlayer();
  const [jam, setJam] = useState<Jam | null>(null);
  const [loadError, setLoadError] = useState<unknown>();
  const [actionError, setActionError] = useState<unknown>();
  const [audio, setAudio] = useState<AudioContext | null>(null);
  const [sync, setSync] = useState<SyncSnapshot | null>(null);
  const [session, setSession] = useState<SyncSession | null>(null);
  const sessionRef = useRef<SyncSession | null>(null);
  const [copied, setCopied] = useState(false);

  // Opening the room (e.g. from an invite link) joins it; joining is idempotent.
  useEffect(() => {
    const controller = new AbortController();
    joinJam(jamId, userId)
      .then((value) => {
        if (controller.signal.aborted) return;
        setJam(value);
        rememberJam(jamId, value.owner_id === userId);
      })
      .catch((error: unknown) => !controller.signal.aborted && setLoadError(error));
    return () => controller.abort();
  }, [jamId]);

  const member = Boolean(jam?.participant_ids.includes(userId));
  const jamCloseCode = useJamSocket(jamId, member, setJam);
  const owner = jam?.owner_id === userId;
  const active = Boolean(jam && jam.state !== 'IDLE' && jam.sync_generation !== null);

  // One Sync connection per room; reconnect only if it closed (e.g. it was
  // opened before Sync had a session and got rejected).
  useEffect(() => {
    if (!audio || !active || !member) return;
    const current = sessionRef.current;
    if (current && current.state.phase !== 'CLOSED') return;
    current?.close();
    const next = new SyncSession({ jamId, participantId: userId, context: audio, onChange: setSync });
    sessionRef.current = next;
    setSession(next);
    next.connect();
  }, [audio, active, member, jamId, jam?.sync_generation]);

  useEffect(
    () => () => {
      sessionRef.current?.close();
      sessionRef.current = null;
    },
    [],
  );
  useEffect(() => () => void audio?.close(), [audio]);

  const enableAudio = async () => {
    // Browsers only allow audio after a user gesture, so the AudioContext is created here.
    const context = new AudioContext();
    await context.resume();
    personalPlayer.pause();
    setAudio(context);
  };

  const run = async (action: () => Promise<Jam | void>) => {
    setActionError(undefined);
    try {
      const result = await action();
      if (result) setJam(result);
    } catch (error) {
      setActionError(error);
    }
  };

  // Jam reconciles its state with Sync only when GET /jams/{id} is called
  // (then broadcasts it on the room socket), so poll while playback is live.
  useInterval(
    () => {
      void getJam(jamId)
        .then(setJam)
        .catch(() => undefined);
    },
    2000,
    member && jam !== null && jam.state !== 'IDLE' && jam.state !== 'ENDED',
  );

  // The owner is asked to decide when some listeners are not ready in time.
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  useInterval(
    () => {
      void getReadiness(jamId, userId)
        .then(setReadiness)
        .catch(() => setReadiness(null));
    },
    2000,
    owner && jam?.state === 'PREPARING',
  );
  const showReadiness = owner && jam?.state === 'PREPARING' && readiness?.decision_required;

  if (loadError !== undefined && !jam) {
    return (
      <div className="mx-auto max-w-xl p-8">
        <Notice tone="error" action={<Link to="/jam" className="text-sm text-primary">Back</Link>}>
          {loadError instanceof ApiError && loadError.status === 404 ? 'This Jam does not exist.' : errorMessage(loadError)}
        </Notice>
      </div>
    );
  }
  if (!jam) return <div className="p-8"><Spinner label="Joining Jam" /></div>;

  const currentItem = jam.queue.find((item) => item.queue_item_id === jam.current_queue_item_id) ?? null;
  const currentSongId = sync?.songId ?? currentItem?.song_id ?? null;

  const copyInvite = async () => {
    const link = `${window.location.origin}/jam/${jamId}`;
    if (await copyText(link)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } else {
      window.prompt('Copy this invite link', link);
    }
  };
  const leave = async () => {
    sessionRef.current?.close();
    if (!owner) await leaveJam(jamId, userId).catch(() => undefined);
    navigate('/jam');
  };

  return (
    <div className="flex min-h-full flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-outline-variant/20 bg-surface/80 px-4 py-3 backdrop-blur md:px-6">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="font-headline text-lg font-bold">Jam</h1>
          <button type="button" onClick={() => void copyInvite()} title="Copy invite link" className="flex items-center gap-1.5 rounded border border-outline-variant/40 bg-surface-container-high px-2.5 py-1 font-mono text-xs text-secondary">
            {shortId(jamId)} <Icon name="content_copy" className="text-sm text-outline" />
          </button>
          <StatusChip status={owner ? 'OWNER' : 'MEMBER'} />
          <StatusChip status={jam.state} />
        </div>
        <div className="flex items-center gap-2">
          <Button icon={copied ? 'check' : 'link'} onClick={() => void copyInvite()} className="py-1.5 text-xs">
            {copied ? 'Copied' : 'Copy invite link'}
          </Button>
          <Button variant="ghost" icon="logout" onClick={() => void leave()} className="py-1.5 text-xs">
            Leave
          </Button>
        </div>
      </header>

      <div className="space-y-3 px-4 pt-4 md:px-6">
        {jamCloseCode && JAM_CLOSE_REASONS[jamCloseCode] && <Notice tone="error">{JAM_CLOSE_REASONS[jamCloseCode]}</Notice>}
        {jamCloseCode && !JAM_CLOSE_REASONS[jamCloseCode] && <Notice tone="warn">Lost the live room connection. Reconnecting…</Notice>}
        {actionError !== undefined && <Notice tone="error">{errorMessage(actionError)}</Notice>}
        {sync?.error && (
          <Notice tone="error">
            Sync: {sync.error.code} {sync.error.message && `· ${sync.error.message}`}
          </Notice>
        )}
        {!audio && (
          <Notice
            tone="info"
            action={
              <Button variant="primary" icon="volume_up" onClick={() => void enableAudio()} className="py-1.5 text-xs">
                Join Jam (Enable Audio)
              </Button>
            }
          >
            Join to listen: this device then plays in sync with everyone else. Every listener, the owner included, joins before playback.
          </Notice>
        )}
      </div>

      <div className="grid flex-1 gap-5 p-4 md:p-6 lg:grid-cols-12">
        <div className="lg:col-span-4">
          <Deck
            jam={jam}
            owner={owner}
            songId={currentSongId}
            sync={sync}
            session={session}
            onControl={(action, extra) => void run(() => playback(jamId, userId, action, extra))}
          />
        </div>
        <div className="space-y-5 lg:col-span-5">
          <Queue jam={jam} owner={owner} playingSongId={currentSongId} run={run} />
          <AddSongsPanel
            title="Add to the shared queue"
            existing={new Set()}
            onAdd={(songId) => void run(() => queueSong(jamId, userId, songId))}
          />
        </div>
        <div className="space-y-5 lg:col-span-3">
          <Participants jam={jam} sync={sync} readiness={readiness} />
          <SyncStats sync={sync} audioEnabled={Boolean(audio)} />
        </div>
      </div>

      {showReadiness && readiness && (
        <ReadinessModal
          readiness={readiness}
          onDecide={(decision) => void run(() => decideReadiness(jamId, userId, decision)).then(() => setReadiness(null))}
        />
      )}
    </div>
  );
}

type ControlAction = Parameters<typeof playback>[2];

function Deck({
  jam,
  owner,
  songId,
  sync,
  session,
  onControl,
}: {
  jam: Jam;
  owner: boolean;
  songId: string | null;
  sync: SyncSnapshot | null;
  session: SyncSession | null;
  onControl: (action: ControlAction, extra?: { queue_item_id?: string; position_ms?: number }) => void;
}) {
  const songs = useSongs(songId ? [songId] : []);
  const song = songId ? songs.get(songId) : null;
  const waveform = useAsync((signal) => (songId ? getWaveform(songId, 120, signal).catch(() => null) : Promise.resolve(null)), [songId]);
  const getPosition = useCallback(() => session?.positionMs() ?? 0, [session]);
  const position = usePosition(getPosition, sync?.phase === 'PLAYING');
  const durationMs = sync?.mediaMs || song?.duration_ms || 0;
  const [seekText, setSeekText] = useState('');

  const seek = (event: FormEvent) => {
    event.preventDefault();
    const ms = parseTimestamp(seekText);
    if (ms !== null) onControl('seek', { position_ms: ms });
  };

  const playing = jam.state === 'PLAYING' || jam.state === 'SCHEDULED';
  const started = jam.state !== 'IDLE' && jam.state !== 'ENDED';
  const hasNext = jam.queue.findIndex((item) => item.queue_item_id === jam.current_queue_item_id) < jam.queue.length - 1;

  return (
    <Card className="relative h-full overflow-hidden border-primary/25">
      <div className="pointer-events-none absolute -left-24 -top-24 h-48 w-48 rounded-full bg-primary/10 blur-3xl" />
      <div className="mb-4 flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${sync?.phase === 'PLAYING' ? 'animate-pulse-glow bg-secondary' : 'bg-outline'}`} />
        <span className="font-mono text-xs uppercase tracking-wider text-secondary">Synchronised deck</span>
      </div>
      {songId ? <SongArt id={songId} size="lg" className="mx-auto max-w-72" /> : (
        <div className="mx-auto flex aspect-square max-w-72 items-center justify-center rounded-xl border border-dashed border-outline-variant/50 text-on-surface-variant">
          Nothing playing yet
        </div>
      )}
      <div className="mt-4">
        <h2 className="truncate font-headline text-xl font-bold">{song?.title ?? (songId ? '…' : 'Waiting for the owner')}</h2>
        <p className="truncate text-sm text-on-surface-variant">{song?.artist ?? (owner ? 'Start playback from the queue.' : 'Only the owner can control playback.')}</p>
      </div>

      <div className="mt-4">
        <Waveform peaks={waveform.data?.peaks ?? []} durationMs={durationMs} positionMs={position} height={48} />
        <div className="mt-1 flex justify-between font-mono text-xs tabular-nums text-on-surface-variant">
          <span className="text-secondary">{formatDuration(position)}</span>
          <span>{formatDuration(durationMs)}</span>
        </div>
      </div>

      {/* Phones: a large drift read-out (Stitch mobile Jam room). */}
      <div className="mt-4 rounded-xl border border-secondary/30 bg-secondary/5 p-3 text-center lg:hidden">
        <p className="font-mono text-[11px] uppercase text-secondary">{sync?.phase === 'PLAYING' ? 'In sync' : sync?.phase ?? 'Not connected'}</p>
        <p className="font-mono text-3xl font-semibold tabular-nums">{formatMs(sync?.lastDriftMs ?? sync?.startErrorMs ?? null)}</p>
        <p className="font-mono text-[11px] text-on-surface-variant">
          offset {formatMs(sync?.offsetMs, 1)} · rtt {formatMs(sync?.rttMs)}
        </p>
      </div>

      {owner ? (
        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-outline-variant/20 pt-4">
          <button
            type="button"
            onClick={() => (!started ? onControl('start') : playing ? onControl('pause') : onControl('resume'))}
            disabled={!jam.queue.length || jam.state === 'PREPARING'}
            aria-label={!started ? 'Start' : playing ? 'Pause' : 'Resume'}
            className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary text-on-primary shadow-lg shadow-primary/30 disabled:opacity-50"
          >
            <Icon name={playing ? 'pause' : 'play_arrow'} fill className="text-2xl" />
          </button>
          <IconButton icon="skip_next" label="Skip to next" onClick={() => onControl('skip')} disabled={!started || !hasNext} className="h-10 w-10 border border-outline-variant/30" />
          <form onSubmit={seek} className="ml-auto flex items-center gap-1.5 rounded-lg border border-outline-variant/30 bg-surface-container px-2 py-1.5">
            <span className="font-mono text-[10px] uppercase text-outline">Seek</span>
            <input
              value={seekText}
              onChange={(event) => setSeekText(event.target.value)}
              placeholder="01:30"
              aria-label="Seek to (mm:ss)"
              className="w-14 rounded border border-outline-variant/40 bg-surface-container-lowest px-1.5 py-0.5 text-center font-mono text-xs focus:border-secondary focus:outline-none"
            />
            <button type="submit" disabled={!started} className="rounded bg-surface-container-highest px-2 py-0.5 font-mono text-[11px] hover:text-secondary disabled:opacity-40">
              Go
            </button>
          </form>
        </div>
      ) : (
        <p className="mt-5 border-t border-outline-variant/20 pt-4 font-mono text-[11px] text-outline">Only the owner can control playback.</p>
      )}
      <p className="mt-4 truncate font-mono text-[10px] text-outline">
        Generation {jam.sync_generation ?? '—'} · target {sync?.targetServerMs ? new Date(sync.targetServerMs).toISOString().slice(11, 23) : '—'}
      </p>
    </Card>
  );
}

function Queue({ jam, owner, playingSongId, run }: { jam: Jam; owner: boolean; playingSongId: string | null; run: (action: () => Promise<Jam | void>) => Promise<void> }) {
  const songs = useSongs(jam.queue.map((item) => item.song_id));
  const ids = jam.queue.map((item) => item.queue_item_id);
  const drag = useDragReorder((from, to) => void run(() => reorderQueue(jam.jam_id, userId, moveItem(ids, from, to))), owner);

  return (
    <Card>
      <div className="mb-3 flex items-center justify-between">
        <h3 className="font-headline text-base font-bold">
          Shared queue <span className="font-mono text-xs font-normal text-secondary">({jam.queue.length})</span>
        </h3>
      </div>
      {jam.queue.length === 0 && <p className="py-6 text-center text-sm text-on-surface-variant">The queue is empty. Add a song below.</p>}
      <ol className="space-y-2">
        {jam.queue.map((item, i) => {
          const song = songs.get(item.song_id);
          const current = item.queue_item_id === jam.current_queue_item_id;
          return (
            <li key={item.queue_item_id} {...drag.rowProps(i)} className={`relative ${drag.dragging === i ? 'opacity-40' : ''}`}>
              {drag.gap === i && <span className="absolute inset-x-2 -top-1.5 h-0.5 rounded-full bg-primary" />}
              <div className={`group flex items-center gap-3 rounded-xl border p-2.5 ${current ? 'border-primary/40 bg-surface-container-high' : 'border-outline-variant/20 bg-surface-container'}`}>
                {owner && <Icon name="drag_indicator" className="cursor-grab text-base text-outline" />}
                <SongArt id={item.song_id} size="sm" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <p className="truncate font-headline text-sm font-semibold">{song?.title ?? '…'}</p>
                    {current && playingSongId === item.song_id && <EqualizerIcon />}
                  </div>
                  <p className="truncate text-xs text-on-surface-variant">{song?.artist ?? ''}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-outline">
                    added by {item.added_by === userId ? 'you' : shortId(item.added_by)} · {formatDuration(song?.duration_ms)}
                  </p>
                </div>
                {owner && (
                  <div className="flex items-center">
                    <IconButton
                      icon="play_circle"
                      label={jam.state === 'PREPARING' ? 'Wait until the current song is ready' : 'Play this now'}
                      disabled={jam.state === 'PREPARING'}
                      onClick={() => void run(() => playback(jam.jam_id, userId, 'start', { queue_item_id: item.queue_item_id }))}
                      className="disabled:cursor-not-allowed"
                    />
                    {!current && <IconButton icon="close" label="Remove from queue" onClick={() => void run(() => removeQueueItem(jam.jam_id, userId, item.queue_item_id))} />}
                  </div>
                )}
              </div>
              {drag.gap === jam.queue.length && i === jam.queue.length - 1 && <span className="absolute inset-x-2 -bottom-1.5 h-0.5 rounded-full bg-primary" />}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

function Participants({ jam, sync, readiness }: { jam: Jam; sync: SyncSnapshot | null; readiness: Readiness | null }) {
  return (
    <Card className="p-4">
      <h4 className="mb-3 flex items-center gap-1.5 font-headline text-xs font-bold uppercase tracking-wider">
        <Icon name="group" className="text-base text-secondary" /> Participants ({jam.participant_ids.length})
      </h4>
      <ul className="space-y-2">
        {jam.participant_ids.map((id) => {
          const state = sync?.participants[id];
          const ready = state?.ready ?? readiness?.ready_participant_ids.includes(id) ?? false;
          // Sync only reports others' presence on changes; this device knows its own socket state.
          const connected = state?.connected ?? (id === userId && Boolean(sync) && sync?.phase !== 'CONNECTING' && sync?.phase !== 'CLOSED');
          return (
            <li key={id} className="flex items-center justify-between gap-2 rounded-lg border border-outline-variant/20 bg-surface-container p-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-primary/40 bg-primary/15 font-mono text-[10px] font-bold text-primary">{initials(id)}</span>
                <span className="truncate font-mono text-xs">{shortId(id)}</span>
                {id === userId && <span className="rounded bg-secondary/15 px-1 font-mono text-[9px] uppercase text-secondary">you</span>}
                {id === jam.owner_id && <span className="rounded bg-primary/20 px-1 font-mono text-[9px] uppercase text-primary">owner</span>}
              </div>
              <div className="flex items-center gap-2 font-mono text-[10px]">
                <span className="flex items-center gap-1" title="Connected to Sync">
                  <span className={`h-2 w-2 rounded-full ${connected ? 'bg-ok' : 'bg-outline-variant'}`} />
                </span>
                <span className="flex items-center gap-1" title="Buffered and ready">
                  <span className={`h-2 w-2 rounded-full ${ready ? 'bg-secondary shadow-[0_0_6px_#48e4ff]' : 'bg-outline-variant'}`} />
                </span>
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 flex gap-3 font-mono text-[10px] text-outline">
        <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-ok" /> connected</span>
        <span className="flex items-center gap-1"><span className="h-1.5 w-1.5 rounded-full bg-secondary" /> ready</span>
      </p>
    </Card>
  );
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const max = Math.max(50, ...values.map(Math.abs));
  const points = values.map((v, i) => `${(i / (values.length - 1)) * 48},${8 - (v / max) * 7}`).join(' ');
  return (
    <svg viewBox="0 0 48 16" className="h-4 w-12 overflow-visible" aria-hidden="true">
      <line x1="0" y1="8" x2="48" y2="8" stroke="#484750" strokeWidth="0.5" />
      <polyline points={points} fill="none" stroke="#3adffa" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function SyncStats({ sync, audioEnabled }: { sync: SyncSnapshot | null; audioEnabled: boolean }) {
  const rows: [string, string][] = [
    ['Phase', sync?.phase ?? (audioEnabled ? 'waiting for playback' : 'audio not enabled')],
    ['Clock offset', formatMs(sync?.offsetMs, 1)],
    ['Round-trip', sync?.rttMs !== null && sync?.rttMs !== undefined ? `${sync.rttMs.toFixed(0)} ms` : '—'],
    ['Start error', formatMs(sync?.startErrorMs)],
    ['Buffered', sync?.mediaMs ? `${formatDuration(sync.bufferedMs)} / ${formatDuration(sync.mediaMs)}` : '—'],
    ['Last correction', sync?.lastCorrection ? `${sync.lastCorrection.method}${sync.lastCorrection.method === 'RATE' ? ` ${sync.lastCorrection.rate.toFixed(2)}×` : ''} (${formatMs(sync.lastCorrection.driftMs)})` : 'none'],
    ['Samples', sync ? String(sync.samples) : '—'],
  ];
  return (
    <Card className="p-4">
      <h4 className="mb-2.5 flex items-center gap-1.5 font-headline text-xs font-bold uppercase tracking-wider">
        <Icon name="query_stats" className="text-base text-primary" /> Sync stats
      </h4>
      <dl className="space-y-1 font-mono text-xs tabular-nums">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between gap-2 border-b border-outline-variant/15 py-1 last:border-0">
            <dt className="text-[11px] text-outline">{label}</dt>
            <dd className="text-right text-on-surface">{value}</dd>
          </div>
        ))}
        <div className="flex items-center justify-between gap-2 py-1">
          <dt className="text-[11px] text-outline">Drift</dt>
          <dd className="flex items-center gap-2">
            <span className="text-tertiary">{formatMs(sync?.lastDriftMs)}</span>
            <Sparkline values={sync?.driftHistory ?? []} />
          </dd>
        </div>
      </dl>
      <p className="mt-2 text-[10px] text-outline">Drift is reported by Sync when it corrects this device.</p>
    </Card>
  );
}

function ReadinessModal({ readiness, onDecide }: { readiness: Readiness; onDecide: (decision: 'CONTINUE' | 'WAIT' | 'CANCEL') => void }) {
  const count = readiness.unready_participant_ids.length;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-md" role="dialog" aria-modal="true" aria-labelledby="readiness-title">
      <div className="w-full max-w-md rounded-2xl border border-primary/40 bg-surface-container p-6 shadow-2xl shadow-black/80">
        <div className="mb-4 flex items-start gap-4">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-tertiary/40 bg-tertiary/10 text-tertiary">
            <Icon name="sync_problem" className="text-2xl" />
          </div>
          <div>
            <h3 id="readiness-title" className="font-headline text-lg font-bold">
              {count} listener{count === 1 ? " isn't" : "s aren't"} ready
            </h3>
            <p className="mt-1 text-xs text-on-surface-variant">Preparation timed out. Decide how to continue.</p>
          </div>
        </div>
        <ul className="my-5 space-y-2 rounded-xl border border-outline-variant/30 bg-surface-container-low p-3">
          {readiness.unready_participant_ids.map((id) => (
            <li key={id} className="flex items-center gap-2 font-mono text-xs">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-tertiary/20 text-[9px] font-bold text-tertiary">{initials(id)}</span>
              {shortId(id)} {id === userId && '(you)'}
            </li>
          ))}
        </ul>
        <div className="space-y-2">
          <Button variant="primary" onClick={() => onDecide('CONTINUE')} className="w-full">
            Continue without them
          </Button>
          <div className="grid grid-cols-2 gap-2">
            <Button onClick={() => onDecide('WAIT')}>Keep waiting</Button>
            <Button variant="danger" onClick={() => onDecide('CANCEL')}>
              Cancel playback
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
