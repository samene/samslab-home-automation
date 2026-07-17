#!/usr/bin/env bash
# Back up application configuration and the native PostgreSQL database.
# Never touches MediaMTX's own recordings/storage.
#
# Usage: backup.sh [label]
#   label is an optional suffix (e.g. "pre-deploy-abc123"); defaults to a
#   plain UTC timestamp. Writes to $BACKUP_DIR (default /var/backups/samslab).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

require_cmd docker
load_env

LABEL="${1:-manual}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/samslab}"
DEST="$BACKUP_DIR/${TIMESTAMP}-${LABEL}"

mkdir -p "$DEST"
log "Backing up to $DEST"

# --- Application configuration ------------------------------------------------
cp "$ENV_FILE" "$DEST/.env"
cp "$SCRIPT_DIR/docker-compose.yml" "$DEST/docker-compose.yml"

# --- Database dump, via a throwaway matching-version postgres client
# container rather than requiring postgresql-client on the host ------------
if [ -n "${DATABASE_URL:-}" ]; then
    # pg_dump/libpq don't understand SQLAlchemy's "+psycopg" driver suffix.
    PG_URI="${DATABASE_URL/+psycopg/}"
    log "Dumping database..."
    docker run --rm "postgres:${POSTGRES_CLIENT_VERSION:-18-alpine}" \
        pg_dump --format=custom --no-owner --no-privileges "$PG_URI" \
        > "$DEST/database.dump"
    log "Database dump written to $DEST/database.dump"
else
    log "WARNING: DATABASE_URL not set; skipping database dump."
fi

log "Backup complete: $DEST"
echo "$DEST" > "$STATE_DIR/last_backup_path"
