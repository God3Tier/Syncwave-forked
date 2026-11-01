import { NavLink, Outlet, useLocation } from 'react-router';
import { shortId } from '../format';
import { switchIdentity, userId } from '../identity';
import { PlayerBar } from './PlayerBar';
import { Icon } from './ui';

const nav = [
  { to: '/', label: 'Discover', icon: 'explore', end: true },
  { to: '/search', label: 'Search', icon: 'search' },
  { to: '/upload', label: 'Upload', icon: 'cloud_upload' },
  { to: '/playlists', label: 'Playlists', icon: 'queue_music' },
  { to: '/jam', label: 'Jam', icon: 'graphic_eq' },
];

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-2">
      <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary-dim to-secondary-dim shadow-lg shadow-primary/20">
        <Icon name="graphic_eq" className="text-xl text-white" />
      </div>
      <div>
        <p className="font-headline text-lg font-bold leading-tight tracking-tight">SyncWave</p>
        <p className="font-mono text-[10px] uppercase tracking-widest text-secondary">Synchronized audio</p>
      </div>
    </div>
  );
}

/** App shell from the Stitch screens: sidebar on desktop, bottom tabs on phones, persistent player. */
export function Layout() {
  const { pathname } = useLocation();
  // The Jam room has its own synchronised player deck (Stitch "Jam Room" screen).
  const inJamRoom = /^\/jam\/[^/]+/.test(pathname);

  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="hidden w-64 shrink-0 flex-col justify-between border-r border-outline-variant/30 bg-surface-container-low p-4 md:flex">
        <div className="space-y-8">
          <Brand />
          <nav className="space-y-1 font-headline text-sm font-medium" aria-label="Main">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `flex items-center gap-3 rounded-lg px-3 py-2.5 transition-colors ${
                    isActive
                      ? 'border-l-2 border-primary bg-surface-container-highest text-primary'
                      : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface'
                  }`
                }
              >
                <Icon name={item.icon} className="text-xl" />
                {item.label}
              </NavLink>
            ))}
          </nav>
          <NavLink
            to="/jam"
            className="flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-primary-dim to-primary px-4 py-3 font-headline text-sm font-semibold text-white shadow-lg shadow-primary/25 transition-transform hover:scale-[1.02]"
          >
            <Icon name="sensors" className="text-lg" />
            Start Jam
          </NavLink>
        </div>
        <div className="flex items-center gap-2.5 rounded-lg border border-outline-variant/30 bg-surface-container-high/60 p-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-tr from-primary to-secondary font-mono text-[10px] font-bold text-on-primary">
            {userId.slice(0, 2).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-mono text-xs text-on-surface" title={userId}>
              user · {shortId(userId)}
            </p>
            <button type="button" onClick={switchIdentity} className="font-mono text-[10px] text-secondary hover:underline">
              switch identity
            </button>
          </div>
        </div>
      </aside>

      <header className="flex items-center justify-between border-b border-outline-variant/20 bg-surface-container-low px-4 py-3 md:hidden">
        <Brand />
        <span className="font-mono text-[10px] text-outline" title={userId}>
          {shortId(userId)}
        </span>
      </header>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <main className="bg-grid-mesh min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
        {!inJamRoom && <PlayerBar />}
        <nav className="grid grid-cols-5 border-t border-outline-variant/20 bg-surface-container-low md:hidden" aria-label="Main">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 py-2 font-headline text-[11px] ${isActive ? 'text-primary' : 'text-on-surface-variant'}`
              }
            >
              <Icon name={item.icon} className="text-xl" />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}

export function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
  return <div className={`mx-auto w-full px-4 py-6 md:px-8 md:py-8 ${wide ? 'max-w-[1600px]' : 'max-w-6xl'}`}>{children}</div>;
}
