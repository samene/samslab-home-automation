#!/usr/bin/env bash
# Roll back to the previously deployed image tags and verify health.
#
# Usage: rollback.sh [version]
#   version defaults to the last version recorded before the most recent
#   deploy (deploy.sh writes this to .state/previous_version automatically).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

require_cmd docker
load_env

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    [ -f "$STATE_DIR/previous_version" ] || die "no previous version recorded — pass one explicitly: rollback.sh <version>"
    VERSION="$(cat "$STATE_DIR/previous_version")"
fi

BACKEND_REF="$(image_ref backend "$VERSION")"
FRONTEND_REF="$(image_ref frontend "$VERSION")"

for ref in "$BACKEND_REF" "$FRONTEND_REF"; do
    docker image inspect "$ref" >/dev/null 2>&1 || die "image not found locally: $ref (was it pruned by cleanup.sh?)"
done

log "Rolling back to version $VERSION ($BACKEND_REF, $FRONTEND_REF)..."
export APP_VERSION="$VERSION"
compose up -d

wait_for_container_health samslab-backend 120
wait_for_container_health samslab-frontend 60

if "$SCRIPT_DIR/verify.sh"; then
    echo "$VERSION" > "$STATE_DIR/current_version"
    log "Rollback to $VERSION succeeded and passed verification."
    exit 0
fi

die "Rollback to $VERSION started but failed verification — manual intervention required."
