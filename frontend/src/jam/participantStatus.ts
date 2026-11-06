export function connectionStatusClasses(connected: boolean): string {
  return connected ? 'bg-primary/15 text-primary' : 'text-outline';
}

export function connectionDotClasses(connected: boolean): string {
  return connected ? 'bg-primary' : 'bg-outline-variant';
}

export function readinessStatusClasses(ready: boolean): string {
  return ready
    ? 'bg-secondary/15 text-secondary shadow-[0_0_8px_rgb(121_227_195/0.2)]'
    : 'text-outline';
}

export function readinessDotClasses(ready: boolean): string {
  return ready
    ? 'bg-secondary shadow-[0_0_6px_rgb(121_227_195/0.65)]'
    : 'bg-outline-variant';
}
