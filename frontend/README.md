# SyncWave frontend

The browser UI for all three scenarios. It is a React 19 + TypeScript single-page app built with Vite and styled with Tailwind CSS v4. In Docker Compose it is served by nginx as the `frontend` service, and the gateway routes `/` to it. The UI calls every service through the same origin at `/api/<service>/...`, so no CORS is needed.

| Page | Route | Services it uses |
|---|---|---|
| Discover | `/` | Recommendation (with optional browser geolocation for the weather signal), Catalogue |
| Search | `/search?q=` | Search. While Search is unreachable, it falls back to filtering READY Catalogue songs |
| Song / Now playing | `/songs/:id` | Catalogue, Streaming, Lyrics (synced highlighting), Waveform (seekable canvas) |
| Upload | `/upload` | Upload (multipart with progress), then polls Upload and Catalogue to show lyrics ∥ waveform processing |
| Playlists | `/playlists`, `/playlists/:id` | Playlist (create, rename, delete, add, remove, drag to reorder, shuffle), Catalogue for titles |
| Jam lobby / room | `/jam`, `/jam/:id` | Jam over HTTP and its room WebSocket; Sync WebSocket for clock sync, `PREPARE`/`READY`/`PLAY_AT`, drift corrections |

## Run it

The normal way is the whole stack from the repository root: `docker compose up -d --build --wait`, then open <http://localhost:8080>.

For fast UI work, run the Vite dev server against that running stack. It proxies `/api` (HTTP and WebSocket) to the gateway:

```sh
cd frontend
npm ci
npm run dev          # http://localhost:5173
```

To use a gateway other than `http://localhost:8080`, set `SYNCWAVE_GATEWAY`.

| Command | What it does |
|---|---|
| `npm run lint` | ESLint, including the React hooks and compiler rules |
| `npm run typecheck` | `tsc -b` |
| `npm test` | Vitest unit tests: clock-offset maths, protocol framing, API error parsing, search fallback, lyric and band decoding |
| `npm run build` | Production build into `dist/` |

## Identity and tokens

There is no auth service yet. Each browser makes up a `user_id` UUID and keeps it in localStorage, as proposed in `contracts/README.md`.

To act as a second Jam participant from the same machine, open the invite link with `?user=new`. That tab then keeps its own identity in sessionStorage. The sidebar's "switch identity" link does the same thing.

Jam and Sync use the local stack's mock tokens. You can override them at build time:

| Variable | Default |
|---|---|
| `VITE_JAM_MEMBER_TOKEN` | `local-jam-member-token` (a `member_token` returned by Jam takes precedence) |
| `VITE_SYNC_PARTICIPANT_TOKEN` | `local-sync-participant-token` |

## How a Jam plays in sync

`src/sync/syncSession.ts` is a TypeScript port of the Sync demo harness (`services/sync/src/sync_service/demo.py`). It plays the real stream instead of a test tone.

1. When the owner starts playback, every device opens `/api/sync/ws`. The browser only allows audio after a user gesture, so a device needs a tap on "Join Jam (Enable Audio)" before this happens.
2. The device estimates its clock offset from 5 `TIME_PING`/`TIME_PONG` samples. It takes the median of the 3 lowest-delay samples (`src/sync/clock.ts`), then sends a fresh ping every 15 s.
3. On `PREPARE` it downloads and decodes the `stream_url`, then sends `READY`.
4. On `PLAY_AT`, `RESUME_AT`, `PAUSE_AT` or `SEEK_TO` it converts the server time to local time and schedules Web Audio.
5. It reports `PLAYBACK_STATUS` every 2 s and applies `SYNC_CORRECTION` (a temporary rate change or a scheduled seek).
6. Messages from an older playback generation are ignored.

The owner's controls go through Jam, never directly to Sync. While Jam is `PREPARING`, the owner's page polls readiness. If listeners are still not ready when the prepare timeout passes, it shows the continue / wait / cancel prompt.

## Design

The frontend uses the **Shared Listening Desk** design system recorded in
[`DESIGN.md`](../DESIGN.md). It is a friends-first consumer music interface:
deep ink surfaces, warm paper text, coral actions, mint live state, bundled
Manrope typography, Lucide icons, and deterministic record-sleeve artwork when
the catalogue has no cover image.

Desktop uses a 15rem navigation rail and persistent player. Below 1024px the
rail becomes a compact header plus four-item bottom navigation. At mobile sizes,
music shelves scroll horizontally and Jam rooms switch between Queue and People
without compressing both panels into one column.

Design tokens live in `src/index.css`; reusable primitives and generated sleeve
art live in `src/components/ui.tsx`. The UI intentionally keeps drift, RTT,
generation, and buffer data secondary to the current song, queue, and friends.

## Known limitations

- **Streaming:** solo playback uses the versioned manifest and independently decodable ten-second WAV chunks. A two-download priority pool fills the complete −4…+4 logical queue window; whole-track playback remains available for the clock-synchronised Jam engine.
- **Search fallback:** Search falls back to the Catalogue when the Search service is unreachable.
- **Drift display:** the drift shown in the Jam room is the value Sync reports when it corrects this device. The client does not compute its own drift.
- **Deploy:** there is no ECS deploy job yet (see `.gitlab-ci.yml`).
