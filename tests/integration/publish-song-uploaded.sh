#!/bin/sh
# Publishes one SongUploaded event (contracts/events/song-uploaded.schema.json)
# to syncwave.events through the RabbitMQ management API, the way the Upload
# Service will. Lets you try Lyrics and Waveform end to end without Upload.
#
# Usage (from the repo root, with `docker compose up -d` running):
#   sh tests/integration/publish-song-uploaded.sh <song_id> <audio_key> [lyrics_key] [title] [artist]
#
#   EVENT_ID=<uuid>  reuse an event_id, e.g. to simulate a duplicate delivery
#   MOOD=<mood>      add a mood label, e.g. calm, mellow, upbeat or energetic
#   HOST=<host>      where RabbitMQ's management API is published (default: localhost)
set -eu

if [ $# -lt 2 ]; then
  sed -n '2,11p' "$0"
  exit 2
fi
song_id=$1
audio_key=$2
lyrics_key=${3:-}
title=${4:-Demo}
artist=${5:-SyncWave Artist}
host=${HOST:-localhost}

new_uuid() {
  if [ -r /proc/sys/kernel/random/uuid ]; then
    cat /proc/sys/kernel/random/uuid
  else
    python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null ||
      python -c 'import uuid; print(uuid.uuid4())'
  fi
}
event_id=${EVENT_ID:-$(new_uuid)}

lyrics_field=""
if [ -n "$lyrics_key" ]; then
  lyrics_field=$(printf ', "lyrics_reference": "%s"' "$lyrics_key")
fi
mood_field=""
if [ -n "${MOOD:-}" ]; then
  mood_field=$(printf ', "mood": "%s"' "$MOOD")
fi
event=$(printf '{"event_id": "%s", "event_type": "SongUploaded", "version": 1, "song_id": "%s", "timestamp": "%s", "producer": "upload", "correlation_id": "%s", "payload": {"audio_reference": "%s", "title": "%s", "artist": "%s"%s%s}}' \
  "$event_id" "$song_id" "$(date -u +%Y-%m-%dT%H:%M:%S.000Z)" "$event_id" "$audio_key" "$title" "$artist" "$lyrics_field" "$mood_field")

# The management API takes the message body as a string; base64 avoids escaping it.
body=$(printf '%s' "$event" | base64 | tr -d '\n')
curl -fsS -u syncwave:syncwave -H 'content-type: application/json' \
  -d "{\"routing_key\": \"song.uploaded\", \"payload\": \"$body\", \"payload_encoding\": \"base64\", \"properties\": {\"content_type\": \"application/json\", \"delivery_mode\": 2, \"message_id\": \"$event_id\", \"type\": \"SongUploaded\"}}" \
  "http://$host:15672/api/exchanges/%2F/syncwave.events/publish"
echo
echo "published SongUploaded event_id=$event_id song_id=$song_id"
