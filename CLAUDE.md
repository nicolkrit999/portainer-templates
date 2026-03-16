# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repository Is

A collection of Docker Compose files for self-hosted services deployed via **Portainer** with **git-based stack management**. Portainer pulls from this repo and deploys services as stacks. External access is provided through a **Cloudflare Tunnel**.

There are no build steps, tests, or package managers — this is a pure Docker Compose configuration repository.

## Repository Structure

Each service has its own directory at the repo root containing a single `docker-compose.yml`. Some services (e.g. `actual-budget/`) use subdirectories for related companion services.

## Use the `docker-compose-architect` Agent

For any task involving creating or modifying compose files, use the `docker-compose-architect` subagent (`.claude/agents/docker-compose-architect.md`). It encodes all conventions below and will produce correct output. Invoke it via the Agent tool with `subagent_type: "docker-compose-architect"`.

## Compose File Conventions

### Secrets & Environment Variables
- **Never hardcode** passwords, tokens, API keys, or URLs with credentials.
- Use `${VARIABLE_NAME}` syntax. Variables are set inside Portainer, not in `.env` files (`.env` is gitignored anyway).
- After writing a compose file, list all `${VARIABLE_NAME}` references so the user knows what to configure in Portainer.

### Networking (Cloudflare Tunnel)
Services that need external access must include this exact configuration:

```yaml
# per-service:
networks:
  - cloudflare_web_network

# top-level (always at end of file):
networks:
  cloudflare_web_network:
    name: cloudflare-web
    external: true
```

- Key is always `cloudflare_web_network`, Docker network name is always `cloudflare-web`, always `external: true`.
- Internal-only services (databases, caches) do **not** get this network.

### Volume Path Conventions
Two storage pools on the NAS server (these are server-side paths, not developer machine paths):
- **`/volume2/docker/<service>/`** — NVMe SSD. For config files, SQLite databases, small fast-access data.
- **`/volume1/Default-volume-1/0001_Docker/<service>/`** — Bulk storage. For user data, media libraries, large databases.

Always suggest paths and confirm with the user before finalizing.

### YAML Formatting & Best Practices
- **No `version:` field** — use Compose V2 format.
- 2-space indentation throughout.
- `container_name` on every service.
- `restart: unless-stopped` by default (`restart: always` only when unconditional restart is required).
- Include `healthcheck` blocks where the image supports them.
- Use `depends_on` with `condition: service_healthy` when depending on a service with a healthcheck.
- Pin to specific version tags (e.g. `image: nextcloud:28.0.3`). Use `:latest` only when explicitly preferred.
- Add log rotation for long-running services:
  ```yaml
  logging:
    options:
      max-size: "10m"
      max-file: "3"
  ```

### Quality Checklist (before finalizing any compose file)
- [ ] No hardcoded secrets
- [ ] All `${VARIABLE_NAME}` references documented
- [ ] Cloudflare network block present if external access needed
- [ ] `container_name` on every service
- [ ] `restart` policy on every service
- [ ] Healthchecks where applicable
- [ ] `depends_on` with `condition: service_healthy` where appropriate
- [ ] Image versions pinned
- [ ] 2-space indentation, no `version:` field
- [ ] Volume paths confirmed with user

## Personal Configuration

Project conventions belong here. Personal preferences (editor config, personal shortcuts, code style opinions not specific to this project) should go in your **user-level** Claude config, not in this file:

- Linux / macOS: `~/.claude/CLAUDE.md` and `~/.claude/rules/`
- Windows: `%USERPROFILE%\.claude\CLAUDE.md` and `%USERPROFILE%\.claude\rules\`

This keeps the repo clean and avoids one developer's preferences leaking to others.
