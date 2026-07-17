#!/usr/bin/env bash
# Shared helpers sourced by every deployment/docker/*.sh script. Never run
# this file directly — it only defines functions and resolves paths.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/.env}"
STATE_DIR="$SCRIPT_DIR/.state"
mkdir -p "$STATE_DIR"

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "required command not found: $1 (see OPERATIONS.md prerequisites)"
}

# Loads .env into the current shell's environment (so docker build --build-arg,
# image tag defaults, and psql/curl helpers below can all read the same
# values docker compose itself uses via --env-file).
load_env() {
    [ -f "$ENV_FILE" ] || die "$ENV_FILE not found — copy .env.example to .env and fill it in"
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
}

# Wraps `docker compose` pinned to this directory's compose file and .env,
# so every script gets the same project regardless of the caller's cwd.
compose() {
    docker compose --project-directory "$SCRIPT_DIR" -f "$SCRIPT_DIR/docker-compose.yml" --env-file "$ENV_FILE" "$@"
}

image_ref() {
    # image_ref backend|frontend [version]
    local kind="$1" version="${2:-${APP_VERSION:-latest}}"
    case "$kind" in
        backend) echo "${BACKEND_IMAGE:-samslab-backend}:${version}" ;;
        frontend) echo "${FRONTEND_IMAGE:-samslab-frontend}:${version}" ;;
        *) die "image_ref: unknown kind '$kind'" ;;
    esac
}

wait_for_container_health() {
    # wait_for_container_health <container-name> <timeout-seconds>
    local name="$1" timeout="${2:-120}" waited=0
    log "Waiting for $name to report healthy (timeout ${timeout}s)..."
    while true; do
        status="$(docker inspect --format '{{.State.Health.Status}}' "$name" 2>/dev/null || echo "unknown")"
        if [ "$status" = "healthy" ]; then
            log "$name is healthy."
            return 0
        fi
        if [ "$status" = "unhealthy" ]; then
            die "$name reported unhealthy"
        fi
        if [ "$waited" -ge "$timeout" ]; then
            die "$name did not become healthy within ${timeout}s (last status: $status)"
        fi
        sleep 3
        waited=$((waited + 3))
    done
}
