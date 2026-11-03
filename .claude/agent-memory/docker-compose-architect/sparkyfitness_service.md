---
name: sparkyfitness-service
description: SparkyFitness (fitness/nutrition tracker) - 4-service compose, db-init chown, Postgres 18 mount quirk, volume paths, no server healthcheck
metadata:
  type: project
---

`sparkyfitness/docker-compose.yml`: `sparkyfitness-db-init` (one-shot alpine chown), `sparkyfitness-db` (`postgres:18.3-alpine`), `sparkyfitness-server` and `sparkyfitness-frontend` (`codewithcj/*:latest`).

- **Networks:** only the frontend is on `traefik-proxy` (routers `sparkyfitness` + `sparkyfitness-tailnet`, backend port 80). db and server sit on the stack's own `sparkyfitness-internal` network. It still has the older name, not the `<stack>-backend` /28 convention from `.claude/rules/networking.md`; bring it to that convention only with a subnet from the registry.
- **Volumes:** db at `${VOLUME_CONFIG}/sparkyfitness/db` (mounted at the PARENT `/var/lib/postgresql`, because Postgres 18+ images use a version-specific subdirectory and refuse to start if `.../data` is occupied); backups and uploads at `${VOLUME_DATA}/sparkyfitness/{backups,uploads}`.
- **db-init:** the postgres alpine image runs as uid/gid 70 and does not read PUID/PGID, so a root-owned fresh bind dir blocks it; the init container runs `chown -R 70:70 /data` once.
- **Healthchecks:** db `pg_isready`, frontend `curl -f http://localhost:80/` (tests nginx only). The server has none on purpose: no verified HTTP health endpoint exists (an earlier research pass guessed `/api/health` without confirming it; do not trust that).
- **Version pins:** the compose now uses `latest` for server and frontend. An earlier pass pinned v0.17.3 after a researcher's claimed v0.16.9 proved wrong; if pinning again, verify the tag on Docker Hub directly rather than trusting remembered numbers.
- **Deliberately omitted:** the optional `SPARKY_FITNESS_EMAIL_*` and OIDC variables.

See `.claude/rules/conventions.md` for the repo-wide rules.
