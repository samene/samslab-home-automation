# Operations

Day-to-day operator reference for the hybrid deployment: native systemd
infrastructure plus two Dockerized application services (backend, frontend).
See [docs/architecture/DEPLOYMENT.md](docs/architecture/DEPLOYMENT.md) for the
architecture and design rationale — this document is the runbook.

## Prerequisites (the Ubuntu VM)

- Docker Engine + the `docker compose` plugin (Compose V2 — `docker compose version` should print `v2.x`)
- `git`, `curl`, `bash` (all standard on Ubuntu)
- Already-running native services: PostgreSQL, VictoriaMetrics, vmagent, vmauth, MediaMTX, Caddy — this deployment never installs or configures them, only connects to them
- `deployment/docker/.env` populated from `.env.example` (never committed)

## First-time setup

```bash
git clone <repo> && cd samslab-home-automation
cp deployment/docker/.env.example deployment/docker/.env
vim deployment/docker/.env   # fill in DATABASE_URL, JWT_SECRET, MEDIAMTX_*, VICTORIA_METRICS_URL, ALLOW_ORIGINS, VITE_API_BASE_URL
./deployment/docker/deploy.sh
```

## Deployment

Ongoing deployments need only:

```bash
git pull
./deployment/docker/deploy.sh
```

`deploy.sh` does everything else automatically: records the currently-live
version, backs up config + database, pulls source (skipped if the working
tree has uncommitted changes — it warns rather than clobbering them), builds
both images, runs Alembic migrations against native PostgreSQL, starts
containers, waits for both to report Docker-healthy, then runs `verify.sh`.
**If verification fails, it rolls back automatically** and exits non-zero —
a failed deploy never leaves the VM on broken code.

Pass an explicit version (default: current git short SHA) to pin an image
tag: `./deployment/docker/deploy.sh v1.4.0`.

## Upgrade

`upgrade.sh` is `deploy.sh` under a second name — an upgrade *is* a deploy of
newer code, with the same backup/migrate/verify/rollback safety:

```bash
./deployment/docker/upgrade.sh
```

## Rollback

Automatic on a failed deploy. To roll back manually (e.g. a regression found
after the fact, not caught by `verify.sh`):

```bash
./deployment/docker/rollback.sh            # rolls back to the last recorded previous version
./deployment/docker/rollback.sh v1.3.2      # rolls back to a specific tag (must still exist locally)
```

Rollback restarts containers on the older image tags and re-runs `verify.sh`;
it does **not** restore the database — restore that separately with
`restore.sh` if the rollback is also undoing a migration (see Backup/Restore
below).

## Health and status

```bash
make health     # ./deployment/docker/verify.sh — backend, frontend, PostgreSQL, MediaMTX, VictoriaMetrics
make status     # docker compose ps
make logs       # follow both containers' stdout (Docker logging only — no log files)
```

Or directly:

```bash
curl http://127.0.0.1:8000/health     # backend
curl http://127.0.0.1:8080/healthz    # frontend
docker inspect --format '{{.State.Health.Status}}' samslab-backend
docker inspect --format '{{.State.Health.Status}}' samslab-frontend
```

## Restart

```bash
docker compose --project-directory deployment/docker \
  -f deployment/docker/docker-compose.yml --env-file deployment/docker/.env restart
```

Both containers already run `restart: unless-stopped`, so they also restart
automatically after a Docker daemon or VM restart.

## Logs

Container logs go to stdout/stderr only (structured JSON from the backend,
nginx's combined-style access/error log from the frontend) and are captured
by Docker's own `json-file` driver (rotated at 10 MB × 5 files per
service — see `docker-compose.yml`). There is no application-level log file
to manage.

```bash
make logs                                   # both services, follow
docker logs -f samslab-backend              # backend only
docker logs -f samslab-frontend             # frontend only
docker logs --since 1h samslab-backend      # recent history only
```

## Backup and restore

```bash
./deployment/docker/backup.sh [label]         # config + docker-compose.yml + pg_dump, to /var/backups/samslab/<timestamp>-<label>/
./deployment/docker/restore.sh <backup-dir>   # restores config + database — prompts for confirmation
```

`deploy.sh` calls `backup.sh` automatically before every deployment. MediaMTX
recordings are never included — this backs up application state only.

## Cleanup

```bash
./deployment/docker/cleanup.sh              # keeps the 5 most recent image tags per service
./deployment/docker/cleanup.sh --keep 10    # keep more
```

Never removes the currently deployed version, `:latest`, or the recorded
previous version (so rollback keeps working).

## Docker commands (`Makefile` targets)

| Command | Does |
| --- | --- |
| `make build` | Build both images (`deployment/docker/build.sh`) |
| `make deploy` | Full deploy (`deployment/docker/deploy.sh`) |
| `make upgrade` | Same as deploy, named for the upgrade workflow |
| `make rollback` | Roll back to the previous version |
| `make health` | Run `verify.sh` |
| `make status` | `docker compose ps` |
| `make logs` | Follow both containers' logs |
| `make shell-backend` | Open a shell in the running backend container |
| `make shell-frontend` | Open a shell in the running frontend container |
| `make clean` | Dev cache cleanup, plus `cleanup.sh` for old Docker images |

## Troubleshooting

**`verify.sh` fails on PostgreSQL/MediaMTX/VictoriaMetrics reachability** —
these are native services outside this deployment's control. Check they're
running (`systemctl status postgresql`, etc.) and that `DATABASE_URL`/
`MEDIAMTX_HOST`/`VICTORIA_METRICS_URL` in `.env` use an address the Docker
containers can actually reach — never `localhost` (that resolves *inside*
the container, not to the host). The Docker bridge gateway address (commonly
`172.17.0.1`) or the VM's real LAN/hostname both work; `localhost` does not.

**A container is `unhealthy`** — `docker logs <container>` first. For the
backend, an unhealthy status after startup almost always means it can't
reach PostgreSQL (check `DATABASE_URL`) or a bad `JWT_SECRET`/setting caused
`Settings()` validation to fail at import time.

**Migrations fail during deploy** — `deploy.sh` runs
`docker run --rm --env-file .env <backend-image> alembic upgrade head`
directly (a throwaway container, not a running service) so you can reproduce
and debug it identically by hand. A failed migration stops the deploy before
containers are started — the old version keeps running untouched.

**Deploy succeeded but `git pull` was skipped** — `deploy.sh` warns and skips
the pull (rather than discarding work) if the working tree has uncommitted
changes. Commit or stash them, then re-run.

**Need to inspect a container** — `make shell-backend` / `make shell-frontend`,
or `docker exec -it <container> sh`. Both images are minimal (no dev tools,
no editors); the backend (Debian slim) has `bash`, the frontend (Alpine) only
has the busybox `sh` `make shell-frontend` opens.
