#!/bin/sh
# Builds and pushes $SERVICE's image, at most once per content hash.
#
#   1. Work out the content tag (ci/scripts/image-tag.sh).
#   2. If the registry already has that tag, skip the build: this exact
#      source was built by an earlier pipeline.
#   3. Otherwise build with the shared `contracts` build context, reusing
#      layers cached in the registry, and push.
#   4. On dev/staging/main ($PROMOTE_TAG set), also point the branch tag
#      (e.g. :staging) at this image. Nothing is rebuilt; only a manifest
#      is written. The staging integration tests run the :staging images.
#
# Writes IMAGE_TAG to build.env, which later jobs receive as a variable.
set -eu

IMAGE="$CI_REGISTRY_IMAGE/$SERVICE"
TAG=$(sh ci/scripts/image-tag.sh)

echo "$CI_REGISTRY_PASSWORD" | docker login --username "$CI_REGISTRY_USER" --password-stdin "$CI_REGISTRY"

if docker buildx imagetools inspect "$IMAGE:$TAG" >/dev/null 2>&1; then
  echo "$IMAGE:$TAG already exists - skipping build."
else
  # The docker-container driver supports exporting the layer cache to the registry.
  docker buildx create --use --driver docker-container >/dev/null
  docker buildx build \
    --platform linux/amd64 \
    --build-context contracts=contracts \
    --cache-from "type=registry,ref=$IMAGE:buildcache" \
    --cache-to "type=registry,ref=$IMAGE:buildcache,mode=max" \
    --label "org.opencontainers.image.source=$CI_PROJECT_URL" \
    --label "org.opencontainers.image.revision=$CI_COMMIT_SHA" \
    --tag "$IMAGE:$TAG" \
    --push \
    "$SERVICE_DIR"
fi

if [ -n "${PROMOTE_TAG:-}" ]; then
  docker buildx imagetools create --tag "$IMAGE:$PROMOTE_TAG" "$IMAGE:$TAG"
  echo "$IMAGE:$PROMOTE_TAG -> $TAG"
fi

echo "IMAGE_TAG=$TAG" > build.env
