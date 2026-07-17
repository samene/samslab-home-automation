#!/usr/bin/env bash
# Restore configuration and the database from a backup produced by backup.sh.
#
# THIS OVERWRITES THE CURRENT DATABASE. It refuses to run without either an
# interactive "yes" confirmation or an explicit --force flag.
#
# Usage: restore.sh <backup-dir> [--force]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

require_cmd docker
load_env

BACKUP_DIR_ARG="${1:-}"
FORCE="${2:-}"
[ -n "$BACKUP_DIR_ARG" ] || die "usage: restore.sh <backup-dir> [--force]"
[ -d "$BACKUP_DIR_ARG" ] || die "backup directory not found: $BACKUP_DIR_ARG"
[ -f "$BACKUP_DIR_ARG/database.dump" ] || die "no database.dump in $BACKUP_DIR_ARG"

if [ "$FORCE" != "--force" ]; then
    if [ ! -t 0 ]; then
        die "refusing to restore non-interactively without --force"
    fi
    read -r -p "This will OVERWRITE the current database from $BACKUP_DIR_ARG. Type 'yes' to continue: " confirmation
    [ "$confirmation" = "yes" ] || die "restore cancelled."
fi

log "Restoring configuration from $BACKUP_DIR_ARG..."
cp "$BACKUP_DIR_ARG/.env" "$ENV_FILE"
cp "$BACKUP_DIR_ARG/docker-compose.yml" "$SCRIPT_DIR/docker-compose.yml"
load_env # reload in case DATABASE_URL changed

PG_URI="${DATABASE_URL/+psycopg/}"
log "Restoring database from $BACKUP_DIR_ARG/database.dump..."
docker run --rm -i "postgres:${POSTGRES_CLIENT_VERSION:-18-alpine}" \
    pg_restore --clean --if-exists --no-owner --no-privileges --dbname "$PG_URI" \
    < "$BACKUP_DIR_ARG/database.dump"

log "Restore complete. Restart containers to pick up the restored configuration:"
log "  docker compose --project-directory $SCRIPT_DIR -f $SCRIPT_DIR/docker-compose.yml --env-file $ENV_FILE up -d"
