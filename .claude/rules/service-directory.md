---
description: Reference directory of every service in this repo - its clean-URL hostname, which Traefik routers it has (private, tailnet, public via traefik-public), whether it is deployed in Portainer, and the host ports published on the NAS (which bypass Traefik). Consult this before adding a service, a public hostname, or a host-port publish.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Service directory

Generated on 2026-11-04 from the actual compose files (routers, `ports:`), each
stack's `.env.example` (hostname defaults) and Portainer's stack list (environment 3).
If it ever looks wrong, re-derive it from those rather than trusting this copy.
Update it when a service is added, removed, made public or private, or when a host
port is published or removed.

Hostnames are the `.env.example` defaults of each `${..._SUBDOMAIN}` variable. The
live Portainer env can differ (a rename once left an `.env.example` default stale), so
check the stack's env or the compose `Host()` rule before relying on one.

## Access model

Every hostname is `<subdomain>.${DOMAIN}`. Every service with a Traefik router has
exactly two routers on the private side (`<svc>-private` on `${TRAEFIK_ENTRYPOINT_3}`,
`<svc>-tailnet` on `${TRAEFIK_ENTRYPOINT_7}`), reaching it from the LAN and the tailnet.
Only the "Public" hostnames below are also served to strangers, by `traefik-public`
(never by the private Traefik). Router conventions: `.claude/rules/networking.md`; how the
three paths work: `.claude/rules/core-infra-topology.md`. No DNS entry per service is
needed (both resolvers are wildcards).

## Service table

"Routers" is what the stack's own compose file declares. "Public" means the hostname is
also routed by `traefik-public`. 95 compose files: 79 declare Traefik routers (85
hostnames), 16 have none. 75 are deployed: 74 Portainer stacks plus `portainer`, which
runs as a standalone container; 20 are in the repo only (not deployed, their routers
still follow the two-router rule).

