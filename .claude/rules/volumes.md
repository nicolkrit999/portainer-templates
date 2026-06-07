---
description: Volume path conventions and storage-pool placement for compose files.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Volume path conventions

Two storage pools with distinct purposes:

- **`/volume2/docker/<service>/`** — NVMe SSD. Use for **configuration, small
  fast-access data, small composes**: app config, SQLite DBs, application state.
- **`/volume1/Default-volume-1/0001_Docker/<service>/`** — HDD bulk storage. Use
  for **user data, media libraries, large databases, heavy files**.

## Rules
- **Avoid unnamed (anonymous) and named-only Docker volumes whenever possible.**
  Every persistent volume should bind-mount to an explicit host path under
  `/volume2/docker/...` or `/volume1/Default-volume-1/0001_Docker/...`.
- Do **not** let data land in the NAS `@docker` directory (the default Docker
  root) — it is hard to back up and audit. If an image insists on a named volume
  for a subpath, bind-mount the parent or use a host-path override.

## Workflow
When creating or changing volume paths, **suggest specific paths from these
conventions, then ask the user to confirm** before finalizing. Example:

> "I've suggested `/volume2/docker/gitea/config` for Gitea's configuration and
> `/volume1/Default-volume-1/0001_Docker/gitea/data` for repository data. Does
> this match your setup, or would you like different paths?"
