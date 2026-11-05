import type { ButtonHTMLAttributes, ReactNode } from 'react';
import {
  ArrowRight,
  AudioLines,
  Check,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  CircleHelp,
  CirclePlus,
  Cloud,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSun,
  Copy,
  GripVertical,
  Home,
  Info,
  Library,
  Link as LinkIcon,
  ListMusic,
  ListPlus,
  LoaderCircle,
  LogOut,
  MapPin,
  MoreHorizontal,
  MoreVertical,
  Pause,
  Pencil,
  Play,
  PlayCircle,
  Radio,
  Search,
  Shuffle,
  SkipBack,
  SkipForward,
  Snowflake,
  Sparkles,
  Sun,
  Trash2,
  TriangleAlert,
  Unplug,
  Upload,
  UserPlus,
  Users,
  Volume2,
  VolumeX,
  X,
  type LucideIcon,
} from 'lucide-react';
import { gradientFor } from '../format';

const icons: Record<string, LucideIcon> = {
  add: CirclePlus,
  add_circle: CirclePlus,
  arrow_forward: ArrowRight,
  auto_awesome: Sparkles,
  check: Check,
  check_circle: CheckCircle2,
  clear_day: Sun,
  close: X,
  cloud: Cloud,
  cloud_upload: Upload,
  content_copy: Copy,
  delete: Trash2,
  done: Check,
  drag_indicator: GripVertical,
  edit: Pencil,
  error: CircleAlert,
  expand_more: ChevronDown,
  explore: Radio,
  foggy: CloudFog,
  graphic_eq: AudioLines,
  group: Users,
  group_add: UserPlus,
  home: Home,
  info: Info,
  library_music: Library,
  link: LinkIcon,
  logout: LogOut,
  more_horiz: MoreHorizontal,
  more_vert: MoreVertical,
  my_location: MapPin,
  partly_cloudy_day: CloudSun,
  pause: Pause,
  play_arrow: Play,
  play_circle: PlayCircle,
  playlist_add: ListPlus,
  queue_music: ListMusic,
  query_stats: Radio,
  rainy: CloudRain,
  search: Search,
  sensors: Radio,
  shuffle: Shuffle,
  skip_next: SkipForward,
  skip_previous: SkipBack,
  sync: LoaderCircle,
  sync_problem: Unplug,
  thunderstorm: CloudLightning,
  upload: Upload,
  volume_off: VolumeX,
  volume_up: Volume2,
  warning: TriangleAlert,
  weather_snowy: Snowflake,
};

export function Icon({ name, className = '', fill = false }: { name: string; className?: string; fill?: boolean }) {
  const Component = icons[name] ?? CircleHelp;
  return <Component aria-hidden="true" size="1em" strokeWidth={2} fill={fill ? 'currentColor' : 'none'} className={className} />;
}

