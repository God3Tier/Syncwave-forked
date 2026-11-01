// Small building blocks ported from the Stitch screens (SyncWave Dark design system).

import type { ButtonHTMLAttributes, ReactNode } from 'react';
import { gradientFor } from '../format';

export function Icon({ name, className = '', fill = false }: { name: string; className?: string; fill?: boolean }) {
  return (
    <span aria-hidden="true" className={`material-symbols-outlined ${fill ? 'fill' : ''} ${className}`}>
      {name}
    </span>
  );
}

type Variant = 'primary' | 'secondary' | 'ghost' | 'cyan' | 'danger';
const variants: Record<Variant, string> = {
  primary: 'bg-primary text-on-primary hover:bg-primary-container shadow-lg shadow-primary/25 font-semibold',
  secondary: 'bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant/40 text-on-surface',
  ghost: 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high',
  cyan: 'border border-secondary/50 text-secondary bg-secondary/5 hover:bg-secondary/15 shadow-[0_0_12px_rgb(58_223_250/0.12)]',
  danger: 'text-error border border-error/25 hover:bg-error-container/20',
};

export function Button({
  variant = 'secondary',
  icon,
  className = '',
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; icon?: string }) {
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 font-headline text-sm transition-all active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${className}`}
    >
      {icon && <Icon name={icon} className="text-lg" />}
      {children}
    </button>
  );
}

export function IconButton({
  icon,
  label,
  className = '',
  fill,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon: string; label: string; fill?: boolean }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      {...props}
      className={`inline-flex items-center justify-center rounded-lg p-1.5 text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface disabled:opacity-40 ${className}`}
    >
      <Icon name={icon} fill={fill} className="text-xl" />
    </button>
  );
}

/** Abstract gradient tile with a waveform glyph: the catalogue has no artwork. */
export function SongArt({ id, size = 'md', className = '' }: { id: string; size?: 'sm' | 'md' | 'lg' | 'xl'; className?: string }) {
  const sizes = { sm: 'h-10 w-10 rounded-lg', md: 'h-12 w-12 rounded-lg', lg: 'aspect-square w-full rounded-xl', xl: 'h-48 w-48 rounded-2xl md:h-56 md:w-56' };
  const bars = size === 'sm' || size === 'md' ? [40, 75, 55, 90, 45] : [35, 60, 85, 50, 95, 65, 40];
  return (
    <div
      className={`relative flex shrink-0 items-center justify-center overflow-hidden border border-white/10 shadow-inner ${sizes[size]} ${className}`}
      style={{ background: gradientFor(id) }}
    >
      <div className={`flex items-center ${size === 'sm' || size === 'md' ? 'h-1/2 gap-[2px]' : 'h-1/3 gap-1.5'}`}>
        {bars.map((height, i) => (
          <span key={i} className={`rounded-full bg-white/70 ${size === 'sm' || size === 'md' ? 'w-[2px]' : 'w-1.5'}`} style={{ height: `${height}%` }} />
        ))}
      </div>
    </div>
  );
}

const chipStyles: Record<string, string> = {
  READY: 'bg-ok/10 text-ok border-ok/30',
  PROCESSING: 'bg-warn/10 text-warn border-warn/30',
  PENDING: 'bg-outline-variant/20 text-on-surface-variant border-outline-variant/40',
  PARTIAL: 'bg-partial/10 text-partial border-partial/30',
  FAILED: 'bg-error/10 text-error border-error/30',
  PLAYING: 'bg-secondary/10 text-secondary border-secondary/40',
  SCHEDULED: 'bg-secondary/10 text-secondary border-secondary/40',
  PREPARING: 'bg-warn/10 text-warn border-warn/30',
  PAUSED: 'bg-outline-variant/20 text-on-surface border-outline-variant/40',
  IDLE: 'bg-outline-variant/20 text-on-surface-variant border-outline-variant/40',
  ENDED: 'bg-outline-variant/20 text-on-surface-variant border-outline-variant/40',
  OWNER: 'bg-primary/15 text-primary border-primary/30',
  MEMBER: 'bg-outline-variant/20 text-on-surface-variant border-outline-variant/40',
};
const pulsing = new Set(['PROCESSING', 'PREPARING', 'PLAYING']);

export function StatusChip({ status, label }: { status: string; label?: string }) {
  const style = chipStyles[status] ?? chipStyles.PENDING;
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 font-mono text-[11px] font-semibold tracking-wide ${style}`}>
      {status !== 'OWNER' && status !== 'MEMBER' && (
        <span className={`h-1.5 w-1.5 rounded-full bg-current ${pulsing.has(status) ? 'animate-pulse-glow' : ''}`} />
      )}
      {label ?? status}
    </span>
  );
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-xl border border-outline-variant/30 bg-surface-container-low p-5 ${className}`}>{children}</section>;
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <h2 className="font-headline text-xl font-bold tracking-tight md:text-2xl">{children}</h2>
      {aside}
    </div>
  );
}

export function Notice({ tone = 'info', children, action }: { tone?: 'info' | 'error' | 'warn'; children: ReactNode; action?: ReactNode }) {
  const styles = {
    info: 'border-secondary/30 bg-secondary/5 text-on-surface',
    warn: 'border-warn/30 bg-warn/5 text-on-surface',
    error: 'border-error/30 bg-error/5 text-on-surface',
  };
  const icons = { info: 'info', warn: 'warning', error: 'error' };
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`flex items-start gap-3 rounded-xl border px-4 py-3 text-sm ${styles[tone]}`}>
      <Icon name={icons[tone]} className={tone === 'error' ? 'text-error' : tone === 'warn' ? 'text-warn' : 'text-secondary'} />
      <div className="flex-1">{children}</div>
      {action}
    </div>
  );
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 font-mono text-xs text-on-surface-variant" role="status">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      {label}…
    </div>
  );
}

export function EqualizerIcon() {
  return (
    <span className="flex h-4 items-end gap-0.5" aria-label="now playing">
      {[0, 200, 400].map((delay) => (
        <span key={delay} className="eq-bar h-4 w-0.5 rounded-full bg-secondary" style={{ animationDelay: `${delay}ms` }} />
      ))}
    </span>
  );
}
