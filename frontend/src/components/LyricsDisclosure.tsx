import { useRef, useState, type ReactNode } from 'react';
import { Icon } from './ui';

/** Accessible, initially collapsed disclosure for synced song lyrics. */
export function LyricsDisclosure({ children }: { readonly children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const toggle = () => {
    setOpen((current) => {
      const next = !current;
      if (next) requestAnimationFrame(() => headingRef.current?.focus());
      return next;
    });
  };

  return (
    <section className="h-fit rounded-2xl bg-surface-container-low p-0 ring-1 ring-outline-variant/45">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="song-lyrics-panel"
        onClick={toggle}
        className="group flex min-h-14 w-full items-center justify-between gap-3 rounded-2xl px-5 text-left hover:bg-surface-container-high focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        <span className="flex items-center gap-2 text-lg font-extrabold">Lyrics <span className="font-mono text-xs font-normal text-secondary">· synced</span></span>
        <Icon name="play_arrow" className={`text-xl text-primary transition-transform ${open ? 'rotate-90' : ''}`} />
      </button>
      {open && (
        <div id="song-lyrics-panel" className="border-t border-outline-variant/30 px-5 pb-5 pt-4">
          <h2 ref={headingRef} tabIndex={-1} className="sr-only">Synced lyrics</h2>
          {children}
        </div>
      )}
    </section>
  );
}
