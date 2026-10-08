# End-to-end tests (the three scenarios)

Placeholder for automated browser tests of the three key scenarios
(plan.md §1), e.g. with Playwright:

1. **Discover & Listen**: search, open a song, playback starts, lyrics and
   waveform load.
2. **Upload & Process**: upload a song, and lyrics and waveform reach
   `READY` within a time limit.
3. **Create & Synchronise a Jam**: two browser contexts join one Jam and
   both receive the same `PLAY_AT(T)`.

To plug into CI, add an executable `tests/e2e/run.sh` that takes the stack's
host as its first argument (`docker` in CI, `localhost` locally). The
staging `integration` job runs it automatically once the file exists.

Automated e2e testing of the scenarios is listed in the brief as an
eligible self-directed research item. Agree with the team before
committing to it.
