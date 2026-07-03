---
description: Volume path conventions and storage-pool placement for compose files.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Volume path conventions

Two storage pools with distinct purposes, referenced **only** via their
canonical variables:

- **`${VOLUME_CONFIG}/<service>/`** - NVMe/SSD-class storage. Use for
  **configuration, small fast-access data, small composes**: app config,
  SQLite DBs, application state.
- **`${VOLUME_DATA}/<service>/`** - HDD-class bulk storage. Use for **user
  data, media libraries, large databases, heavy files**.

## Rules
- **Committed compose files must never contain literal host paths.** The real
  storage roots are set in `.env` / Portainer stack env; `.env.example` ships
  sensible defaults for this instance (`VOLUME_CONFIG=/volume2/docker`,
  `VOLUME_DATA=/volume1/Default-volume-1/0001_Docker`). Reference paths only
  as `${VOLUME_CONFIG}/<service>/...` or `${VOLUME_DATA}/<service>/...`.
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