type Variant = 'primary' | 'secondary' | 'ghost' | 'cyan' | 'danger';
const variants: Record<Variant, string> = {
  primary: 'bg-primary text-on-primary hover:bg-primary-container shadow-[0_7px_24px_rgb(255_115_80/0.16)] font-bold',
  secondary: 'bg-surface-container-high hover:bg-surface-container-highest border border-outline-variant/55 text-on-surface',
  ghost: 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high',
  cyan: 'border border-secondary/45 text-secondary bg-secondary/5 hover:bg-secondary/12',
  danger: 'text-error border border-error/35 hover:bg-error/10',
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
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm transition-[background-color,color,border-color,transform] duration-150 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45 ${variants[variant]} ${className}`}
    >
      {icon ? <Icon name={icon} className="text-[1.1rem]" /> : null}
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
      className={`inline-flex size-10 items-center justify-center rounded-xl text-on-surface-variant transition-colors hover:bg-surface-container-high hover:text-on-surface disabled:cursor-not-allowed disabled:opacity-35 ${className}`}
    >
      <Icon name={icon} fill={fill} className="text-xl" />
    </button>
  );
}

/** Deterministic record-sleeve art used until the catalogue carries cover artwork. */
export function SongArt({ id, size = 'md', className = '' }: { id: string; size?: 'sm' | 'md' | 'lg' | 'xl'; className?: string }) {
  const sizes = {
    sm: 'size-11 rounded-[10px]',
    md: 'size-12 rounded-xl',
    lg: 'aspect-square w-full rounded-2xl',
    xl: 'size-48 rounded-2xl md:size-56',
  };
  let hash = 0;
  for (let i = 0; i < id.length; i++) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  const bars = Array.from({ length: size === 'sm' || size === 'md' ? 4 : 7 }, (_, index) => 24 + ((hash >>> (index * 3)) % 62));

  return (
    <div
      aria-hidden="true"
      className={`relative isolate flex shrink-0 items-end overflow-hidden shadow-[0_10px_24px_rgb(0_0_0/0.18)] ${sizes[size]} ${className}`}
      style={{ background: gradientFor(id) }}
    >
      <span className="absolute inset-[9%] rounded-full border border-black/15 opacity-45" />
      <span className="absolute right-[13%] top-[13%] size-[12%] rounded-full bg-black/50 ring-2 ring-white/30" />
      <span className={`relative z-10 flex items-end ${size === 'sm' || size === 'md' ? 'mb-2 ml-2 h-4 gap-[2px]' : 'mb-[11%] ml-[11%] h-[24%] gap-[3%]'}`}>
        {bars.map((height, index) => (
          <span
            key={index}
            className={`rounded-full bg-white/85 ${size === 'sm' || size === 'md' ? 'w-[2px]' : 'w-1.5'}`}
            style={{ height: `${height}%` }}
          />
        ))}
      </span>
    </div>
  );
}

const chipStyles: Record<string, string> = {
  READY: 'bg-secondary/10 text-secondary border-secondary/25',
  PROCESSING: 'bg-warn/10 text-warn border-warn/25',
  PENDING: 'bg-outline-variant/20 text-on-surface-variant border-outline-variant/45',
  PARTIAL: 'bg-partial/10 text-partial border-partial/25',
  FAILED: 'bg-error/10 text-error border-error/25',
  PLAYING: 'bg-secondary/10 text-secondary border-secondary/25',
  SCHEDULED: 'bg-secondary/10 text-secondary border-secondary/25',
  PREPARING: 'bg-warn/10 text-warn border-warn/25',
  PAUSED: 'bg-outline-variant/20 text-on-surface border-outline-variant/45',
  IDLE: 'bg-outline-variant/20 text-on-surface-variant border-outline-variant/45',
  ENDED: 'bg-outline-variant/20 text-on-surface-variant border-outline-variant/45',
  OWNER: 'bg-primary/12 text-primary border-primary/25',
  MEMBER: 'bg-outline-variant/20 text-on-surface-variant border-outline-variant/45',
};
const pulsing = new Set(['PROCESSING', 'PREPARING', 'PLAYING']);

export function StatusChip({ status, label }: { status: string; label?: string }) {
  const style = chipStyles[status] ?? chipStyles.PENDING;
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-1 text-[11px] font-bold tracking-wide ${style}`}>
      {status !== 'OWNER' && status !== 'MEMBER' ? (
        <span className={`size-1.5 rounded-full bg-current ${pulsing.has(status) ? 'animate-pulse-glow' : ''}`} />
      ) : null}
      {label ?? status}
    </span>
  );
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <section className={`rounded-2xl bg-surface-container-low p-5 ring-1 ring-outline-variant/45 ${className}`}>{children}</section>;
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <h2 className="max-w-3xl text-xl font-extrabold tracking-[-0.025em] md:text-2xl">{children}</h2>
      {aside}
    </div>
  );
}

export function Notice({ tone = 'info', children, action }: { tone?: 'info' | 'error' | 'warn'; children: ReactNode; action?: ReactNode }) {
  const styles = {
    info: 'bg-secondary/6 text-on-surface ring-secondary/22',
    warn: 'bg-warn/6 text-on-surface ring-warn/22',
    error: 'bg-error/6 text-on-surface ring-error/25',
  };
  const icons = { info: 'info', warn: 'warning', error: 'error' };
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={`flex items-start gap-3 rounded-xl px-4 py-3 text-sm ring-1 ${styles[tone]}`}>
      <Icon name={icons[tone]} className={tone === 'error' ? 'text-error' : tone === 'warn' ? 'text-warn' : 'text-secondary'} />
      <div className="min-w-0 flex-1 leading-6">{children}</div>
      {action}
    </div>
  );
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-6 text-sm text-on-surface-variant" role="status">
      <span className="size-4 animate-spin rounded-full border-2 border-outline-variant border-t-primary" />
      {label}…
    </div>
  );
}

export function EqualizerIcon() {
  return (
    <span className="flex h-4 items-end gap-0.5" aria-label="Now playing">
      {[0, 180, 360].map((delay) => (
        <span key={delay} className="eq-bar h-4 w-0.5 rounded-full bg-primary" style={{ animationDelay: `${delay}ms` }} />
      ))}
    </span>
  );
}
