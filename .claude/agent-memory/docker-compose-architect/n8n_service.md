---
name: n8n-service
description: n8n compose - init-container ownership-fix pattern, depends_on conditions, backend network
metadata:
  type: project
---

`n8n/docker-compose.yml` uses disposable `alpine` init services to fix bind-mount ownership before the real service starts, because n8n (node user, 1000:1000) and postgres (999:999) cannot chown their own bind-mounted data.

Pattern (reuse for any `EACCES` / permission crash loop on a bind mount):
```yaml
<service>-init:
  image: alpine
  container_name: <service>-init
  restart: "no"
  user: "0"
  volumes:
    - ${DOCKER_CONFIG_DIR}/<service>/<subpath>:<container-path>
  command: chown -R <uid>:<gid> <container-path>
```
The real service then has `depends_on: <service>-init: condition: service_completed_successfully`.

- `n8n-db-init` chowns `${DOCKER_CONFIG_DIR}/n8n/db` to `999:999` before `n8n-db` (`postgres:18`).
- `n8n-data-init` chowns `${DOCKER_CONFIG_DIR}/n8n/data` to `1000:1000` before `n8n`; added 2026-07-01 for the `EACCES: permission denied, open '/home/node/.n8n/config'` crash loop.
- **depends_on nuance:** `n8n-db`'s healthcheck block is commented out, so `n8n` depends on it with `condition: service_started` (`service_healthy` would never resolve). When converting list-form `depends_on` to map-form, keep the old entry's semantics (`service_started`), and check whether a healthcheck is actually enabled before choosing `service_healthy`.
- **Networks:** `n8n-db` is only on `n8n_backend_network` (`n8n-backend`, `internal: true`, 172.16.104.0/28, env-overridable); `n8n` is on that plus `traefik-proxy`. Standard private + `-tailnet` routers.
- The stack uses `${DOCKER_CONFIG_DIR}` for its paths (not `${VOLUME_CONFIG}`); keep whichever the stack's Portainer env defines.
- Redeploying n8n via `StackGitRedeploy` without the full env blanks `N8N_ENCRYPTION_KEY`/`POSTGRES_PASSWORD` (incident 2026-08-22, rule in `.claude/rules/portainer-instance.md`).

**Why:** n8n always runs as 1000:1000; host-created or tool-created bind mounts have other owners and make it crash-loop on startup.
**How to apply:** use this init-service pattern for any new ownership mismatch.
