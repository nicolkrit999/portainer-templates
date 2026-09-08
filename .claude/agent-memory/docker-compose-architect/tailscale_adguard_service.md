---
name: tailscale-adguard-service
description: tailscale-adguard stack - 3rd Tailscale identity giving AdGuard a tailnet IP for exit-node DNS-bypass fix; same-project network_mode:service: DNS relay sidecar pattern
metadata:
  type: project
---

Created 2026-09-07: `tailscale-adguard/docker-compose.yml` + `.env.example`.

**Purpose**: give AdGuard Home (`adguard/`, container `adguard`, on `traefik-proxy` network, DNS port 53) its own Tailscale IP so it can be registered in the Tailscale admin console as the tailnet's DNS server. Fixes confirmed bug: a device with an active Tailscale exit node bypasses AdGuard filtering because nothing is currently registered as the tailnet nameserver, so DNS falls through to the exit node's own resolver. Admin-console registration of the resulting 100.x.x.x IP is out of scope for this repo (peer session's job on the Tailscale side).

**Structure - 2 services in ONE compose file** (deliberately different from `tailscale-admin`'s cross-stack pattern):
- `tailscale-adguard` - 3rd independent Tailscale identity (after `tailscale/` host-mode primary and `tailscale-admin/`'s sidecar-hosting node). Ordinary (non-host) networking on `traefik_proxy_network`, static IP `172.27.255.248` (confirmed free by grepping all compose files for `ipv4_address` - only `172.27.255.250` Traefik and `172.27.255.249` tailscale-admin existed before this). `TS_AUTHKEY_ADGUARD`/`TS_HOSTNAME_ADGUARD` (default `adguard-dns`) env vars, state at `${VOLUME_CONFIG}/tailscale-adguard/state`, `net.ipv4.ip_unprivileged_port_start: "0"` sysctl (lets the relay bind port 53 without NET_BIND_SERVICE/root), `restart: always`, `tailscale status --json` healthcheck. Deliberately advertises NO subnet routes - it's a DNS endpoint, not a LAN gateway.
- `dns-relay` - alpine+socat, joins via `network_mode: service:tailscale-adguard` (same-project form, valid because both services are in this one file - contrast with `tailscale-admin`/`traefik-tailnet-forwarder`'s cross-stack `network_mode: container:tailscale-admin` form). Relays UDP+TCP:53 to `adguard:53` (reachable because it inherits `tailscale-adguard`'s `traefik_proxy_network` attachment). No NET_ADMIN needed (pure relay, no interface/route creation - contrast with `macvlan-host-shim` which DOES need NET_ADMIN). Command styled like `macvlan-host-shim`: single-line idempotent `apk add` + backgrounded socat UDP/TCP listeners + `wait`.

**No Traefik/Cloudflare/SAN group** - same precedent as `iperf3`, pure Tailscale-reachable infra with no HTTP surface.

**Portainer setup needed**: only `TS_AUTHKEY_ADGUARD` is a real secret to fill in (generate reusable pre-auth key via Tailscale admin console). `TS_HOSTNAME_ADGUARD`, `TAILSCALE_ADGUARD_INTERNAL_IP` have safe working defaults. `VOLUME_CONFIG` is the existing repo-wide var, already set at stack level typically.

See also [[tailscale_admin_traefik_tailnet_forwarder_service]] for the sibling pattern this was modeled on (merged into one file 2026-09-08, was two separate memories/stacks when this note was originally written).
