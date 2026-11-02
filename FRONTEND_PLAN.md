# SyncWave frontend: nine-slot buffering, laptop/mobile UI, and Playwright tests

Updated: 30 October 2026.
Status: agreed implementation plan; the frontend and chunk API described below
have not been implemented. Working branch: `feat/streaming-sync-integration`.

## 1. Goal and technology

Build the first usable frontend with real audio playback, playlists,
synchronized Jams, and the **nine-slot adaptive buffer**. Support both laptop
and mobile screens.

Confirmed choices:

- React + Vite with TypeScript and npm.
- Dark listening-room appearance.
- Clearly labeled demo identity.
- Nine logical buffer slots on both device types, with adaptive resource limits.
- Playwright for browser acceptance tests.
- Upload, full Search, and production accounts follow once their services are ready.

Use React Router, TanStack Query, Tailwind CSS, shadcn/ui with Radix primitives,
Lucide icons, and Zod. Use native Fetch, WebSocket, Web Audio, and browser storage
APIs. Use Vitest for buffer and component behavior, React Testing Library for UI
tests, and axe with Playwright for accessibility checks. Use Node 24 and commit
the npm lockfile.

The available design and testing skills are sufficient. No external plugin is
required; Figma or Product Design remains optional for editable mockups.

## 2. Screens and responsive appearance

Use charcoal backgrounds, warm white text, cyan accents, readable typography,
clear focus indicators, and restrained animation.

| Screen | Features |
|---|---|
| Discover | Recommendations, paginated Catalogue list, Play, Add to playlist, and filtering clearly limited to loaded songs. |
| Playlists | Create, rename, delete, and open playlists, with informative empty states. |
| Playlist detail | Play, add/remove, shuffle, accessible reordering, and start a Jam using the saved order. |
| Jam entry | Create a room, join through an invitation link, and reopen locally remembered rooms. |
| Jam room | Shared queue, participants, readiness, connection status, current track, invitation link, and owner controls. |
| Help/settings | Demo identity explanation, keyboard shortcuts, audio activation instructions, recovery guidance, and data-saving preferences. |

The persistent player includes play/pause, solo previous/next, seeking, elapsed
time, duration, volume, lyrics, waveform, and queue access.

### Laptop: 1024 pixels and wider

- Persistent left navigation and bottom player.
- Main song list with visible title, artist, duration, and primary actions.
- Queue or lyrics in a right-side panel.
- A collapsible buffer view shows all nine positions, buffered duration,
  target duration, and loading/error status.

### Tablet: 768-1023 pixels

- Collapsed navigation.
- Queue and lyrics open in a drawer.
- Player controls retain clear spacing and labels.

### Mobile: below 768 pixels

- Bottom navigation for Discover, Playlists, and Jams.
- Mini-player above navigation and the device safe area.
- Expandable full-screen player.
- Jam queue and participants appear as labeled tabs.
- Buffer details appear as a vertical sheet rather than nine compressed cards.
- Support portrait and landscape without horizontal overflow.

Use initials-based artwork when cover images are unavailable. Provide explicit
loading, empty, buffering, unavailable-media, disconnected, and error states.

## 3. Nine-slot buffer and streaming changes

### Buffer ownership and targets

The browser owns the logical window, following the architecture in `plan.md`.

| Position | -4 | -3 | -2 | -1 | Current | +1 | +2 | +3 | +4 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Target | 30s | 30s | 120s | 120s | 180s | 120s | 120s | 30s | 30s |

Identify positions by queue item, allowing repeated songs without confusing
their queue positions. Reuse cached media chunks when the same song appears
more than once.

Default playback does not repeat the playlist. Positions beyond its beginning
or end remain empty.

### Reliable chunk delivery

The existing proportional byte-slicing endpoint must be replaced for this flow
because arbitrary slices of compressed files may not decode correctly.

Add a documented Streaming contract:

- A track manifest endpoint describing duration, media version, chunk format,
  and available chunk URLs.
- A chunk endpoint returning independently decodable audio.
- Use ten-second PCM WAV chunks for the initial implementation: 44.1 kHz,
  stereo, 16-bit, with a shorter final chunk.
- Generate chunks with FFmpeg from the original media and cache derivatives
  under a versioned S3 prefix.
- Limit concurrent server conversions to two. Bound FFmpeg execution time and
  clean up temporary files after success or failure.
- Include media version and sample boundaries in the manifest so the browser
  can reject stale content and schedule chunks without cumulative timing errors.
- Preserve the existing whole-track endpoint for compatibility.

Document the additions in `contracts/api/streaming.openapi.yaml`. Add FFmpeg to
Streaming's container.

The separate server-side ringbuffer remains outside the frontend playback
path; browser buffering follows the project's stated architecture.

### Scheduling and resource policy

- Fetch enough current-track audio to start before waiting for distant slots.
- Prioritize current track, +1, -1, +2, -2, then the outer slots.
- Allow at most two concurrent chunk downloads; prioritize a seek over prefetch.
- Store prefetched encoded chunks in a session-specific browser cache, capped
  at 256 MiB and reduced when available storage is insufficient.
- Keep decoded audio bounded to 64 MiB, normally retaining only the current
  and immediately scheduled chunks.
