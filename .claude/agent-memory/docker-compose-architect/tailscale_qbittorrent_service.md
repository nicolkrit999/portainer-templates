---
name: tailscale-qbittorrent-service
description: tailscale-qbittorrent stack - qBittorrent behind a dedicated Tailscale + Mullvad exit-node sidecar (network_mode:service:), structure, env, gotchas
metadata:
  type: project
---

`tailscale-qbittorrent/docker-compose.yml` (live, 2 services; migrated off `network_mode: host` on 2026-09-24). The plain `qbit-torrent/` stack is kept as a deliberate, not-deployed rollback reference; see [[tailscale_qbittorrent_naming_split]] for how the two coexist.

**`tailscale-qbittorrent`** (sidecar): dedicated Tailscale identity, same shape as [[tailscale_adguard_service]] (`NET_ADMIN`+`SYS_MODULE`, `/dev/net/tun`, `TS_USERSPACE=false`, healthcheck `tailscale status --json`) without any relay. On `traefik-proxy` with a dynamic address (no static IP needed). Always routes through one fixed Mullvad exit node (Barcelona, deliberately not Switzerland, traffic-correlation reasons, no rotation) via `TS_EXTRA_ARGS: "--exit-node=${MULLVAD_EXIT_NODE} --accept-dns=true --exit-node-allow-lan-access=true"`.
- `MULLVAD_EXIT_NODE` must be a **Tailscale IP**, not a `.ts.net` name: on first boot `tailscale up --exit-node=<hostname>` fails because name resolution needs the tailnet connection it is still creating. Look the IP up with `tailscale exit-node list --filter=<region>` on a connected device.
- `--exit-node-allow-lan-access=true` is required: by default the exit-node client firewall drops everything except loopback, which would cut Traefik (another container, on `172.27.0.0/16`) off from the WebUI.
- `--accept-dns=true` is Tailscale's default; kept explicit by the user's request.

**`qbittorrent`** (`container_name: qbit-torrent-tailscale`): `network_mode: service:tailscale-qbittorrent` with `depends_on: ... service_healthy`; `mem_limit: 16g`, `cpus: 4.0`, `cpuset: "0-4"` (core 5 stays free for the rest of the host). Traefik reaches it through the sidecar: `loadbalancer.server.url: http://tailscale-qbittorrent:${WEBUI_PORT}`. Routers: `qbit-torrent-tailscale` (`${TRAEFIK_ENTRYPOINT_3}`) and `qbit-torrent-tailscale-tailnet` (`${TRAEFIK_ENTRYPOINT_7}` + `tailnet-admin-only`), bare `tls`.

**Env:** `TS_AUTHKEY_QBITTORRENT` (secret), `TS_HOSTNAME_QBITTORRENT`, `MULLVAD_EXIT_NODE`, `QBIT_TORRENT_TAILSCALE_SUBDOMAIN`, `WEBUI_PORT`, `VOLUME_CONFIG`, `VOLUME_DATA`, plus the shared `DOMAIN`, `TZ`, `PUID`, `PGID`, `TRAEFIK_ENTRYPOINT_3/7`.
