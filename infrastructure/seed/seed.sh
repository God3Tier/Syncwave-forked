#!/bin/sh
# Loads the demo song into a local stack, the way the Upload Service would:
# put the audio and lyrics in S3, then publish SongUploaded. Catalogue,
# Lyrics and Waveform pick it up from there (Scenario 2 choreography).
#
# Runs as the one-shot `seed` service on every `docker compose up`. The song
# and event IDs are fixed, so a repeat is a duplicate delivery that the
# idempotent consumers skip. It never fails the stack: if seeding does not
# work, the log says so and everything else still starts.
set -u

SONG_ID=7d1a5e0c-4b9f-4c3e-9a8d-1f2b3c4d5e6f
EVENT_ID=3c9e2b71-8f4a-4d6b-a1e5-6b7c8d9e0f12
BUCKET_URL=http://s3:9000/syncwave-audio

put() {
  curl -fsS --retry 5 --retry-all-errors --retry-delay 2 \
    --aws-sigv4 aws:amz:us-east-1:s3 --user syncwave:syncwave-secret \
    --upload-file "$1" "$BUCKET_URL/$2"
}

if put /seed/daisy-bell.mp3 "audio/$SONG_ID.mp3" &&
  put /seed/daisy-bell.lrc "lyrics/$SONG_ID.lrc" &&
  EVENT_ID=$EVENT_ID HOST=rabbitmq sh /scripts/publish-song-uploaded.sh \
    "$SONG_ID" "audio/$SONG_ID.mp3" "lyrics/$SONG_ID.lrc" \
    "Daisy Bell (Bicycle Built for Two)" "Edward M. Favor"; then
  echo "seeded demo song $SONG_ID"
else
  echo "WARNING: could not seed the demo song; add songs by hand (README.md)" >&2
fi
exit 0
