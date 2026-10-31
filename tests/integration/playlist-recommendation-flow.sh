#!/bin/sh
# Playlist + Recommendation + Jam flow: does the Playlist Service work through
# the gateway, does Recommendation return Catalogue songs, and does Jam copy a
# Playlist's order into its queue (Jam -> Playlist gRPC GetPlaylist)?
#
# Needs at least 3 READY songs in the Catalogue (publish them with
# tests/integration/publish-song-uploaded.sh, or run the Lyrics/Waveform flow).
# It creates its own playlist and Jam, and deletes the playlist when it is done.
#
# Usage (from the repo root, with `docker compose up -d --wait` running):
#   sh tests/integration/playlist-recommendation-flow.sh            # against localhost
#   sh tests/integration/playlist-recommendation-flow.sh docker     # in CI, Docker-in-Docker host
set -u
HOST="${1:-localhost}"
API="http://$HOST:8080/api"
JAM_TOKEN="${JAM_TOKEN:-local-jam-member-token}"
OWNER="${OWNER_ID:-11111111-1111-4111-8111-111111111111}"
UNKNOWN_SONG="00000000-0000-4000-8000-000000000000"
failures=0
body=""
status=""

pass() { echo "ok    $1"; }
fail() {
  echo "FAIL  $1${2:+  ($2)}"
  failures=$((failures + 1))
}

# request METHOD URL [JSON_BODY] [extra curl args]: sets $status and $body.
request() {
  method=$1
  url=$2
  data=${3:-}
  shift 2
  [ $# -gt 0 ] && shift
  out=$(curl -sS --max-time 10 -X "$method" -w '\n%{http_code}' \
    -H 'content-type: application/json' "$@" ${data:+-d "$data"} "$url" 2>/dev/null)
  status=$(printf '%s' "$out" | tail -n 1)
  body=$(printf '%s' "$out" | sed '$d')
}

expect() { # expect LABEL WANTED_STATUS
  if [ "$status" = "$2" ]; then pass "$1"; else fail "$1" "wanted HTTP $2, got $status"; fi
}

field() { # field NAME: first string value of "NAME" in $body
  printf '%s' "$body" | grep -o "\"$1\":\"[^\"]*\"" | head -n 1 | cut -d'"' -f4
}

# The song ids of a playlist or Jam response, in the order they appear.
song_ids() { printf '%s' "$body" | grep -o '"song_id":"[^"]*"' | cut -d'"' -f4 | tr '\n' ' '; }

# --- Songs to use: the first three READY songs in the Catalogue ------------
request GET "$API/catalogue/songs?processing_status=READY&limit=3"
songs=$(song_ids)
set -- $songs
if [ $# -lt 3 ]; then
  fail "catalogue has 3 READY songs" "found $#; see the header of this script"
  echo "$failures check(s) failed"
  exit 1
fi
s1=$1 s2=$2 s3=$3
pass "catalogue has 3 READY songs"

# --- Playlist through the gateway ------------------------------------------
request POST "$API/playlist/playlists" "{\"owner_id\":\"$OWNER\",\"name\":\"integration flow\"}"
expect "playlist: create" 201
pid=$(field playlist_id)
[ -n "$pid" ] || {
  fail "playlist: create returned a playlist_id"
  echo "$failures check(s) failed"
  exit 1
}
P="$API/playlist/playlists/$pid"

for s in "$s1" "$s2" "$s3"; do
  request POST "$P/songs" "{\"song_id\":\"$s\"}"
  expect "playlist: add song" 200
done
request POST "$P/songs" "{\"song_id\":\"$s1\"}"
expect "playlist: adding the same song twice is refused" 409
request POST "$P/songs" "{\"song_id\":\"$UNKNOWN_SONG\"}"
expect "playlist: unknown song is refused (Catalogue check)" 404

request GET "$P"
expect "playlist: get" 200
if [ "$(song_ids)" = "$s1 $s2 $s3 " ]; then pass "playlist: songs are in the order added"; else fail "playlist: order" "$(song_ids)"; fi

request POST "$P/shuffle"
expect "playlist: shuffle" 200
shuffled=$(song_ids)
if [ "$shuffled" != "$s1 $s2 $s3 " ]; then pass "playlist: shuffle changed the order"; else fail "playlist: shuffle changed the order"; fi
request GET "$P"
if [ "$(song_ids)" = "$shuffled" ]; then pass "playlist: shuffled order is saved"; else fail "playlist: shuffled order is saved"; fi

request PUT "$P/songs" "{\"song_ids\":[\"$s3\",\"$s2\",\"$s1\"]}"
expect "playlist: reorder" 200
if [ "$(song_ids)" = "$s3 $s2 $s1 " ]; then pass "playlist: reorder result"; else fail "playlist: reorder result" "$(song_ids)"; fi

# --- Jam imports the playlist over gRPC (Jam -> Playlist GetPlaylist) -------
request POST "$API/jam/jams" "{\"owner_id\":\"$OWNER\",\"playlist_id\":\"$pid\"}" -H "X-Jam-Token: $JAM_TOKEN"
expect "jam: create from playlist" 201
if [ "$(song_ids)" = "$s3 $s2 $s1 " ]; then pass "jam: queue matches the playlist order"; else fail "jam: queue matches the playlist order" "$(song_ids)"; fi
request POST "$API/jam/jams" "{\"owner_id\":\"$OWNER\",\"playlist_id\":\"$UNKNOWN_SONG\"}" -H "X-Jam-Token: $JAM_TOKEN"
expect "jam: unknown playlist is refused" 404

# --- Recommendation through the gateway ------------------------------------
request GET "$API/recommendation/recommendations?limit=3"
expect "recommendation: without location" 200
printf '%s' "$body" | grep -q '"weather_used":false' && pass "recommendation: no location -> weather not used" || fail "recommendation: no location -> weather not used"
rec=$(song_ids)
[ -n "$rec" ] && pass "recommendation: returns songs" || fail "recommendation: returns songs"
request GET "$API/recommendation/recommendations?lat=1.35&lon=103.82&limit=3"
expect "recommendation: with location (weather up or down, still 200)" 200
request GET "$API/recommendation/recommendations?lat=1.35"
expect "recommendation: lat without lon is refused" 400

# --- Clean up --------------------------------------------------------------
request DELETE "$P"
expect "playlist: delete" 204
request GET "$P"
expect "playlist: gone after delete" 404

if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
