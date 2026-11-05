import { useCallback, useEffect, useEffectEvent, useState } from 'react';

export interface AsyncState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
  setData: (value: T) => void;
}

interface Result<T> {
  key: string;
  data: T | undefined;
  error: unknown;
}

/**
 * Runs `load` whenever `deps` change, aborting the previous run. The previous
 * data stays visible while the next load is in flight.
 */
export function useAsync<T>(load: (signal: AbortSignal) => Promise<T>, deps: readonly (string | number | boolean | null | undefined)[]): AsyncState<T> {
  const [tick, setTick] = useState(0);
  const key = `${deps.map(String).join('\u0000')}\u0000${tick}`;
  const [result, setResult] = useState<Result<T>>({ key: '', data: undefined, error: undefined });
  const run = useEffectEvent(load);

  useEffect(() => {
    const controller = new AbortController();
    run(controller.signal).then(
      (data) => !controller.signal.aborted && setResult({ key, data, error: undefined }),
      (error: unknown) => !controller.signal.aborted && setResult((previous) => ({ key, data: previous.data, error })),
    );
    return () => controller.abort();
  }, [key]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  const setData = useCallback((data: T) => setResult((previous) => ({ ...previous, data, error: undefined })), []);
  return {
    data: result.data,
    error: result.key === key ? result.error : undefined,
    loading: result.key !== key,
    reload,
    setData,
  };
}

/** Calls `fn` every `ms` while `active`. */
export function useInterval(fn: () => void, ms: number, active = true): void {
  const tick = useEffectEvent(fn);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => tick(), ms);
    return () => clearInterval(timer);
  }, [ms, active]);
}

export function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}
