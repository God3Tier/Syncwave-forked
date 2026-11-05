#!/bin/sh
# Edge cases for the Playlist and Recommendation services, through the gateway:
# bad input, insert positions, reorder errors, shuffle sizes, paging, parallel
# edits, and Recommendation query limits. Nothing here stops a container; see
# playlist-recommendation-resilience.sh for that.
#
# Needs at least 4 READY songs in the Catalogue. It uses its own owner id (one
# per run) and deletes every playlist it created when it finishes.
#
# Usage (from the repo root, with `docker compose up -d --wait` running):
#   sh tests/integration/playlist-recommendation-edge-cases.sh [host]
set -u
HOST="${1:-localhost}"
API="http://$HOST:8080/api"
P="$API/playlist/playlists"
R="$API/recommendation/recommendations"
OWNER="33333333-3333-4333-8333-$(printf '%012d' "$(date +%s)")"
UNKNOWN="00000000-0000-4000-8000-000000000000"
failures=0
body=""
status=""

pass() { echo "ok    $1"; }
fail() {
  echo "FAIL  $1${2:+  ($2)}"
  failures=$((failures + 1))
}

# request METHOD URL [JSON_BODY]: sets $status and $body.
request() {
  out=$(curl -sS --max-time 10 -X "$1" -w '\n%{http_code}' -H 'content-type: application/json' \
    ${3:+-d "$3"} "$2" 2>/dev/null)
  status=$(printf '%s' "$out" | tail -n 1)
  body=$(printf '%s' "$out" | sed '$d')
}

expect() { # expect LABEL WANTED_STATUS
  if [ "$status" = "$2" ]; then pass "$1"; else fail "$1" "wanted HTTP $2, got $status"; fi
}

expect_order() { # expect_order LABEL "id id id "
  if [ "$(song_ids)" = "$2" ]; then pass "$1"; else fail "$1" "wanted [$2] got [$(song_ids)]"; fi
}

field() { printf '%s' "$body" | grep -o "\"$1\":\"[^\"]*\"" | head -n 1 | cut -d'"' -f4; }
song_ids() { printf '%s' "$body" | grep -o '"song_id":"[^"]*"' | cut -d'"' -f4 | tr '\n' ' '; }
positions() { printf '%s' "$body" | grep -o '"position":[0-9]*' | cut -d: -f2 | tr '\n' ' '; }

new_playlist() { # sets $pid
  request POST "$P" "{\"owner_id\":\"$OWNER\",\"name\":\"edge case\"}"
  pid=$(field playlist_id)
}

cleanup() {
  request GET "$P?owner_id=$OWNER&limit=100"
  for id in $(printf '%s' "$body" | grep -o '"playlist_id":"[^"]*"' | cut -d'"' -f4); do
    curl -s -o /dev/null --max-time 10 -X DELETE "$P/$id"
  done
}
trap cleanup EXIT

