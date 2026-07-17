#!/bin/sh
# The backend container's own Docker HEALTHCHECK probe.
#
# Uses python3 (already the base image, since this ships inside the backend
# container only) rather than curl/wget, so no extra package is installed
# just to support the healthcheck.
#
# Usage: healthcheck.sh <url> [expected_status]
set -eu

url="${1:?usage: healthcheck.sh <url> [expected_status]}"
expected_status="${2:-200}"

exec python3 - "$url" "$expected_status" <<'PY'
import sys
import urllib.request

url, expected_status = sys.argv[1], int(sys.argv[2])
try:
    with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - fixed, non-user-controlled URL
        status = response.status
except Exception as error:
    print(f"healthcheck failed: {url} ({error})", file=sys.stderr)
    sys.exit(1)

if status != expected_status:
    print(f"healthcheck failed: {url} returned {status} (expected {expected_status})", file=sys.stderr)
    sys.exit(1)

print(f"healthcheck ok: {url} returned {status}")
PY
