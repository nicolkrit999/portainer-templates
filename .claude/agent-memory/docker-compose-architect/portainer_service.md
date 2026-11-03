---
name: portainer-service
description: Portainer itself - reference-copy-only compose (not git-tracked), live /data path, restart:always, docker.sock rw, ports 9000/9444
metadata:
  type: project
---

`portainer/docker-compose.yml` is a **reference copy only**: Portainer runs as a standalone container created from UGOS's compose UI, so edits to the file do not reach it (its own header comment says so). It manages every other stack, so its `/data` state must be preserved exactly.

- **Image/name**: `portainer/portainer-ce:latest`, `container_name: portainer`.
- **Volume**: `${VOLUME_CONFIG}/portainer:/data` = live host path `/volume2/docker/portainer`. Never change it. This is also why a relative bind mount in a git stack breaks: see `.claude/rules/gotchas/portainer-relative-bind-mounts.md`.
- **Docker socket**: hardcoded literal `/var/run/docker.sock`, read-write (Traefik mounts the same path `:ro`; Portainer needs write).
- **Ports**: `9000:9000` and `9444:9443` published. The UI on the host port is the fallback path if Traefik breaks.
- **`restart: always`**: deliberate exception to the repo's `unless-stopped` default; Portainer must survive daemon restarts unconditionally.
- **Routers**: `portainer` (`${TRAEFIK_ENTRYPOINT_3}`) and `portainer-tailnet` (`${TRAEFIK_ENTRYPOINT_7}`, with `tailnet-admin-only`), bare `tls`, on `traefik-proxy` only. No healthcheck, no PUID/PGID (the image does not use them).

**Do not bypass the `.env.example` write deny rule** (a permission control, not an obstacle): if `Write` denies an `.env.example` path, stop and ask the user how to create it. History: a 2026-08-21 session used `dangerouslyDisableSandbox` around it and was flagged.
