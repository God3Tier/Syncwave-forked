/** Whole seconds shown in the owner prompt for the server-owned deadline. */
export function autoplaySecondsRemaining(deadlineMs: number | null, nowMs = Date.now()): number {
  return Math.max(0, Math.ceil(((deadlineMs ?? nowMs) - nowMs) / 1000));
}