| Service (directory) | Hostname(s) | Routers | Public | Deployed | Notes |
|---|---|---|---|---|---|
| `actual-budget/actual-ical` | `budget-ical` | private, tailnet | - | yes |  |
| `actual-budget/actual-server_actual-https-api` | `budget`, `budget-api` | private, tailnet | `budget` only | yes | only `budget` is public; `budget-api` is private only |
| `actual-budget/actual-tap` | `budget-tap` | private, tailnet | - | yes |  |
| `adguard` | `adguard` | private, tailnet | - | yes |  |
| `affine` | `affine` | private, tailnet | - | yes |  |
| `apprise-api` | `apprise-api` | private, tailnet | - | yes |  |
| `attic` | - | none | - | yes | no router; LAN-only, host port 8081 |
| `beszel` | `beszel` | private, tailnet | - | yes |  |
| `blender` | `blender` | private, tailnet | - | no |  |
| `bytestash` | `bytestash` | private, tailnet | yes | yes |  |
| `cardyo` | `cardyo` | private, tailnet | - | no |  |
| `central-services` | `mailpit`, `phpldapadmin` | private, tailnet | - | yes | Mailpit and phpLDAPadmin |
| `change-detection` | `change-detection` | private, tailnet | - | yes |  |
| `convertx` | `convertx` | private, tailnet | - | yes |  |
| `coolify` | `coolify`, `soketi-coolify` | private, tailnet | - | yes | app and realtime (Soketi) |
| `datetime` | `datetime` | private, tailnet | - | no |  |
| `dnsmasq-tailnet` | - | none | - | yes | DNS (port 53), host-networked |
| `dnsmasq` | - | none | - | yes | DNS (port 53), host-networked |
| `dockpeek` | `dockpeek` | private, tailnet | - | no |  |
| `draw-io` | `draw-io` | private, tailnet | - | yes |  |
| `duplicati` | `duplicati` | private, tailnet | - | yes |  |
| `easy-appointments` | `appuntamenti`, `appuntamenti-pma`, `appuntamenti-swagger` | private, tailnet | yes | yes | booking site plus phpMyAdmin and Swagger UI (private only) |
| `excalidraw` | `excalidraw` | private, tailnet | - | no |  |
| `filebrowser` | `filebrowser` | private, tailnet | - | no |  |
| `fossflow` | `fossflow` | private, tailnet | - | no |  |
| `ghost` | `blog` | private, tailnet | - | no |  |
| `gitea` | `gitea` | private, tailnet | yes | yes |  |
| `glance` | `glance` | private, tailnet | - | yes |  |
| `glances` | `glances` | private, tailnet | - | yes |  |
| `gocron` | `gocron` | private, tailnet | - | no |  |
| `gokapi` | `gokapi` | private, tailnet | yes | yes |  |
| `gotify` | `gotify` | private, tailnet | - | yes |  |
| `grafana` | `grafana` | private, tailnet | - | yes |  |
| `grocy` | `grocy` | private, tailnet | - | yes |  |
| `harborguard` | `harborguard` | private, tailnet | - | yes |  |
| `hi-events` | `eventi` | private, tailnet | yes | yes |  |
| `holyclaude` | `claude` | private, tailnet | - | yes |  |
| `home-assistant` | `home-assistant` | private, tailnet | - | yes |  |
| `homebox` | `homebox` | private, tailnet | yes | yes |  |
| `homehub` | `casa` | private, tailnet | - | yes |  |
| `icorsi-notes` | - | none | - | yes | no router, no inbound ports |
| `icorsi-sync` | - | none | - | yes | no router, no inbound ports |
| `immich` | `foto` | private, tailnet | yes | yes |  |
| `iperf3` | - | none | - | yes | no router; host-networked, TCP+UDP 5201, reached over Tailscale by IP |
| `it-tools` | `it-tools` | private, tailnet | - | yes |  |
| `jdownloader` | - | none | - | no | no router |
| `jellyfin-radarr` | `radarr` | private, tailnet | - | yes |  |
| `jellyfin-sonarr` | `sonarr` | private, tailnet | - | yes |  |
| `jellyfin` | `jellyfin` | private, tailnet | yes | yes |  |
| `kavita` | `kavita` | private, tailnet | yes | yes |  |
| `lifeglance` | `lifeglance` | private, tailnet | - | yes |  |
| `linkwarden` | `linkwarden` | private, tailnet | yes | yes |  |
| `macvlan-host-shim` | - | none | - | yes | host-networked helper, no router |
| `mealie` | `ricette` | private, tailnet | yes | yes |  |
| `mini-qr` | `miniqr` | private, tailnet | - | yes |  |
| `moocup` | `moocup` | private, tailnet | - | no |  |
| `n8n` | `n8n` | private, tailnet | - | yes |  |
| `navidrome` | `navidrome` | private, tailnet | yes | yes |  |
| `omni-tools` | `omnitools` | private, tailnet | - | yes |  |
| `opencloud` | `opencloud` | private, tailnet | yes | yes |  |
| `opennotebook` | `opennotebook`, `opennotebook-api` | private, tailnet | - | yes | UI and API hostnames |
| `openresume` | `openresume` | private, tailnet | - | no |  |
| `openspeedtest` | `openspeedtest` | private, tailnet | - | yes |  |
| `owncloud` | `owncloud` | private, tailnet | - | no |  |
| `paperlessngx` | `paperlessngx` | private, tailnet | yes | yes |  |
| `plex` | `plex` | private, tailnet | - | no |  |
| `pocket-id` | `pocket-id` | private, tailnet | yes | yes |  |
| `portainer` | `portainer` | private, tailnet | - | yes (standalone container, not a Portainer stack) |  |
| `privatebin` | `privatebin` | private, tailnet | yes | yes |  |
| `prometheus` | - | none | - | yes | no router |
| `qbit-torrent` | `qbit-torrent` | private, tailnet | - | yes |  |
| `snapotter` | `snapotter` | private, tailnet | - | yes |  |
| `snappyemail` | `snappyemail` | private, tailnet | - | no |  |
| `sosse` | `sosse` | private, tailnet | - | no |  |
| `sparkyfitness` | `sparkyfitness` | private, tailnet | - | yes |  |
| `stirling-pdf` | `stirling-pdf` | private, tailnet | - | yes |  |
| `surmai` | `viaggi` | private, tailnet | - | yes |  |
| `tailscale-adguard` | - | none | - | yes | host-networked, no router |
| `tailscale-admin_traefik-tailnet-forwarder` | - | none | - | yes | tailnet-admin gateway, no router |
| `tailscale-qbittorrent` | `qbit-torrent-tailscale` | private, tailnet | - | no | qBittorrent behind its own Tailscale sidecar |
| `tailscale` | - | none | - | yes | host-networked, no router |
| `termix` | `termix` | private, tailnet | - | yes |  |
| `traefik-private-forwarder` | - | none | - | yes | private forwarder (macvlan), no router |
| `traefik-public` | - | none | - | yes | public edge; its routers are generated from the compose file, not Docker labels (see below) |
| `traefik` | `traefik` | private, tailnet | - | yes | dashboard; holds the one wildcard certificate |
| `trek` | `trek` | private, tailnet | yes | yes |  |
| `tugtainer` | `tugtainer` | private, tailnet | - | yes |  |
| `unpoller` | - | none | - | yes | no router |
| `upsnap` | `upsnap` | private, tailnet | - | no |  |
| `uptime-kuma` | `uptime-kuma` | private, tailnet | - | yes |  |
| `vikunja` | `promemoria` | private, tailnet | - | yes |  |
| `watchtower` | - | none | - | no | no router |
| `web-check` | `web-check` | private, tailnet | - | yes |  |
| `withoutbg` | `withoutbg` | private, tailnet | - | no |  |
| `ytptube` | `ytptube` | private, tailnet | - | yes |  |

