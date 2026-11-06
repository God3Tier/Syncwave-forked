import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import { useAuth } from '../auth/AuthProvider';
import {
  getJam,
  getReadiness,
  jamMemberId,
  jamSocketUrl,
  joinJam,
  leaveJam,
  playback,
  rememberJam,
  transferAndLeave,
} from '../api/jam';
import type { Jam, Readiness } from '../api/types';
import { useInterval } from '../hooks/useAsync';
import { usePlayer } from '../player/context';
import { SyncSession, type LocalAudioState, type SyncSnapshot } from '../sync/syncSession';

const HEARTBEAT_MS = 30_000;

type ControlAction = Parameters<typeof playback>[1];

/** App-wide state for the one Jam this browser tab is actively listening to. */
export interface JamSessionValue {
  readonly jamId: string | null;
  readonly jam: Jam | null;
  readonly participantId: string | null;
  readonly member: boolean;
  readonly owner: boolean;
  readonly audioEnabled: boolean;
  readonly localAudioState: LocalAudioState;
  readonly sync: SyncSnapshot | null;
  readonly session: SyncSession | null;
  readonly readiness: Readiness | null;
  readonly closeCode: number | null;
  readonly loadError: unknown;
  readonly actionError: unknown;
  readonly volume: number;
  activateJam: (jamId: string) => void;
  adoptJam: (jam: Jam) => void;
  enableAudio: () => Promise<void>;
  run: (action: () => Promise<Jam | void>) => Promise<void>;
  control: (action: ControlAction, extra?: { queue_item_id?: string; position_ms?: number }) => Promise<void>;
  leaveCurrent: () => Promise<void>;
  transferAndLeaveCurrent: (participantId: string) => Promise<void>;
  positionMs: () => number;
  analyser: () => AnalyserNode | null;
  setVolume: (value: number) => void;
}

const JamSessionContext = createContext<JamSessionValue | null>(null);

function useJamSocket(
  jamId: string | null,
  participantId: string | null,
  enabled: boolean,
  onJam: (jam: Jam) => void,
): number | null {
  const [closeCode, setCloseCode] = useState<number | null>(null);
  const onJamRef = useRef(onJam);
  useEffect(() => {
    onJamRef.current = onJam;
  }, [onJam]);

  useEffect(() => {
    if (!enabled || !participantId || !jamId) return;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let heartbeat: ReturnType<typeof setInterval> | undefined;
    let stopped = false;
    const sendHeartbeat = () => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'HEARTBEAT' }));
    };
    const open = () => {
      socket = new WebSocket(jamSocketUrl(jamId, participantId));
      socket.onopen = () => {
        setCloseCode(null);
        sendHeartbeat();
        heartbeat = setInterval(sendHeartbeat, HEARTBEAT_MS);
      };
      socket.onmessage = (event) => {
        const value: unknown = JSON.parse(String(event.data));
        if (typeof value === 'object' && value !== null && 'jam_id' in value) {
          // SAFETY: The Jam HTTP/WebSocket adapter owns this protocol boundary. The
          // server sends the same strict JamResponse shape used by the HTTP client.
          onJamRef.current(value as Jam);
        }
      };
      socket.onclose = (event) => {
        clearInterval(heartbeat);
        if (stopped) return;
        setCloseCode(event.code);
        if (![4401, 4403, 4404, 4408].includes(event.code)) retry = setTimeout(open, 2000);
      };
    };
    open();
    return () => {
      stopped = true;
      clearTimeout(retry);
      clearInterval(heartbeat);
      socket?.close(1000);
    };
  }, [enabled, jamId, participantId]);

  return closeCode;
}

