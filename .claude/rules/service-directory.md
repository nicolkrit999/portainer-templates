---
description: Reference directory of every service in this repo - which access tier(s) it's reachable on, its clean-URL hostname, and (where one exists) its direct LAN/Tailscale port that bypasses Traefik entirely. Consult this before adding a new service's tier, or before adding/removing a direct-port publish.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Service directory

This file is generated from the actual compose files and live Portainer env
(not hand-maintained from memory) - if it ever looks wrong, re-derive it from
the compose files rather than trusting a stale copy. Update it whenever a
service's tier changes or a direct-port link is added/removed, the same way
`san-cert-groups.md`'s table is kept current.

## What "access tier" means here

Each tier corresponds to a Traefik entrypoint (see `.claude/rules/networking.md`
for the full entrypoint/port table): `family`, `guest`, `private`, `friends`.
`tailnet-admin` is not a tier in that sense - it's the admin-gated clean-URL
path over Tailscale (see `.claude/rules/core-infra-topology.md`), additive on
top of `private` for private-tier-only services. `internal-cloudflared-only`
is Traefik's own internal entrypoint for the Cloudflare Tunnel connector, not
a household-facing tier.

**`private` is always present wherever Traefik is configured at all** - it's
the mandatory baseline (see `.claude/rules/networking.md`). Every other tier
is additive on top of it, per the household's own explicit request for that
specific service.

## Access tier + clean-URL table

| Service (directory) | Hostname(s) | Access tier(s) | Deployed? |
|---|---|---|---|
| `actual-budget` | budget, budget-api | family, private | yes |
| `actual-budget-ical` | budget-ical | family, private | yes |
| `actual-budget-tap` | budget-tap | family, private | yes |
| `adguard` | adguard | private, tailnet-admin | no |
| `affine` | affine | private, tailnet-admin | yes |
| `apprise-api` | apprise-api | private, tailnet-admin | yes |
| `attic` | *(no Traefik router - LAN-only)* | *(none)* | yes |
| `audiobookshelf` | audiobookshelf | private, tailnet-admin | no |
| `beszel` | beszel | private, tailnet-admin | yes |
| `blender` | blender | private, tailnet-admin | no |
| `bytestash` | bytestash | private, tailnet-admin | yes |
| `cardyo` | cardyo | private, tailnet-admin | no |
| `central-services` | mailpit, phpldapadmin | private, tailnet-admin | yes |
| `change-detection` | change-detection | private, tailnet-admin | yes |
| `convertx` | convertx | private, tailnet-admin | yes |
| `coolify` | coolify, soketi-coolify | private, tailnet-admin | yes |
| `datetime` | datetime | private, tailnet-admin | no |
| `dockpeek` | dockpeek | private, tailnet-admin | no |
| `draw-io` | draw-io | private, tailnet-admin | yes |
| `duplicati` | duplicati | private, tailnet-admin | yes |
| `easy-appointments` | appuntamenti | family, guest, private | yes |
| `excalidraw` | excalidraw | private, tailnet-admin | no |
| `filebrowser` | filebrowser | private, tailnet-admin | no |
| `fossflow` | fossflow | private, tailnet-admin | no |
| `ghost` | blog | family, guest, private | no |
| `gitea` | gitea | family, guest, private | yes |
| `glance` | glance | private, tailnet-admin | yes |
| `glances` | glances | private, tailnet-admin | yes |
| `gocron` | gocron | private, tailnet-admin | no |
| `gotify` | gotify | private, tailnet-admin | yes |
| `grocy` | grocy | family, private | yes |
| `harborguard` | harborguard | private, tailnet-admin | yes |
| `holyclaude` | claude | private, tailnet-admin | yes |
| `home-assistant` | home-assistant | private, tailnet-admin | yes |
| `homebox` | homebox | family, private | yes |
| `homehub` | casa | family, private | yes |
| `immich` | foto | family, guest, private, friends | yes |
| `it-tools` | it-tools | private, tailnet-admin | yes |
| `jellyfin` | jellyfin | family, guest, private, friends | yes |
| `jellyfin-radarr` | radarr | private, tailnet-admin | yes |
| `jellyfin-sonarr` | sonarr | private, tailnet-admin | yes |
| `kavita` | kavita | private, tailnet-admin | yes |
| `lifeglance` | lifeglance | private, tailnet-admin | yes |
| `linkwarden` | linkwarden | private, tailnet-admin | yes |
| `mealie` | ricette | family, guest, private | yes |
| `mini-qr` | miniqr | family, private | yes |
| `moocup` | moocup | private, tailnet-admin | no |
| `n8n` | n8n | private, tailnet-admin | yes |
| `navidrome` | navidrome | family, guest, private | yes |
| `omni-tools` | omnitools | family, private | yes |
| `opennotebook` | opennotebook | private, tailnet-admin | yes |
| `openresume` | openresume | private, tailnet-admin | no |
| `owncloud` | owncloud | guest, private | yes |
| `paperlessngx` | paperlessngx | private, tailnet-admin | yes |
| `plex` | plex | family, guest, private, friends | no |
| `pocket-id` | pocket-id | private, tailnet-admin | yes |
| `portainer` | portainer | private, tailnet-admin | yes |
| `privatebin` | privatebin | private, tailnet-admin | yes |
| `qbit-torrent` | qbit-torrent | private, tailnet-admin | yes |
| `snapotter` | snapotter | private, tailnet-admin | yes |
| `snappyemail` | snappyemail | private, tailnet-admin | no |
| `sosse` | sosse | private, tailnet-admin | no |
| `sparkyfitness` | sparkyfitness | private, tailnet-admin | yes |
| `stirling-pdf` | stirling-pdf | private, tailnet-admin | yes |
| `surmai` | viaggi | family, guest, private, friends | yes |
| `termix` | termix | private, tailnet-admin | yes |
| `traefik` | traefik | private, tailnet-admin, internal-cloudflared-only | yes |
| `trek` | trek | family, guest, private, friends | yes |
| `tugtainer` | tugtainer | private, tailnet-admin | yes |
| `upsnap` | upsnap | private, tailnet-admin | no |
| `uptime-kuma` | uptime-kuma | private, tailnet-admin | yes |
| `vikunja` | promemoria | family, private | yes |
| `web-check` | web-check | private, tailnet-admin | yes |
| `withoutbg` | withoutbg | private, tailnet-admin | no |
| `ytptube` | ytptube | private, tailnet-admin | yes |

