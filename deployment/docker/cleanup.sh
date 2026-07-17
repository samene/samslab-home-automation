#!/usr/bin/env bash
# Prune old image versions and dangling Docker resources so disk usage
# doesn't grow unbounded across repeated deploys. Never touches the image
# currently deployed, :latest, or (if present) the previous version rollback
# would need.
#
# Usage: cleanup.sh [--keep N]   (default: keep the 5 most recent tags)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

require_cmd docker
load_env

KEEP=5
if [ "${1:-}" = "--keep" ] && [ -n "${2:-}" ]; then
    KEEP="$2"
fi

protected_tags() {
    echo "latest"
    [ -f "$STATE_DIR/current_version" ] && cat "$STATE_DIR/current_version"
    [ -f "$STATE_DIR/previous_version" ] && cat "$STATE_DIR/previous_version"
}

prune_image_tags() {
    local repo="$1"
    local protected
    protected="$(protected_tags)"

    # Oldest-first list of every tag for this repo, one per line.
    local tags
    tags="$(docker images "$repo" --format '{{.CreatedAt}}|{{.Tag}}' | sort -r | awk -F'|' '{print $2}')"

    local kept=0
    while IFS= read -r tag; do
        [ -z "$tag" ] && continue
        if echo "$protected" | grep -qx "$tag"; then
            continue
        fi
        kept=$((kept + 1))
        if [ "$kept" -le "$KEEP" ]; then
            continue
        fi
        log "Removing old image: ${repo}:${tag}"
        docker rmi "${repo}:${tag}" >/dev/null 2>&1 || log "WARNING: could not remove ${repo}:${tag} (still in use?)"
    done <<< "$tags"
}

prune_image_tags "${BACKEND_IMAGE:-samslab-backend}"
prune_image_tags "${FRONTEND_IMAGE:-samslab-frontend}"

log "Pruning dangling images and stopped containers..."
docker image prune -f >/dev/null
docker container prune -f >/dev/null

log "Cleanup complete."
