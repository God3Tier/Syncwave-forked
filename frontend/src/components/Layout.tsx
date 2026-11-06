import { Link, NavLink, Outlet, useLocation } from 'react-router';
import { guestName } from '../guestName';
import { userId } from '../identity';
import { useAuth } from '../auth/AuthProvider';
import { PlayerBar } from './PlayerBar';
import { Icon } from './ui';

const primaryNav = [
  { to: '/', label: 'Home', icon: 'home', end: true },
  { to: '/search', label: 'Search', icon: 'search' },
  { to: '/playlists', label: 'Your library', icon: 'library_music' },
  { to: '/upload', label: 'Upload music', icon: 'upload' },
];

const mobileNav = [
  { to: '/', label: 'Home', icon: 'home', end: true },
  { to: '/search', label: 'Search', icon: 'search' },
  { to: '/playlists', label: 'Library', icon: 'library_music' },
  { to: '/jam', label: 'Jam', icon: 'graphic_eq' },
];

function Mark() {
  return (
    <span className="relative flex size-9 items-end justify-center gap-[3px] overflow-hidden rounded-[11px] bg-primary pb-2 shadow-[0_8px_22px_rgb(255_115_80/0.2)]">
      <span className="h-2 w-[3px] rounded-full bg-on-primary" />
      <span className="h-4 w-[3px] rounded-full bg-on-primary" />
      <span className="h-3 w-[3px] rounded-full bg-on-primary" />
      <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-secondary" />
    </span>
  );
}

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-3 rounded-xl" aria-label="SyncWave home">
      <Mark />
      <span className="text-lg font-extrabold tracking-[-0.035em]">SyncWave</span>
    </Link>
  );
}

function NavigationLink({ item }: { item: (typeof primaryNav)[number] }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        `flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-semibold transition-colors ${isActive ? 'bg-on-surface text-background' : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'}`
      }
    >
      <Icon name={item.icon} className="text-xl" />
      {item.label}
    </NavLink>
  );
}

export function Layout() {
  const { pathname } = useLocation();
  const inJamRoom = /^\/jam\/[^/]+/.test(pathname);
  const { account, loading, logOut } = useAuth();

  return (
    <div className="flex h-full flex-col bg-background lg:flex-row">
      <a href="#main-content" className="sr-only z-50 rounded-lg bg-on-surface px-3 py-2 text-background focus:not-sr-only focus:fixed focus:left-3 focus:top-3">Skip to content</a>
      <aside className="hidden w-[15rem] shrink-0 flex-col border-r border-outline-variant/35 bg-surface-container-lowest px-4 pb-4 pt-5 lg:flex">
        <div className="px-2">
          <Brand />
        </div>

        <nav className="mt-9 flex flex-col gap-1" aria-label="Main">
          {primaryNav.map((item) => <NavigationLink key={item.to} item={item} />)}
        </nav>

        <div className="mt-7 border-t border-outline-variant/35 pt-5">
          <Link
            to="/jam"
            className="group block rounded-2xl bg-surface-container p-4 ring-1 ring-outline-variant/50 transition-colors hover:bg-surface-container-high"
          >
            <span className="flex items-center justify-between">
              <span className="flex -space-x-2" aria-hidden="true">
                {['bg-primary', 'bg-secondary', 'bg-tertiary'].map((color) => (
                  <span key={color} className={`size-7 rounded-full border-2 border-surface-container ${color}`} />
                ))}
              </span>
              <Icon name="arrow_forward" className="text-lg text-outline transition-transform group-hover:translate-x-0.5 group-hover:text-on-surface" />
            </span>
            <span className="mt-4 block text-sm font-extrabold">Listen together</span>
            <span className="mt-1 block text-xs leading-5 text-on-surface-variant">Start a room or join your friends.</span>
          </Link>
        </div>

        <div className="mt-auto flex items-center gap-3 border-t border-outline-variant/35 px-1 pt-4">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-secondary/15 text-xs font-extrabold text-secondary">
            {(account?.username ?? guestName).slice(0, 2).toUpperCase()}
          </span>
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs font-semibold" title={account ? account.username : `Guest · ${userId}`}>
              {loading ? 'Checking account…' : account?.username ?? guestName}
            </p>
            {account ? (
              <button type="button" onClick={() => void logOut().catch(() => undefined)} className="mt-0.5 text-xs text-on-surface-variant underline-offset-4 hover:text-on-surface hover:underline">
                Log out
              </button>
            ) : (
              <Link to={`/login?returnTo=${encodeURIComponent(pathname)}`} className="mt-0.5 inline-block text-xs text-primary underline-offset-4 hover:underline">
                Log in
              </Link>
            )}
          </div>
        </div>
      </aside>

      <header className="flex h-16 items-center justify-between border-b border-outline-variant/35 bg-surface-container-lowest px-4 lg:hidden">
        <Brand />
        <div className="flex items-center gap-1">
          <Link to="/upload" aria-label="Upload music" className="flex size-10 items-center justify-center rounded-xl text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface">
            <Icon name="upload" className="text-xl" />
          </Link>
          {account ? (
            <button type="button" onClick={() => void logOut().catch(() => undefined)} aria-label={`Log out ${account.username}`} className="rounded-xl px-2.5 py-2 text-xs font-bold text-secondary hover:bg-surface-container-high">
              {account.username}
            </button>
          ) : (
            <Link to={`/login?returnTo=${encodeURIComponent(pathname)}`} className="rounded-xl px-2.5 py-2 text-xs font-bold text-primary hover:bg-surface-container-high">
              Log in
            </Link>
          )}
        </div>
      </header>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <main id="main-content" className="app-canvas min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
        {!inJamRoom ? <PlayerBar /> : null}
        <nav className="grid grid-cols-4 border-t border-outline-variant/40 bg-surface-container-lowest pb-[env(safe-area-inset-bottom)] lg:hidden" aria-label="Main">
          {mobileNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex min-h-[4rem] flex-col items-center justify-center gap-1 text-[11px] font-bold transition-colors ${isActive ? 'text-primary' : 'text-on-surface-variant'}`
              }
            >
              <Icon name={item.icon} fill className="text-[1.35rem]" />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}

export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={`page-enter mx-auto w-full px-4 pb-10 pt-6 md:px-8 md:pb-14 md:pt-9 ${wide ? 'max-w-[1480px]' : 'max-w-6xl'}`}>
      {children}
    </div>
  );
}
