#!/usr/bin/env bash
# Build and tag both application images.
#
# Usage: build.sh [version]
#   version defaults to the current git short SHA, falling back to "latest"
#   in a non-git checkout. Every build is tagged both <version> and :latest.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

require_cmd docker
load_env

VERSION="${1:-$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "latest")}"
BACKEND_REF="$(image_ref backend "$VERSION")"
FRONTEND_REF="$(image_ref frontend "$VERSION")"
BACKEND_LATEST="$(image_ref backend latest)"
FRONTEND_LATEST="$(image_ref frontend latest)"

log "Building backend image: $BACKEND_REF"
docker build \
    -f "$SCRIPT_DIR/Dockerfile.backend" \
    -t "$BACKEND_REF" \
    -t "$BACKEND_LATEST" \
    "$REPO_ROOT"

log "Building frontend image: $FRONTEND_REF"
docker build \
    -f "$SCRIPT_DIR/Dockerfile.frontend" \
    --build-arg "VITE_API_BASE_URL=${VITE_API_BASE_URL:-http://localhost:8000}" \
    -t "$FRONTEND_REF" \
    -t "$FRONTEND_LATEST" \
    "$REPO_ROOT"

echo "$VERSION" > "$STATE_DIR/last_built_version"
log "Built version $VERSION: $BACKEND_REF, $FRONTEND_REF"
