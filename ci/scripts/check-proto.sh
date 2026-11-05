#!/bin/sh
# Lints the gRPC contracts. In a merge request, also fails if the change
# would break existing gRPC clients, compared with the MR's target branch.
set -eu
cd "$(git rev-parse --show-toplevel)"

if ! find contracts/grpc -name '*.proto' | grep -q .; then
  echo "No .proto files yet - nothing to check."
  exit 0
fi

buf lint contracts/grpc
buf build contracts/grpc -o /dev/null

target="${CI_MERGE_REQUEST_TARGET_BRANCH_NAME:-}"
if [ -z "$target" ]; then
  echo "Not a merge request - skipping breaking-change check."
  exit 0
fi

git fetch --quiet --depth=1 origin "$target"
base=$(mktemp -d)
git archive FETCH_HEAD contracts/grpc 2>/dev/null | tar -x -C "$base" 2>/dev/null || true
if ! find "$base/contracts/grpc" -name '*.proto' 2>/dev/null | grep -q .; then
  echo "$target has no .proto files yet - nothing to compare against."
  exit 0
fi

buf breaking contracts/grpc --against "$base/contracts/grpc"
echo "No breaking changes against $target."
