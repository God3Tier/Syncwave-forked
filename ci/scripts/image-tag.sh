#!/bin/sh
# Prints the content-addressed image tag for $SERVICE_DIR.
#
# The tag is a hash of the git tree objects of the service folder and of the
# contract paths its image is built against ($CONTRACT_PATHS, passed in by
# the root pipeline). Identical source gives an identical tag on any branch
# and any commit, so the image built and tested in the merge request is the
# exact image that dev, staging and main later reuse ("build once").
set -eu
: "${SERVICE_DIR:?SERVICE_DIR must be set}"

for path in "$SERVICE_DIR" ${CONTRACT_PATHS:-}; do
  printf '%s %s\n' "$path" "$(git rev-parse "HEAD:$path" 2>/dev/null || echo absent)"
done | sha256sum | cut -c1-16
