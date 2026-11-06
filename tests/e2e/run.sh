#!/bin/sh
set -eu

project_name="${COMPOSE_PROJECT_NAME:-syncwave}"
container_name="${project_name}-playwright-e2e"
network_name="${project_name}_default"

cleanup() {
  mkdir -p tests/e2e/artifacts
  docker cp "$container_name:/workspace/tests/e2e/artifacts/." tests/e2e/artifacts/ \
    >/dev/null 2>&1 || true
  docker rm --force "$container_name" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM
cleanup

docker run --detach \
  --name "$container_name" \
  --network "$network_name" \
  mcr.microsoft.com/playwright/python:v1.56.0-noble \
  sleep infinity >/dev/null

docker exec "$container_name" mkdir -p \
  /workspace/tests/e2e/artifacts \
  /workspace/services/upload/samples \
  /workspace/infrastructure/seed
docker cp tests/e2e/test_app.py "$container_name:/workspace/tests/e2e/test_app.py"
docker cp services/upload/samples/upload-test.mp3 \
  "$container_name:/workspace/services/upload/samples/upload-test.mp3"
docker cp infrastructure/seed/daisy-bell.lrc \
  "$container_name:/workspace/infrastructure/seed/daisy-bell.lrc"

docker exec --workdir /workspace "$container_name" \
  python tests/e2e/test_app.py --base-url http://gateway:8080
