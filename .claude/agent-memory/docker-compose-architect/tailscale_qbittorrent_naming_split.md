---
name: tailscale-qbittorrent-naming-split
description: qbit-torrent/ (rollback reference) and tailscale-qbittorrent/ (live Mullvad sidecar) have fully distinct identities so both can be deployed side by side
metadata:
  type: project
---

`qbit-torrent/docker-compose.yml` (plain, `network_mode: host`, no Mullvad) is a deliberate permanent rollback reference, not deployed; `tailscale-qbittorrent/` (see [[tailscale_qbittorrent_service]]) is live. Since 2026-09-24 they share no identity, so both can run at once and the user can switch freely. `qbit-torrent/docker-compose.yml` points here by file name, so keep this file's name.

| | `qbit-torrent/` | `tailscale-qbittorrent/` (`qbittorrent` service) |
|---|---|---|
| `container_name` | `qbit-torrent` | `qbit-torrent-tailscale` |
| Hostname variable | `QBIT_TORRENT_SUBDOMAIN` | `QBIT_TORRENT_TAILSCALE_SUBDOMAIN` (default `qbit-torrent-tailscale`) |
| Router/service names | `qbit-torrent`, `qbit-torrent-tailnet` | `qbit-torrent-tailscale`, `qbit-torrent-tailscale-tailnet` |
| Config volume | `${VOLUME_CONFIG}/qbit-torrent/...` | `${VOLUME_CONFIG}/qbit-torrent-tailscale/config` |
| Downloads | `${VOLUME_DATA}/qbit-torrent/...` | `${VOLUME_DATA}/qbit-torrent-tailscale/downloads` |

The rename covers every router/service key, including the `.services.<name>.` key in `loadbalancer.server.url`; the URL value itself (`http://tailscale-qbittorrent:${WEBUI_PORT}`) names the sidecar container and is unrelated to it. Both files use `${VOLUME_CONFIG}`/`${VOLUME_DATA}` (not `DOCKER_CONFIG_DIR`/`DOCKER_DATA_DIR`).

**Why:** two stacks with the same `container_name`, router names and hostname variable collide the moment both are deployed.

**How to apply:** when adding a second variant of an existing service (rollback copy, VPN copy), give it its own container name, router/service names, hostname variable and volume subpaths from the start.
