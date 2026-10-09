#!/bin/sh
# Smoke test for the whole stack: is every piece up and wired together?
# CI runs it on the staging branch (root .gitlab-ci.yml, `integration` job).
#
# Usage (from the repo root, with `docker compose up -d` running):
#   sh tests/integration/smoke.sh            # against localhost
#   sh tests/integration/smoke.sh docker     # in CI, Docker-in-Docker host
set -u
HOST="${1:-localhost}"
failures=0

get() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null --max-time 5 "$1"
  else
    wget -q -O /dev/null -T 5 "$1"
  fi
}

check() {
  if get "$2" 2>/dev/null; then
    echo "ok    $1"
  else
    echo "FAIL  $1  ($2)"
    failures=$((failures + 1))
  fi
}

check "gateway"                     "http://$HOST:8080/healthz"
check "s3"                          "http://$HOST:9000/health"
check "rabbitmq: events exchange"   "http://syncwave:syncwave@$HOST:15672/api/exchanges/%2F/syncwave.events"
check "rabbitmq: lyrics queue"      "http://syncwave:syncwave@$HOST:15672/api/queues/%2F/lyrics.song-uploaded"
check "rabbitmq: waveform queue"    "http://syncwave:syncwave@$HOST:15672/api/queues/%2F/waveform.song-uploaded"

# Every service that exists must answer /health through the gateway.
for dir in services/*/; do
  name=$(basename "$dir")
  [ "$name" = "_template" ] && continue
  check "service: $name" "http://$HOST:8080/api/$name/health"
done
if [ -d frontend ]; then
  check "frontend" "http://$HOST:8080/"
fi

if [ "$failures" -gt 0 ]; then
  echo "$failures check(s) failed"
  exit 1
fi
echo "all checks passed"
