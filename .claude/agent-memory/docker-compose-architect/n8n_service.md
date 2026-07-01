---
name: n8n-service
description: n8n compose file layout, init-container ownership-fix pattern, and dependency conditions
metadata:
  type: project
---

The n8n stack at `n8n/docker-compose.yml` uses disposable `alpine` "init"
services to fix bind-mount ownership before the real service starts, since
n8n (node user, 1000:1000) and postgres (999:999) images can't chown their
own bind-mounted data directories.

Pattern (repeat for any future ownership-mismatch fix in this repo):
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
Then the real service depends on it via
`depends_on: <service>-init: condition: service_completed_successfully`.

Existing instances in n8n/docker-compose.yml:
- `n8n-db-init` → chowns `${DOCKER_CONFIG_DIR}/n8n/db` to `999:999` (postgres image UID/GID) before `n8n-db` starts.
- `n8n-data-init` → chowns `${DOCKER_CONFIG_DIR}/n8n/data` to `1000:1000` (n8n's `node` user) before `n8n` starts. Added 2026-07-01 to fix `EACCES: permission denied, open '/home/node/.n8n/config'` crash loop.

**Why:** n8nio/n8n image always runs as UID/GID 1000:1000 (`node` user) -
bind mounts created by the host or by other tooling often don't have
matching ownership, causing n8n to crash-loop on startup when it can't
write its config/encryption-key file.

**depends_on nuance:** `n8n`'s `depends_on` is a map with two keys -
`n8n-db: condition: service_started` (n8n-db has no active healthcheck,
its healthcheck block is commented out, so `service_healthy` would never
resolve) and `n8n-data-init: condition: service_completed_successfully`.
When converting a list-form `depends_on` to map-form to add a new
dependency, preserve equivalent semantics for the existing entry
(`service_started` matches list-form's implicit behavior) rather than
defaulting to `service_healthy`.

**How to apply:** Reuse this exact init-service pattern whenever a new
service in this repo hits an `EACCES`/permission crash loop against a
bind-mounted volume. Check whether the target service's healthcheck is
actually enabled before choosing `service_healthy` vs `service_started`
in `depends_on`.