- Recheck browser storage limits and handle cache writes or decoding failures.
- If persistent browser caching is unavailable, use a bounded memory cache
  and reduce distant prefetch.
- In data-saving mode, pause distant prefetch and show reduced coverage. All
  nine logical positions remain represented.
- Release session-owned caches on normal exit and clean up abandoned session
  caches on subsequent startup.

As playback advances, rotate the window, preserve useful chunks, cancel
obsolete requests, and evict songs outside the window.

For long current tracks, maintain approximately 180 seconds of rolling
coverage, retaining up to 30 seconds behind the cursor and prioritizing the
remainder ahead. Clamp coverage to actual track boundaries.

On a seek, invalidate obsolete scheduling, fetch the destination chunks first,
and resume only when usable audio is available. Missing neighbor chunks must
not block current playback.

### Playback and Jam integration

Keep one audio engine outside route components. Schedule decoded chunks
against `AudioContext` time and release completed sources.

For Jams:

- Jam remains responsible for membership, queue changes, and owner commands.
- Sync remains responsible for clock exchange, readiness, scheduled playback,
  and corrections.
- Use the same buffer engine in solo and Jam modes.
- Send readiness after audio activation and sufficient current-track coverage;
  do not wait for all nine slots.
- Apply pause, resume, seek, skip, and drift corrections using the active
  generation.
- On disconnection, stop local Jam audio, reconnect with bounded backoff, and
  reconcile authoritative state.

Members may add songs and leave. Owners control shared playback and queue
order. Clearly explain that stopping local listening does not end the room;
ending rooms and transferring ownership require later backend support.

## 4. Nielsen usability requirements

Review the UI against [Nielsen's ten usability heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/).

| Principle | Required behavior |
|---|---|
| Status | Show buffering, buffer coverage, connection state, participant readiness, and pending saves. |
| Familiar language | Use song, queue, room, owner, and ready; put protocol details in optional diagnostics. |
| Control | Allow cancellation, correction of edits, local playback stopping, and member departure. |
| Consistency | Keep controls, labels, navigation, and playback behavior consistent across devices. |
| Prevention | Validate input, prevent duplicate submissions, explain unavailable actions, and confirm destructive deletion. |
| Recognition | Keep the current song, room role, queue, and available actions visible. |
| Efficiency | Provide keyboard operation, discoverable shortcuts, playlist actions, and invitation copying. |
| Focus | Keep music and group activity central; collapse buffer diagnostics by default. |
| Recovery | Preserve input, explain failures, offer appropriate retry actions, and distinguish playback failures from prefetch failures. |
| Help | Explain audio activation, room permissions, reconnecting, and data-saving behavior. |

Require accessible dialogs, labeled controls, visible focus, sufficient
contrast, touch targets of at least 44 pixels, reduced-motion support, and
screen-reader announcements for significant state changes.

## 5. Tests, deployment, and delivery

### Automated buffer tests

Use Vitest to verify slot mapping, boundary handling, rotation, repeated songs,
target durations, prioritization, cancellation, cache eviction, resource
limits, and stale media-version handling.

Verify independently decoded chunks have the expected sample counts and cover
consecutive source intervals. Test variable-bitrate input and nonzero chunk
offsets to catch the existing byte-slicing failure.

### Playwright acceptance tests

Run real browser flows through the gateway with generated non-silent audio
fixtures:

- Fetch manifests and chunks, decode audio, start playback, and verify
  advancing engine position and nonzero audio signal.
- Verify pause/resume, seeking, volume, track changes, and navigation persistence.
- Exercise playlists longer than nine songs and verify requests match the
  active window.
- Advance and reverse through tracks; verify rotation, useful-cache reuse,
  cancellation, and eviction.
- Test tracks shorter than a slot target and tracks longer than three minutes.
- Apply slow-network and request-failure conditions; current playback must
  take priority over neighbor prefetch.
- Test low-storage and memory-fallback policies through controlled
  storage-adapter failures.
- Create independent owner/member browser contexts; verify real media
  preparation, matching `PLAY_AT` schedules, owner controls, and reconnect
  reconciliation.
- Test laptop, tablet, and mobile layouts, keyboard interaction, and
  serious/critical axe findings.

Use the full suite in Chromium in staging, with Firefox/WebKit playback and
navigation smoke checks before release. Save Playwright traces, screenshots,
and service logs on failure.

Headless tests establish delivery, buffering, decoding, and scheduling
behavior. Physical laptop/phone testing remains necessary for audible
synchronization, mobile interruptions, and background-tab behavior.

### Delivery sequence

1. Record the product brief, design system, and revised plan.
2. Implement and test the Streaming chunk contract.
3. Build the responsive app shell, demo identity, and frontend container.
4. Implement the nine-slot buffer and solo listening experience.
5. Add discovery, playlists, lyrics, waveform, and synchronized Jams.
6. Complete Playwright, accessibility, responsive, and physical-device verification.
7. Commit and push meaningful units: chunk delivery; frontend foundation;
   adaptive buffering; listening/playlists; Jams; tests/documentation.

Integrate the frontend through root Compose and the existing gateway. Connect
browser tests to `tests/e2e/run.sh`. Keep live GitLab publishing verification
pending until authenticated access is available.