/** Keeps Jam membership, synchronization and audio alive across route changes. */
export function JamProvider({ children }: { readonly children: ReactNode }) {
  const { account, loading: authLoading } = useAuth();
  const personalPlayer = usePlayer();
  const [jamId, setJamId] = useState<string | null>(null);
  const [jam, setJam] = useState<Jam | null>(null);
  const [participantId, setParticipantId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<unknown>();
  const [actionError, setActionError] = useState<unknown>();
  const [audio, setAudio] = useState<AudioContext | null>(null);
  const [sync, setSync] = useState<SyncSnapshot | null>(null);
  const [session, setSession] = useState<SyncSession | null>(null);
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [volume, setVolumeState] = useState(0.8);
  const sessionRef = useRef<SyncSession | null>(null);
  const activeJamIdRef = useRef<string | null>(null);

  const activateJam = useCallback((nextJamId: string) => {
    if (activeJamIdRef.current === nextJamId) return;
    activeJamIdRef.current = nextJamId;
    sessionRef.current?.close();
    sessionRef.current = null;
    setSession(null);
    setSync(null);
    setReadiness(null);
    setJam(null);
    setParticipantId(null);
    setLoadError(undefined);
    setActionError(undefined);
    setJamId(nextJamId);
  }, []);

  const adoptJam = useCallback((value: Jam) => {
    activateJam(value.jam_id);
    const joinedAs = value.member_id ?? account?.id ?? jamMemberId(value.jam_id, account?.id);
    setParticipantId(joinedAs);
    setJam(value);
    rememberJam(value.jam_id, value.owner_id === joinedAs);
  }, [account?.id, activateJam]);

  useEffect(() => {
    if (!jamId || authLoading || jam?.jam_id === jamId) return;
    const controller = new AbortController();
    const knownMember = jamMemberId(jamId, account?.id);
    (knownMember ? getJam(jamId, controller.signal) : joinJam(jamId))
      .then((value) => {
        if (controller.signal.aborted) return;
        const joinedAs = value.member_id ?? account?.id ?? knownMember;
        setParticipantId(joinedAs);
        setJam(value);
        rememberJam(jamId, value.owner_id === joinedAs);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoadError(error);
      });
    return () => controller.abort();
  }, [account?.id, authLoading, jam, jamId]);

  const member = Boolean(participantId && jam?.participant_ids.includes(participantId));
  const owner = Boolean(account && jam?.owner_id === account.id);
  const live = Boolean(jam && jam.lifecycle_state === 'ACTIVE');
  const closeCode = useJamSocket(jamId, participantId, member && live, setJam);
  const synchronized = Boolean(jam && jam.state !== 'IDLE' && jam.sync_generation !== null);

  useEffect(() => {
    if (!audio || !synchronized || !member || !jamId || !participantId) return;
    const current = sessionRef.current;
    if (current && current.state.phase !== 'CLOSED') return;
    current?.close();
    const next = new SyncSession({ jamId, participantId, context: audio, onChange: setSync });
    next.setVolume(volume);
    sessionRef.current = next;
    queueMicrotask(() => setSession(next));
    next.connect();
  }, [audio, jam?.sync_generation, jamId, member, participantId, sync?.phase, synchronized, volume]);

  useEffect(() => () => {
    sessionRef.current?.close();
    void audio?.close();
  }, [audio]);

  useEffect(() => {
    if (!audio) return;
    const resume = () => {
      if (document.visibilityState === 'visible' && audio.state === 'suspended') {
        void sessionRef.current?.resumeAudio();
      }
    };
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('online', resume);
    window.addEventListener('pageshow', resume);
    return () => {
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('online', resume);
      window.removeEventListener('pageshow', resume);
    };
  }, [audio]);

  const enableAudio = useCallback(async () => {
    if (audio) {
      const resumed = sessionRef.current
        ? await sessionRef.current.resumeAudio()
        : await audio.resume().then(() => audio.state === 'running');
      if (!resumed) setActionError(new Error('This browser blocked audio. Tap again to resume.'));
      return;
    }
    const context = new AudioContext();
    await context.resume();
    const unlock = context.createBufferSource();
    unlock.buffer = context.createBuffer(1, 1, context.sampleRate);
    unlock.connect(context.destination);
    unlock.start();
    personalPlayer.pause();
    setAudio(context);
  }, [audio, personalPlayer]);

  const run = useCallback(async (action: () => Promise<Jam | void>) => {
    setActionError(undefined);
    try {
      const result = await action();
      if (result) setJam(result);
    } catch (error) {
      setActionError(error);
    }
  }, []);

  useInterval(
    () => {
      if (!jamId) return;
      void getJam(jamId).then(setJam).catch(() => undefined);
    },
    2000,
    member && live && jam?.state !== 'IDLE' && jam?.state !== 'ENDED',
  );

  useInterval(
    () => {
      if (!jamId) return;
      void getReadiness(jamId).then(setReadiness).catch(() => setReadiness(null));
    },
    2000,
    owner && live && jam?.state !== 'IDLE' && jam?.state !== 'ENDED',
  );

  const clear = useCallback(() => {
    sessionRef.current?.close();
    sessionRef.current = null;
    setSession(null);
    setSync(null);
    setReadiness(null);
    setJam(null);
    setJamId(null);
    activeJamIdRef.current = null;
    setParticipantId(null);
  }, []);

  const leaveCurrent = useCallback(async () => {
    if (!jamId || !participantId) return;
    setActionError(undefined);
    try {
      await leaveJam(jamId, participantId);
      clear();
    } catch (error) {
      setActionError(error);
      throw error;
    }
  }, [clear, jamId, participantId]);

  const transferAndLeaveCurrent = useCallback(async (nextOwnerId: string) => {
    if (!jamId) return;
    setActionError(undefined);
    try {
      await transferAndLeave(jamId, nextOwnerId);
      clear();
    } catch (error) {
      setActionError(error);
      throw error;
    }
  }, [clear, jamId]);

  const control = useCallback(async (
    action: ControlAction,
    extra: { queue_item_id?: string; position_ms?: number } = {},
  ) => {
    if (!jamId) return;
    await run(() => playback(jamId, action, extra));
  }, [jamId, run]);

  const setVolume = useCallback((value: number) => {
    const bounded = Math.max(0, Math.min(1, value));
    setVolumeState(bounded);
    sessionRef.current?.setVolume(bounded);
  }, []);

  const value = useMemo<JamSessionValue>(() => ({
    jamId,
    jam,
    participantId,
    member,
    owner,
    audioEnabled: Boolean(audio),
    localAudioState: sync?.localAudioState ?? (audio ? 'RUNNING' : 'LOCKED'),
    sync,
    session,
    readiness,
    closeCode,
    loadError,
    actionError,
    volume,
    activateJam,
    adoptJam,
    enableAudio,
    run,
    control,
    leaveCurrent,
    transferAndLeaveCurrent,
    positionMs: () => sessionRef.current?.positionMs() ?? 0,
    analyser: () => sessionRef.current?.analyser() ?? null,
    setVolume,
  }), [
    actionError, activateJam, adoptJam, audio, closeCode, enableAudio, jam, jamId, leaveCurrent,
    loadError, member, owner, participantId, readiness, run, session, sync, transferAndLeaveCurrent,
    volume, control, setVolume,
  ]);

  return <JamSessionContext.Provider value={value}>{children}</JamSessionContext.Provider>;
}

/** Access the persistent Jam session owned above the router. */
export function useJamSession(): JamSessionValue {
  const value = useContext(JamSessionContext);
  if (!value) throw new Error('useJamSession must be used inside <JamProvider>');
  return value;
}
