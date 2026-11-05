import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError } from '../api/http';
import { getAccount, logIn, logOut, signUp, type Account, type Credentials } from '../api/auth';
import { setSignedInAccount } from './session';

interface AuthValue {
  account: Account | null;
  loading: boolean;
  error: unknown;
  signUp: (credentials: Credentials) => Promise<Account>;
  logIn: (credentials: Credentials) => Promise<Account>;
  logOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>();

  useEffect(() => {
    let active = true;
    const loadAccount = async () => {
      try {
        const current = await getAccount();
        if (!active) return;
        setAccount(current);
        setSignedInAccount(current);
      } catch (cause) {
        if (!active) return;
        setAccount(null);
        setSignedInAccount(null);
        if (!(cause instanceof ApiError) || cause.status !== 401) setError(cause);
      } finally {
        if (active) setLoading(false);
      }
    };
    void loadAccount();
    return () => { active = false; };
  }, []);

  const value = useMemo<AuthValue>(() => ({
    account,
    loading,
    error,
    signUp: async (credentials) => {
      const next = await signUp(credentials);
      setError(undefined);
      return next;
    },
    logIn: async (credentials) => {
      const next = await logIn(credentials);
      setAccount(next);
      setSignedInAccount(next);
      setError(undefined);
      return next;
    },
    logOut: async () => {
      await logOut();
      setAccount(null);
      setSignedInAccount(null);
    },
  }), [account, error, loading]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
