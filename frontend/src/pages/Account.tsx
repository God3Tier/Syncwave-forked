import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { ApiError } from '../api/http';
import { useAuth } from '../auth/AuthProvider';
import { Icon } from '../components/ui';

type Mode = 'login' | 'signup';

function safeReturnTo(value: string | null): string {
  if (!value || !value.startsWith('/') || value.startsWith('//')) return '/';
  if (value === '/login' || value === '/signup') return '/';
  const target = new URL(value, window.location.origin);
  if (target.origin !== window.location.origin) return '/';
  return `${target.pathname}${target.search}${target.hash}`;
}

export function AccountPage({ mode }: { mode: Mode }) {
  const isSignup = mode === 'signup';
  const { account, loading, signUp, logIn } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const returnTo = safeReturnTo(params.get('returnTo'));
  const intent = params.get('intent');
  const destination = (() => {
    if (!intent) return returnTo;
    const next = new URL(returnTo, window.location.origin);
    next.searchParams.set('intent', intent);
    return `${next.pathname}${next.search}${next.hash}`;
  })();

  useEffect(() => {
    if (!loading && account) navigate(destination, { replace: true });
  }, [account, destination, loading, navigate]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError('');
    if (isSignup && password !== confirmPassword) {
      setError('Those passwords do not match.');
      return;
    }
    setBusy(true);
    try {
      const credentials = { username: username.trim(), password };
      if (isSignup) await signUp(credentials);
      else await logIn(credentials);
      navigate(destination, { replace: true });
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setError('That username is already taken. Try another one.');
      } else if (cause instanceof ApiError && cause.status === 401) {
        setError('That username and password do not match.');
      } else if (cause instanceof ApiError && cause.status === 422) {
        setError('Use 3–24 letters, numbers, or underscores for your username and at least 10 characters for your password.');
      } else {
        setError('Could not connect right now. Try again in a moment.');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto grid min-h-full w-full max-w-5xl items-center gap-10 px-4 py-8 md:grid-cols-[1fr_24rem] md:px-8">
      <section className="hidden max-w-xl md:block" aria-label="SyncWave listening together">
        <div className="mb-7 flex items-end gap-1.5" aria-hidden="true">
          {[20, 38, 27, 52, 34, 45, 18, 30, 48, 25, 40].map((height, index) => (
            <span key={index} className={`w-2 rounded-full ${index === 4 || index === 8 ? 'bg-secondary' : 'bg-primary'}`} style={{ height }} />
          ))}
        </div>
        <p className="font-mono text-xs uppercase tracking-[0.18em] text-secondary">Your friends are one link away</p>
        <h1 className="mt-4 text-4xl font-extrabold leading-tight tracking-[-0.045em] lg:text-5xl">
          Find a track.<br />Bring everyone in.
        </h1>
        <p className="mt-5 max-w-md text-sm leading-7 text-on-surface-variant">
          Keep listening without an account. Sign in when you want to save a playlist or host a Jam with your friends.
        </p>
      </section>

      <section className="w-full rounded-2xl border border-outline-variant/45 bg-surface-container-lowest p-6 shadow-[0_22px_64px_rgb(0_0_0/0.25)] sm:p-8" aria-labelledby="account-title">
        <div className="mb-7 flex items-center gap-3 md:hidden">
          <Icon name="graphic_eq" className="text-2xl text-primary" />
          <span className="text-lg font-extrabold tracking-tight">SyncWave</span>
        </div>
        <p className="font-mono text-[11px] uppercase tracking-[0.16em] text-secondary">{isSignup ? 'Make it yours' : 'Welcome back'}</p>
        <h2 id="account-title" className="mt-2 text-2xl font-extrabold tracking-[-0.035em]">
          {isSignup ? 'Create your account' : 'Log in to SyncWave'}
        </h2>
        <p className="mt-2 text-sm leading-6 text-on-surface-variant">
          {isSignup ? 'Save your playlists and start listening rooms.' : 'Your playlists and Jams are waiting.'}
        </p>

        <form onSubmit={(event) => void submit(event)} className="mt-7 flex flex-col gap-4">
          <div>
            <label htmlFor="username" className="mb-1.5 block text-sm font-semibold">Username</label>
            <input
              id="username"
              name="username"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
              required
              minLength={3}
              maxLength={24}
              pattern="[A-Za-z0-9_]{3,24}"
              title="Use 3–24 letters, numbers, or underscores."
              className="min-h-12 w-full rounded-xl border border-outline-variant/55 bg-surface-container px-3.5 text-sm outline-none transition focus:border-secondary focus:ring-2 focus:ring-secondary/25"
            />
            {isSignup && <p className="mt-1.5 text-xs text-on-surface-variant">3–24 letters, numbers, or underscores.</p>}
          </div>
          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm font-semibold">Password</label>
            <input
              id="password"
              name="password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={isSignup ? 'new-password' : 'current-password'}
              required
              minLength={10}
              maxLength={128}
              className="min-h-12 w-full rounded-xl border border-outline-variant/55 bg-surface-container px-3.5 text-sm outline-none transition focus:border-secondary focus:ring-2 focus:ring-secondary/25"
            />
          </div>
          {isSignup && (
            <div>
              <label htmlFor="confirm-password" className="mb-1.5 block text-sm font-semibold">Confirm password</label>
              <input
                id="confirm-password"
                name="confirm-password"
                type="password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                autoComplete="new-password"
                required
                minLength={10}
                maxLength={128}
                className="min-h-12 w-full rounded-xl border border-outline-variant/55 bg-surface-container px-3.5 text-sm outline-none transition focus:border-secondary focus:ring-2 focus:ring-secondary/25"
              />
            </div>
          )}
          {error && <p role="alert" className="rounded-lg border border-error/35 bg-error/10 px-3 py-2.5 text-sm text-error">{error}</p>}
          <button
            type="submit"
            disabled={busy}
            className="mt-1 inline-flex min-h-12 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-sm font-extrabold text-on-primary transition hover:brightness-110 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary disabled:cursor-wait disabled:opacity-60"
          >
            {busy ? 'Please wait…' : isSignup ? 'Create account' : 'Log in'}
          </button>
        </form>

        <p className="mt-6 text-center text-sm text-on-surface-variant">
          {isSignup ? 'Already have an account? ' : 'New to SyncWave? '}
          <Link
            to={`${isSignup ? '/login' : '/signup'}?returnTo=${encodeURIComponent(returnTo)}${intent ? `&intent=${encodeURIComponent(intent)}` : ''}`}
            className="font-bold text-primary underline-offset-4 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-secondary"
          >
            {isSignup ? 'Log in' : 'Create an account'}
          </Link>
        </p>
        <Link to={returnTo} className="mt-4 block text-center text-xs text-on-surface-variant underline-offset-4 hover:text-on-surface hover:underline">
          Keep listening as a guest
        </Link>
      </section>
    </div>
  );
}