request GET "$API/catalogue/songs?processing_status=READY&limit=4"
set -- $(song_ids)
if [ $# -lt 4 ]; then
  fail "catalogue has 4 READY songs" "found $#"
  echo "$failures check(s) failed"
  exit 1
fi
s1=$1 s2=$2 s3=$3 s4=$4

# --- Create / read / rename / delete: bad input ------------------------------
long=$(printf 'a%.0s' $(seq 1 100))
request POST "$P" "{\"owner_id\":\"$OWNER\",\"name\":\"$long\"}"
expect "create: 100-character name is accepted" 201
request POST "$P" "{\"owner_id\":\"$OWNER\",\"name\":\"${long}a\"}"
expect "create: 101-character name is refused" 400
request POST "$P" "{\"owner_id\":\"$OWNER\",\"name\":\"\"}"
expect "create: empty name is refused" 400
request POST "$P" '{"owner_id":"not-a-uuid","name":"n"}'
expect "create: bad owner_id is refused" 400
request POST "$P" '{"name":"n"}'
expect "create: missing owner_id is refused" 400
request POST "$P" '{bad json'
expect "create: malformed JSON is refused" 400
request GET "$P/not-a-uuid"
expect "get: bad id is refused" 400
request GET "$P/$UNKNOWN"
expect "get: unknown id is 404" 404
request PATCH "$P/$UNKNOWN" '{"name":"x"}'
expect "rename: unknown id is 404" 404
request DELETE "$P/$UNKNOWN"
expect "delete: unknown id is 404" 404

new_playlist
request PATCH "$P/$pid" '{"name":"renamed"}'
expect "rename: ok" 200
[ "$(field name)" = "renamed" ] && pass "rename: name changed" || fail "rename: name changed"
request PATCH "$P/$pid" '{"name":""}'
expect "rename: empty name is refused" 400

# --- Shuffle on 0, 1 and 2 songs ---------------------------------------------
request POST "$P/$pid/shuffle"
expect "shuffle: empty playlist is fine" 200
request POST "$P/$pid/songs" "{\"song_id\":\"$s1\"}"
request POST "$P/$pid/shuffle"
expect "shuffle: one song is fine" 200
expect_order "shuffle: one song stays put" "$s1 "
request POST "$P/$pid/songs" "{\"song_id\":\"$s2\"}"
before=$s1" "$s2" "
changed=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  request POST "$P/$pid/shuffle"
  now=$(song_ids)
  [ "$now" != "$before" ] && changed=$((changed + 1))
  before=$now
done
[ "$changed" -eq 10 ] && pass "shuffle: two songs change order every time (10 of 10)" || fail "shuffle: two songs change order every time" "changed $changed of 10"

# --- Insert positions --------------------------------------------------------
new_playlist
request POST "$P/$pid/songs" "{\"song_id\":\"$s1\",\"position\":5}"
expect "add: position past the end of an empty playlist is refused" 400
request POST "$P/$pid/songs" "{\"song_id\":\"$s1\",\"position\":-1}"
expect "add: negative position is refused" 400
request POST "$P/$pid/songs" '{"song_id":"not-a-uuid"}'
expect "add: bad song_id is refused" 400
request POST "$P/$pid/songs" "{\"song_id\":\"$s1\",\"position\":0}"
request POST "$P/$pid/songs" "{\"song_id\":\"$s2\",\"position\":0}"
expect_order "add: position 0 inserts at the front" "$s2 $s1 "
request POST "$P/$pid/songs" "{\"song_id\":\"$s3\",\"position\":1}"
expect_order "add: position 1 inserts in the middle" "$s2 $s3 $s1 "
request POST "$P/$pid/songs" "{\"song_id\":\"$s4\",\"position\":3}"
expect_order "add: position at the end appends" "$s2 $s3 $s1 $s4 "
[ "$(positions)" = "0 1 2 3 " ] && pass "add: positions have no gaps" || fail "add: positions have no gaps" "$(positions)"

# --- Reorder errors ----------------------------------------------------------
request PUT "$P/$pid/songs" "{\"song_ids\":[\"$s1\"]}"
expect "reorder: missing songs are refused" 400
request PUT "$P/$pid/songs" "{\"song_ids\":[\"$s1\",\"$s1\",\"$s2\",\"$s3\"]}"
expect "reorder: a duplicate is refused" 400
request PUT "$P/$pid/songs" '{"song_ids":[]}'
expect "reorder: empty list is refused" 400
request GET "$P/$pid"
expect_order "reorder: failed attempts changed nothing" "$s2 $s3 $s1 $s4 "

# --- Remove ------------------------------------------------------------------
request DELETE "$P/$pid/songs/$UNKNOWN"
expect "remove: song not in playlist is 404" 404
request DELETE "$P/$pid/songs/$s3"
expect "remove: ok" 200
expect_order "remove: others keep their order" "$s2 $s1 $s4 "
[ "$(positions)" = "0 1 2 " ] && pass "remove: positions have no gaps" || fail "remove: positions have no gaps" "$(positions)"

# --- Listing and paging ------------------------------------------------------
request GET "$P?owner_id=$OWNER&limit=2"
expect "list: first page" 200
first=$(printf '%s' "$body" | grep -o '"playlist_id":"[^"]*"' | wc -l | tr -d ' ')
[ "$first" -eq 2 ] && pass "list: limit=2 returns 2 playlists" || fail "list: limit=2 returns 2 playlists" "got $first"
request GET "$P?owner_id=$OWNER&limit=0"
expect "list: limit 0 is refused" 400
request GET "$P?owner_id=$OWNER&limit=101"
expect "list: limit 101 is refused" 400
request GET "$P"
expect "list: owner_id is required" 400
request GET "$P?owner_id=33333333-3333-4333-8333-000000000000"
printf '%s' "$body" | grep -q '"playlist_id"' && fail "list: another owner sees nothing" || pass "list: another owner sees nothing"

# --- Parallel edits ----------------------------------------------------------
new_playlist
codes=$(seq 1 20 | xargs -P 10 -I{} curl -s -o /dev/null -w '%{http_code}\n' -X POST "$P/$pid/songs" \
  -H 'content-type: application/json' -d "{\"song_id\":\"$s1\"}")
ok=$(printf '%s\n' "$codes" | grep -c '^200$')
dup=$(printf '%s\n' "$codes" | grep -c '^409$')
[ "$ok" -eq 1 ] && [ "$dup" -eq 19 ] && pass "parallel: 20 adds of one song give 1x200 and 19x409" || fail "parallel: 20 adds of one song" "200s=$ok 409s=$dup"

(
  for s in "$s2" "$s3" "$s4"; do
    curl -s -o /dev/null -X POST "$P/$pid/songs" -H 'content-type: application/json' -d "{\"song_id\":\"$s\"}" &
  done
  for _ in 1 2 3 4 5 6; do curl -s -o /dev/null -X POST "$P/$pid/shuffle" & done
  wait
)
request GET "$P/$pid"
[ "$(positions)" = "0 1 2 3 " ] && pass "parallel: adds and shuffles leave positions 0-3 with no gaps" || fail "parallel: positions" "$(positions)"
ids=$(song_ids | tr ' ' '\n' | grep -v '^$' | sort -u | wc -l | tr -d ' ')
[ "$ids" -eq 4 ] && pass "parallel: every song appears exactly once" || fail "parallel: every song appears exactly once" "unique=$ids"

# --- Recommendation query limits ---------------------------------------------
for q in "limit=0" "limit=51" "limit=abc" "lat=91&lon=0" "lat=-91&lon=0" "lat=0&lon=181" "lat=abc&lon=1" "lon=5"; do
  request GET "$R?$q"
  expect "recommendation: ?$q is refused" 400
done
request GET "$R?lat=-90&lon=-180&limit=50"
expect "recommendation: the extreme coordinates are accepted" 200
request GET "$R?limit=1"
n=$(printf '%s' "$body" | grep -o '"song_id"' | wc -l | tr -d ' ')
[ "$n" -eq 1 ] && pass "recommendation: limit=1 returns 1 song" || fail "recommendation: limit=1 returns 1 song" "got $n"
request GET "$R?limit=3"
a=$(song_ids)
request GET "$R?limit=3"
[ "$a" = "$(song_ids)" ] && pass "recommendation: same request, same result" || fail "recommendation: same request, same result"

if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
