#!/bin/sh
# What happens to Playlist, Recommendation and Jam when a dependency stops?
# STOPS AND RESTARTS containers of the local Compose stack, one at a time:
#   playlist (restart), catalogue, playlist, postgres.
# It restarts whatever it stopped, even when a check fails. Nothing is deleted
# and no volumes are touched. Do not run it against a stack other people use.
#
# Needs at least 2 READY songs in the Catalogue.
#
# Usage (from the repo root, with `docker compose up -d --wait` running):
#   sh tests/integration/playlist-recommendation-resilience.sh
set -u
HOST=localhost
API="http://$HOST:8080/api"
P="$API/playlist/playlists"
JAM_TOKEN="${JAM_TOKEN:-local-jam-member-token}"
OWNER="44444444-4444-4444-8444-$(printf '%012d' "$(date +%s)")"
failures=0
body=""
status=""
stopped=""

pass() { echo "ok    $1"; }
fail() {
  echo "FAIL  $1${2:+  ($2)}"
  failures=$((failures + 1))
}

request() { # request METHOD URL [JSON_BODY] [extra curl args]
  method=$1
  url=$2
  data=${3:-}
  shift 2
  [ $# -gt 0 ] && shift
  out=$(curl -sS --max-time 15 -X "$method" -w '\n%{http_code}' \
    -H 'content-type: application/json' "$@" ${data:+-d "$data"} "$url" 2>/dev/null)
  status=$(printf '%s' "$out" | tail -n 1)
  body=$(printf '%s' "$out" | sed '$d')
}

expect() { if [ "$status" = "$2" ]; then pass "$1"; else fail "$1" "wanted HTTP $2, got $status"; fi; }
field() { printf '%s' "$body" | grep -o "\"$1\":\"[^\"]*\"" | head -n 1 | cut -d'"' -f4; }
song_ids() { printf '%s' "$body" | grep -o '"song_id":"[^"]*"' | cut -d'"' -f4 | tr '\n' ' '; }

# wait_for URL SECONDS: wait until the URL answers 200.
wait_for() {
  i=0
  while [ "$i" -lt "$2" ]; do
    [ "$(curl -s -o /dev/null --max-time 3 -w '%{http_code}' "$1")" = "200" ] && return 0
    sleep 2
    i=$((i + 2))
  done
  return 1
}

stop_service() {
  docker compose stop "$1" >/dev/null 2>&1
  stopped="$stopped $1"
}

start_service() {
  docker compose start "$1" >/dev/null 2>&1
  stopped=$(printf '%s' "$stopped" | sed "s/ $1//")
}

restore() {
  for s in $stopped; do docker compose start "$s" >/dev/null 2>&1; done
  wait_for "$API/playlist/health" 90
  wait_for "$API/catalogue/health" 90
  wait_for "$API/jam/health" 90
  # Remove the test playlists (owner id is unique to this run).
  request GET "$P?owner_id=$OWNER&limit=100"
  for id in $(printf '%s' "$body" | grep -o '"playlist_id":"[^"]*"' | cut -d'"' -f4); do
    curl -s -o /dev/null --max-time 10 -X DELETE "$P/$id"
  done
}
trap restore EXIT

request GET "$API/catalogue/songs?processing_status=READY&limit=2"
set -- $(song_ids)
if [ $# -lt 2 ]; then
  fail "catalogue has 2 READY songs" "found $#"
  echo "$failures check(s) failed"
  exit 1
fi
s1=$1 s2=$2

request POST "$P" "{\"owner_id\":\"$OWNER\",\"name\":\"resilience\"}"
pid=$(field playlist_id)
request POST "$P/$pid/songs" "{\"song_id\":\"$s1\"}"
request POST "$P/$pid/songs" "{\"song_id\":\"$s2\"}"
request GET "$P/$pid"
[ "$(song_ids)" = "$s1 $s2 " ] && pass "setup: playlist with 2 songs" || fail "setup: playlist with 2 songs"

# --- 1. Playlist restarts: the data survives ---------------------------------
docker compose restart playlist >/dev/null 2>&1
wait_for "$API/playlist/health" 90 && pass "playlist: back up after a restart" || fail "playlist: back up after a restart"
request GET "$P/$pid"
expect "playlist: playlist still there after restart" 200
[ "$(song_ids)" = "$s1 $s2 " ] && pass "playlist: songs and order survive a restart" || fail "playlist: songs and order survive a restart"

# --- 2. Catalogue stopped ----------------------------------------------------
stop_service catalogue
sleep 3
request GET "$P/$pid"
expect "catalogue down: playlist get still works" 200
request POST "$P/$pid/shuffle"
expect "catalogue down: shuffle still works" 200
request PATCH "$P/$pid" '{"name":"while catalogue is down"}'
expect "catalogue down: rename still works" 200
request POST "$P" "{\"owner_id\":\"$OWNER\",\"name\":\"made while catalogue is down\"}"
expect "catalogue down: create still works" 201
request DELETE "$P/$pid/songs/$s1"
expect "catalogue down: remove still works" 200
request POST "$P/$pid/songs" "{\"song_id\":\"$s1\"}"
expect "catalogue down: adding a song is refused with 502" 502
printf '%s' "$body" | grep -q 'CATALOGUE_UNAVAILABLE' && pass "catalogue down: error code is CATALOGUE_UNAVAILABLE" || fail "catalogue down: error code" "$body"
request GET "$P/$pid"
[ "$(song_ids)" = "$s2 " ] && pass "catalogue down: the refused add stored nothing" || fail "catalogue down: the refused add stored nothing" "$(song_ids)"
request GET "$API/recommendation/recommendations?limit=3"
expect "catalogue down: recommendation is 502" 502
curl -s -o /dev/null --max-time 5 "$API/recommendation/health" && pass "catalogue down: recommendation stays alive" || fail "catalogue down: recommendation stays alive"
start_service catalogue
wait_for "$API/catalogue/health" 90 && pass "catalogue: back up" || fail "catalogue: back up"
request POST "$P/$pid/songs" "{\"song_id\":\"$s1\"}"
expect "catalogue back: adding a song works again" 200
request GET "$API/recommendation/recommendations?limit=3"
expect "catalogue back: recommendation works again" 200

# --- 3. Playlist stopped: Jam must fail cleanly ------------------------------
stop_service playlist
sleep 3
request POST "$API/jam/jams" "{\"owner_id\":\"$OWNER\",\"playlist_id\":\"$pid\"}" -H "X-Jam-Token: $JAM_TOKEN"
expect "playlist down: Jam refuses a playlist import with 503" 503
request POST "$API/jam/jams" "{\"owner_id\":\"$OWNER\"}" -H "X-Jam-Token: $JAM_TOKEN"
expect "playlist down: Jam can still create an empty Jam" 201
request GET "$API/recommendation/recommendations?limit=3"
expect "playlist down: recommendation is unaffected" 200
start_service playlist
wait_for "$API/playlist/health" 90 && pass "playlist: back up" || fail "playlist: back up"
request POST "$API/jam/jams" "{\"owner_id\":\"$OWNER\",\"playlist_id\":\"$pid\"}" -H "X-Jam-Token: $JAM_TOKEN"
expect "playlist back: Jam imports the playlist again (gRPC reconnects)" 201

# --- 4. Postgres stopped -----------------------------------------------------
stop_service postgres
sleep 3
request GET "$P/$pid"
if [ "$status" -ge 500 ] 2>/dev/null; then pass "postgres down: playlist get fails with $status"; else fail "postgres down: playlist get fails" "got $status"; fi
curl -s -o /dev/null --max-time 5 "$API/playlist/health" && pass "postgres down: playlist process stays alive" || fail "postgres down: playlist process stays alive"
request GET "$API/recommendation/recommendations?limit=3"
[ "$status" = "200" ] || [ "$status" = "502" ] && pass "postgres down: recommendation answers ($status)" || fail "postgres down: recommendation answers" "got $status"
start_service postgres
wait_for "$API/playlist/health" 90 && pass "postgres: playlist health after it returns" || fail "postgres: playlist health after it returns"
i=0
status=000
while [ "$i" -lt 60 ] && [ "$status" != "200" ]; do
  request GET "$P/$pid"
  [ "$status" = "200" ] || sleep 2
  i=$((i + 2))
done
expect "postgres back: playlist works again without a restart (within 60s)" 200
[ "$(song_ids)" = "$s2 $s1 " ] && pass "postgres back: data is unchanged" || fail "postgres back: data is unchanged" "$(song_ids)"

if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
