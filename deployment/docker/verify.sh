#!/usr/bin/env bash
# Verify a running deployment end to end. Exits 0 only if every check below
# passes; deploy.sh/rollback.sh both treat any non-zero exit as "roll back".
#
# Checks: backend healthy, frontend reachable, native PostgreSQL reachable,
# native MediaMTX reachable, native VictoriaMetrics reachable.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"

require_cmd curl
require_cmd docker
load_env

failures=0

check() {
    local description="$1"
    shift
    if "$@"; then
        log "OK: $description"
    else
        log "FAILED: $description"
        failures=$((failures + 1))
    fi
}

check_backend_health() {
    curl -fsS --max-time 5 "http://127.0.0.1:${BACKEND_HOST_PORT:-8000}/health" >/dev/null
}

check_frontend_reachable() {
    curl -fsS --max-time 5 "http://127.0.0.1:${FRONTEND_HOST_PORT:-8080}/healthz" >/dev/null
}

check_database_reachable() {
    compose exec -T backend python3 -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine

async def main() -> None:
    engine = create_async_engine(os.environ['DATABASE_URL'])
    async with engine.connect():
        pass
    await engine.dispose()

asyncio.run(main())
" >/dev/null 2>&1
}

check_mediamtx_reachable() {
    local host="${MEDIAMTX_HOST:?MEDIAMTX_HOST not set}" port="${MEDIAMTX_PLAYBACK_PORT:-8889}"
    timeout 5 bash -c "echo >/dev/tcp/${host}/${port}" >/dev/null 2>&1
}

check_victoriametrics_reachable() {
    local url="${VICTORIA_METRICS_URL:?VICTORIA_METRICS_URL not set}"
    curl -fsS --max-time 5 "${url%/}/health" >/dev/null
}

check "backend healthy (GET /health)" check_backend_health
check "frontend reachable" check_frontend_reachable
check "PostgreSQL reachable (native)" check_database_reachable
check "MediaMTX reachable (native)" check_mediamtx_reachable
check "VictoriaMetrics reachable (native)" check_victoriametrics_reachable

if [ "$failures" -eq 0 ]; then
    log "All verification checks passed."
    exit 0
fi

log "$failures verification check(s) failed."
exit 1