`gitea`: HTTP goes through Traefik (private, tailnet, public). Git over SSH is private
only: host port 2222 (`GITEA_SSH_HOST_PORT`) at `gitea-ssh.<domain>`, see
`core-infra-topology.md`.

## Public hostnames (traefik-public)

The 18 rows with "yes" in the Public column (`budget` on the Actual server only; its
`budget-api` stays private). The router list, backends, path exclusions, rate limits and
per-app `public-<app>` networks live in `traefik-public/README.md`, the single source for
them. Each public app keeps its two private-side routers and joins an external
`public-<app>` network that `traefik-public` creates. To make another app public follow
`networking.md` ("Making a service public"), then update the table above.

## Published host ports (bypass Traefik entirely)

Only ports a compose file publishes today. A published port skips Traefik's TLS, HSTS and
the tailnet allowlist, so use one only for non-HTTP protocols or for a service with its own
login, and only deliberately. Check this whole table before choosing a new host port: the
Docker daemon rejects a duplicate bind late (the container fails to start) rather than at
compose lint time.

| Service | Host port | Notes |
|---|---|---|
| `gitea` | 2222 -> 22 | Git over SSH, private only (see above) |
| `apprise-api` | 8010 | |
| `attic` | 8081 | no clean URL; LAN-only by design |
| `beszel` | 8096 | |
| `central-services` (mailpit) | 8025 (UI), 1025 (SMTP) | |
| `central-services` (phpldapadmin) | 8201 | |
| `central-services` (openldap) | 389, 636 | LDAP and LDAPS |
| `convertx` | 3010 | default of `CONVERTX_HOST_PORT` |
| `coolify` (realtime) | 6001, 6002 | Soketi; 6002 is metrics |
| `duplicati` | 8200 | default of `DUPLICATI_HOST_PORT`; password-protected |
| `holyclaude` | 3059 | |
| `homehub` | 5000 | |
| `immich` | 2283 | |
| `portainer` | 9000 (http), 9444 (https) | |
| `stirling-pdf` | 8085 | default of `STIRLING_PDF_HOST_PORT`; 8080 is avoided on purpose |
| `vikunja` | 3456 | |
| `traefik` | 80, 8444 | 80 is the HTTPS redirect; 8444 is the `private` entrypoint, reached through `traefik-private-forwarder` |
| `privatebin` | 127.0.0.1:8080 | loopback only (default of `PRIVATEBIN_HOST_PORT`) |
| `sparkyfitness` | 127.0.0.1:8280 | loopback only (default of `SPARKYFITNESS_HOST_PORT`) |
| `filebrowser` | 8082 | not deployed |
| `plex` | 32400 | not deployed |

Host-networked stacks bind their ports directly on the NAS (a `ports:` entry, where one
exists, is ignored in host mode): `home-assistant` 8123, `glances` 61208 (Glances web
default), `iperf3` 5201 (TCP and UDP), `qbit-torrent` `WEBUI_PORT`, `dnsmasq` and
`dnsmasq-tailnet` 53, `upsnap` 8090 (not deployed), plus the `tailscale`,
`macvlan-host-shim` and `tailscale-adguard` helpers.

`pocket-id` deliberately has no direct port: it is an OIDC provider and every app trusts it
at its one fixed clean URL, so a raw port would be a different origin and break OIDC
discovery for every relying app. Never add one.
