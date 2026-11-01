#!/bin/sh
# Loads the demo songs (songs.txt) into a local stack, the way the Upload
# Service would: put the audio and lyrics in S3, then publish SongUploaded.
# Catalogue, Lyrics and Waveform pick them up from there (Scenario 2
# choreography).
#
# Runs as the one-shot `seed` service on every `docker compose up`. The song
# and event IDs are fixed, so a repeat is a duplicate delivery that the
# idempotent consumers skip. It never fails the stack: if seeding does not
# work, the log says so and everything else still starts.
set -u

BUCKET_URL=http://s3:9000/syncwave-audio

put() {
  curl -fsS --retry 5 --retry-all-errors --retry-delay 2 \
    --aws-sigv4 aws:amz:us-east-1:s3 --user syncwave:syncwave-secret \
    --upload-file "$1" "$BUCKET_URL/$2"
}

seed() {
  lyrics_key=""
  if [ -n "$lyrics" ]; then
    lyrics_key="lyrics/$song_id.lrc"
    put "/seed/$lyrics" "$lyrics_key" || return 1
  fi
  put "/seed/$audio" "audio/$song_id.mp3" &&
    EVENT_ID=$event_id MOOD=$mood HOST=rabbitmq sh /scripts/publish-song-uploaded.sh \
      "$song_id" "audio/$song_id.mp3" "$lyrics_key" "$title" "$artist"
}

while IFS='|' read -r audio lyrics title artist mood song_id event_id <&3; do
  case $audio in '' | '#'*) continue ;; esac
  if seed </dev/null; then
    echo "seeded demo song $song_id ($title)"
  else
    echo "WARNING: could not seed $title; add songs by hand (README.md)" >&2
  fi
done 3</seed/songs.txt
exit 0
