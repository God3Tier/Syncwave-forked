import { Navigate, Outlet, useLocation } from 'react-router';
import { Spinner } from '../components/ui';
import { useAuth } from './AuthProvider';

/** Protects account-only routes while preserving the user's intended destination. */
export function RequireAccount() {
  const { account, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="mx-auto flex min-h-[50vh] max-w-6xl items-center px-4 md:px-8">
        <Spinner label="Checking your account" />
      </div>
    );
  }

  if (!account) {
    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    return <Navigate to={`/login?returnTo=${encodeURIComponent(returnTo)}`} replace />;
  }

  return <Outlet />;
}