`gitea` note: family/guest/private HTTP tiers only - `gitea-ssh`/`ssh` (git-over-SSH,
Cloudflare Access) are a completely separate, Cloudflare-Tunnel-only path with
no Traefik router at all, not listed here since they're not HTTP services.

## Direct LAN/Tailscale port table (bypasses Traefik entirely)

Added 2026-08-23 for bandwidth-heavy or large-upload services where the
household wanted a raw fallback that doesn't depend on Tailscale/DNS being
correctly configured on every device (see `san-bundle-stale-cert-cleanup-runbook`
memory's sibling reasoning - same "don't assume the smart path always applies"
principle). These bypass Traefik's TLS, HSTS, and (for `tailnet-admin` services)
the IP-allowlist middleware entirely - only use them for services that already
have their own login, and only for browsing, not for entering fresh passwords
(the connection is plain HTTP, not TLS).

Only services with a real published host port are listed - everything else has
no direct-port path at all (Traefik-internal-Docker-network-only), by design.
Before adding a new one, check this whole table for the chosen host port -
duplicate host-port bindings across compose files were the single biggest risk
identified in this session's work session; the docker daemon rejects the
create silently-late (container just fails to start) rather than at compose
lint time.

| Service | Host port | Notes |
|---|---|---|
| `actual-budget` (budget) | 5006 | |
| `actual-budget` (budget-api) | 5007 | |
| `actual-budget-ical` | 3000 | |
| `actual-budget-tap` | 3001 | host-networked (`network_mode: host`) |
| `apprise-api` | 8010 | |
| `attic` | 8081 | no clean URL at all - LAN/Tailscale-only by design |
| `audiobookshelf` | 13378 | not currently deployed |
| `beszel` | 8096 | |
| `central-services` (mailpit) | 8025 | |
| `central-services` (phpldapadmin) | 8201 | |
| `convertx` | 3010 | |
| `coolify` (soketi-coolify) | 6001 | 6002 also published (metrics, not the main link) |
| `duplicati` | 8200 | password-protected (`DUPLICATI_WEBSERVICE_PASSWORD`) |
| `filebrowser` | 8082 | not currently deployed |
| `gitea` | 3003 | has its own full login/account system |
| `glances` | 61208 | host-networked (`network_mode: host`) |
| `holyclaude` | 3059 | |
| `home-assistant` | 8123 | host-networked (`network_mode: host`) |
| `homehub` | 5000 | |
| `immich` | 2283 | |
| `jellyfin` | 8196 | has its own login |
| `navidrome` | 4533 | |
| `plex` | 32400 | not currently deployed |
| `pocket-id` | 1411 | |
| `portainer` | 9000 (http), 9444 (https) | |
| `qbit-torrent` | 9865 | host-networked (`network_mode: host`) |
| `stirling-pdf` | 8085 | moved from the conventional 8080 - that port is already used live by `easy-appointments`' phpMyAdmin sidecar container |
| `upsnap` | 8090 | not currently deployed |
| `vikunja` | 3456 | |

**Known already-occupied host ports NOT in the table above** (internal-only,
multi-container composes - don't reuse these when picking a new port):
`easy-appointments` also publishes 3306 (mariadb), 8080 (phpMyAdmin), 8000
(swagger-ui), 8100 (baikal) - none of these are meant for direct end-user
access, they're internal tooling for that one stack.
