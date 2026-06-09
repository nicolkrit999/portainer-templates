---
description: YAML formatting, compose best practices, timezone, and default user conventions.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Compose conventions

## YAML formatting
- **2-space indentation** throughout.
- Top-level `services:` key — **do not include a `version:` field** (Compose V2).
- No trailing whitespace; separate logical sections (volumes, networks) with a
  blank line.
- **Quote every value in `environment:` blocks** — booleans, numbers, and
  `${VAR}` references included. Portainer's stack deployer rejects YAML
  bool/number env values with an opaque `[object Object]` UI error. Write
  `FOO: "true"` not `FOO: true`; `PORT: "8080"` not `PORT: 8080`;
  `KEY: "${MY_SECRET}"` not `KEY: ${MY_SECRET}`.
  **Exception:** `PUID`/`PGID` may stay unquoted (numeric user IDs Portainer accepts).

## Compose best practices
- **`container_name`** on every service (descriptive, matches purpose).
- **`restart`** policy on every service — default `unless-stopped`; use `always`
  only when it must survive Docker daemon restarts unconditionally.
- **Healthchecks** where the image supports them (research the correct
  endpoint/command).
- **`depends_on`** with `condition: service_healthy` when depending on a service
  that defines a healthcheck.
- **Image pinning**: pin specific tags/digests for stability-critical services;
  `:latest` only when the user prefers it or the service is low-risk.
- **Logging limits** for long-running services to prevent disk exhaustion:
  ```yaml
  logging:
    options:
      max-size: "10m"
      max-file: "3"
  ```

## Timezone
**Always use `TZ: "${TZ}"` — never hardcode the timezone value in a compose
file.** The `TZ` variable is provided via the `.env` / Portainer stack env and
defaults to `Europe/Zurich`. Every service that accepts a `TZ` env var must
reference it as `"${TZ}"`.

## Default username & UID/GID
- Default admin/user account name is **`krit`** unless specified — apply to
  `DEFAULT_USERNAME`, `ADMIN_USER`, `INITIAL_USER`, etc., replacing upstream
  sample values (`admin`, `marius`, …). Passwords still go through `${...}`.
- NAS user `krit` IDs, for images supporting `PUID`/`PGID` (LinuxServer.io,
  *arr stack) or a `user:` directive: `PUID=1000`, `PGID=10`. Set as literal
  values (not secrets):
  ```yaml
  environment:
    PUID: 1000
    PGID: 10
    TZ: "${TZ}"
  ```
