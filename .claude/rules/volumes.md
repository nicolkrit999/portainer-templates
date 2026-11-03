---
description: Volume path conventions and storage-pool placement for compose files.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Volume path conventions

Two storage pools with distinct purposes, referenced **only** via variables:

- **`${VOLUME_CONFIG}/<service>/`** - NVMe/SSD-class storage. Use for
  **configuration, small fast-access data, small composes**: app config,
  SQLite DBs, application state.
- **`${VOLUME_DATA}/<service>/`** - HDD-class bulk storage. Use for **user
  data, media libraries, large databases, heavy files**.

## Rules
- **Committed compose files must never contain literal host paths.** The real
  storage roots are set in the Portainer stack env (this NAS: config pool
  `/volume2/docker`, data pool `/volume1/Default-volume-1/0001_Docker`);
  `.env.example` defaults are placeholders and vary between stacks. Reference
  paths only as `${VOLUME_CONFIG}/<service>/...` or `${VOLUME_DATA}/<service>/...`.
- **Two spellings coexist** (checked 2026-11-04): older stacks use
  `${DOCKER_CONFIG_DIR}` / `${DOCKER_DATA_DIR}` (about 44 and 23 compose files),
  newer ones `${VOLUME_CONFIG}` / `${VOLUME_DATA}` (15 and 6). Same meaning, same
  pools. New stacks use `VOLUME_*`; when editing an existing stack keep the
  spelling it already has (renaming means touching its Portainer env) and never
  mix both in one stack. (`gotchas/portainer-relative-bind-mounts.md` needs the
  root that contains Portainer's own data dir; both spellings are `/volume2/docker` here.)
- **Avoid unnamed (anonymous) and named-only Docker volumes whenever possible.**
  Every persistent volume should bind-mount to an explicit host path under
  `${VOLUME_CONFIG}/...` or `${VOLUME_DATA}/...`.
- Do **not** let data land in the NAS `@docker` directory (the default Docker
  root) - it is hard to back up and audit. If an image insists on a named volume
  for a subpath, bind-mount the parent or use a host-path override.

## Workflow
When creating or changing volume paths, **suggest specific paths from these
conventions, then ask the user to confirm** before finalizing. Example:

> "I've suggested `${VOLUME_CONFIG}/gitea/config` for Gitea's configuration and
> `${VOLUME_DATA}/gitea/data` for repository data. Does this match your setup,
> or would you like different paths?"
