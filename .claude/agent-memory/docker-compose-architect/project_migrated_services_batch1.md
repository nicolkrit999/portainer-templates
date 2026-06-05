---
name: project-migrated-services-batch1
description: Services migrated from Portainer to git repo in batch 1 — folder names, image tags, Portainer stack IDs, and key env vars
metadata:
  type: project
---

Batch 1 migration completed 2026-06-05. All services written to `/home/krit/github-repos/personal/portainer-templates/<service>/docker-compose.yml` with generalised env vars. Actual .env files at `/home/krit/momentary/portainer-env/<service>/.env`.

| Service | Stack ID | Folder | Image | Key env vars |
|---|---|---|---|---|
| beszel | 10 | beszel/ | henrygd/beszel:latest + henrygd/beszel-agent | BESZEL_AGENT_TOKEN, BESZEL_AGENT_KEY, BESZEL_HUB_URL, BESZEL_FILESYSTEM, DOCKER_CONFIG_DIR |
| bytestash | 11 | bytestash/ | ghcr.io/jordan-dalby/bytestash:latest | JWT_SECRET, DOCKER_CONFIG_DIR |
| change-detection | 19 | change-detection/ | dgtlmoon/changedetection.io:latest + sockpuppetbrowser | TZ, DOCKER_CONFIG_DIR |
| draw-io | 23 | draw-io/ | jgraph/drawio | none (no env vars needed) |
| glances | 45 | glances/ | nicolargo/glances:latest-full | TZ (network_mode: host — no cloudflare network) |
| grocy | 46 | grocy/ | lscr.io/linuxserver/grocy:latest | PUID, PGID, TZ, DOCKER_CONFIG_DIR |
| mealie | 61 | mealie/ | ghcr.io/mealie-recipes/mealie:latest | PUID, PGID, TZ, DOCKER_DATA_DIR, MEALIE_BASE_URL, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_CONFIGURATION_URL |
| home-assistant | 67 | home-assistant/ | homeassistant/home-assistant | TZ, DOCKER_CONFIG_DIR (network_mode: host) |
| homebox | 68 | homebox/ | ghcr.io/sysadminsmedia/homebox:latest | TZ, DOCKER_CONFIG_DIR |

**Why:** Migrating Portainer stacks to git-based management for version control and reproducibility.
**How to apply:** When working on any of these services, the folder and variable names above are canonical. Mealie uses DOCKER_DATA_DIR (not DOCKER_CONFIG_DIR) because its data lives on /volume1 HDD.
