#!/usr/bin/env bash
# Upgrade to a new version. An "upgrade" is just a deploy of newer code with
# the same safety guarantees (backup, migrate, verify, auto-rollback) — this
# wrapper exists as its own named entry point (matching the Makefile's
# `upgrade` target and this directory's documented script list) rather than
# duplicating deploy.sh's logic.
#
# Usage: upgrade.sh [version]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/deploy.sh" "$@"
