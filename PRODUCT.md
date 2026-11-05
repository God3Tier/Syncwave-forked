# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

SyncWave is primarily for groups of friends who want to discover music, build a shared queue, and listen together in real time from their own devices. The repository is a school project, but the product experience should present as a credible consumer music app rather than a technical demonstration.

## Product Purpose

SyncWave combines a personal music library with browser-based synchronized listening rooms. A successful experience gets someone from discovery or a playlist into a shared Jam quickly, keeps the current track and queue understandable, and makes connection or readiness problems recoverable without exposing protocol complexity.

## Positioning

Unlike a conventional solo streaming library, SyncWave makes synchronized group listening a first-class workflow: friends join from a link, contribute to one queue, see who is ready, and hear owner-controlled playback on the same timeline.

## Operating Context

- Friends browse recommendations, search the catalogue, inspect tracks, and play music individually.
- People upload audio and optional timed lyrics, then follow processing status for catalogue, lyrics, and waveform assets.
- People create and manage playlists, reorder tracks, and use a playlist as the starting queue for a Jam.
- A host creates a Jam, shares an invite link, manages the queue, and controls synchronized playback.
- Participants enable audio, join the shared queue, and receive clear connection, preparation, and readiness feedback.
- The app is evaluated on desktop, tablet, and mobile browsers through a local Compose environment.

## Capabilities and Constraints

- Preserve the existing React, TypeScript, Vite, Tailwind CSS, same-origin gateway integration, routes, service contracts, and browser-based audio behavior.
- Preserve discovery, weather-aware recommendations, search fallback, upload processing, song detail, lyrics, waveform seeking, playlists, solo playback, Jam membership, queue operations, readiness decisions, and Sync WebSocket behavior.
- Authentication is intentionally a local demo identity stored in browser storage; no production auth service exists yet.
- Catalogue entries do not currently provide cover artwork, so the product needs a coherent generated-art fallback.
- Solo Streaming uses a versioned manifest and independently decodable WAV chunks for an adaptive nine-position browser buffer. Jam retains whole-track delivery for its clock-synchronised engine.
- AWS deployment, live CI/GitLab verification, production secrets, and other online-only checks are outside the current local completion scope.

## Brand Commitments

- Product name: SyncWave.
- The experience should feel familiar to users of Spotify, Deezer, and SoundCloud while remaining its own product.
- Consumer music language takes priority over infrastructure terminology. Detailed synchronization data belongs in optional diagnostics rather than the primary workflow.

## Evidence on Hand

- Product and architecture plans: `plan.md`, `FRONTEND_PLAN.md`, and `INTEGRATION_PLAN.md`.
- Implemented frontend routes and workflows under `frontend/src`.
- Browser scenario coverage in `tests/e2e/test_app.py`.
- Local backend and integration scenarios under `tests/integration`.
- No real cover-art library, customer testimonials, commercial claims, or production identity assets are available and none should be fabricated.

## Product Principles

1. Put listening first: the current track, queue, and next meaningful action stay obvious.
2. Make listening together feel social and lightweight, not like operating distributed infrastructure.
3. Reveal technical state only when it helps someone recover, understand readiness, or verify synchronization.
4. Preserve familiar media-control behavior across solo playback and Jams.
5. Treat loading, processing, disconnected, empty, and partial-success states as guided workflows.

## Accessibility & Inclusion

The frontend must support keyboard navigation, visible focus, programmatic labels, sufficient contrast, reduced motion, 44-pixel touch targets where practical, logical reading order, and responsive layouts without horizontal clipping at 1440, 768, and 390 pixels.
