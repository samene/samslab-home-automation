#!/usr/bin/env bash
# Full production deployment: backup -> pull -> build -> migrate -> start ->
# verify, automatically rolling back if verification fails. This is the one
# script an operator needs to run — everything else happens automatically.
#
# Usage: deploy.sh [version]
#   version defaults to the current git short SHA.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

require_cmd docker
require_cmd git
load_env

VERSION="${1:-$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "latest")}"
log "Starting deployment of version: $VERSION"

# --- 1. Record what's currently live, so rollback.sh knows what to restore ---
if [ -f "$STATE_DIR/current_version" ]; then
    cp "$STATE_DIR/current_version" "$STATE_DIR/previous_version"
    log "Previous version recorded: $(cat "$STATE_DIR/previous_version")"
else
    log "No previous deployment recorded (this looks like a first deploy)."
fi

# --- 2. Backup current deployment (config + DB) before touching anything ----
log "Backing up current deployment..."
"$SCRIPT_DIR/backup.sh" "pre-deploy-$VERSION"

# --- 3. Pull latest source (best-effort — deploy.sh is also runnable against
# an already-checked-out tree, e.g. from CI) --------------------------------
if [ -d "$REPO_ROOT/.git" ]; then
    if [ -n "$(cd "$REPO_ROOT" && git status --porcelain)" ]; then
        log "WARNING: working tree has uncommitted changes; skipping git pull."
    else
        log "Pulling latest source..."
        (cd "$REPO_ROOT" && git pull --ff-only) || log "WARNING: git pull failed; continuing with the current checkout."
    fi
else
    log "Not a git checkout; skipping source pull."
fi

# --- 4. Build both images -----------------------------------------------------
"$SCRIPT_DIR/build.sh" "$VERSION"

BACKEND_REF="$(image_ref backend "$VERSION")"
FRONTEND_REF="$(image_ref frontend "$VERSION")"

# --- 5. Run Alembic migrations against the native PostgreSQL, using the
# freshly built backend image so migration code always matches app code.
# No --network needed: PostgreSQL is a native service reachable over the
# default bridge (LAN/host address), exactly like the backend container
# itself reaches it — this isn't inter-container traffic. -------------------
log "Running database migrations..."
docker run --rm --env-file "$ENV_FILE" "$BACKEND_REF" alembic upgrade head

# --- 6. Start containers on the new version ----------------------------------
export APP_VERSION="$VERSION"
log "Starting containers on version $VERSION..."
compose up -d

# --- 7. Wait for health, then verify externally ------------------------------
wait_for_container_health samslab-backend 120
wait_for_container_health samslab-frontend 60

log "Running endpoint verification..."
if "$SCRIPT_DIR/verify.sh"; then
    echo "$VERSION" > "$STATE_DIR/current_version"
    log "Deployment of $VERSION succeeded and passed verification."
    exit 0
fi

log "ERROR: verification failed — rolling back automatically."
"$SCRIPT_DIR/rollback.sh"
exit 1
