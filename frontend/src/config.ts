// Runtime configuration. Every service is reached through the gateway at
// /api/<service>/ on the page's own origin, so there are no hosts to configure.
//
// The two tokens are the fixed mock credentials of the local stack
// (services/jam/compose.yaml MOCK_JAM_TOKEN, services/sync/compose.yaml
// MOCK_SYNC_TOKEN). Jam does not yet hand the browser a Sync token, so the
// frontend uses the configured one.

export const config = {
  jamToken: import.meta.env.VITE_JAM_MEMBER_TOKEN ?? 'local-jam-member-token',
  syncToken: import.meta.env.VITE_SYNC_PARTICIPANT_TOKEN ?? 'local-sync-participant-token',
  /** How often PLAYBACK_STATUS is reported to Sync (plan.md STATUS_INTERVAL_MS). */
  syncStatusIntervalMs: 2000,
  /** Sync closes idle sockets after 45 s; a TIME_PING keeps it alive and refreshes the offset. */
  syncHeartbeatMs: 15000,
  /** How many songs after the current one the player pre-buffers. */
  prefetchAhead: 2,
};
