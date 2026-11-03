---
description: How the core/setup infrastructure stacks (Traefik, traefik-public, both forwarders, both Tailscale nodes, both dnsmasq instances, macvlan-host-shim) fit together. Read this fully before modifying any of these stacks - they are not ordinary application services.
paths:
  - "traefik/**"
  - "traefik-public/**"
  - "traefik-private-forwarder/**"
  - "tailscale/**"
  - "tailscale-admin_traefik-tailnet-forwarder/**"
  - "dnsmasq/**"
  - "dnsmasq-tailnet/**"
  - "macvlan-host-shim/**"
---

# Core infrastructure topology

Exactly three access paths exist. Service compose conventions (the two routers, bare
TLS, hostnames) are in `.claude/rules/networking.md`; this file is the mechanism.
IPs below are this instance's values (the variables hold them; they are not committed).

| Path | Who | Flow |
|---|---|---|
| **LAN** | owner at home | `dnsmasq` (wildcard) answers `${DNS_PRIVATE_IP}` = `traefik-private-forwarder`'s macvlan IP (192.168.1.99) → raw TCP passthrough (socat) → Traefik entrypoint `3` → service |
| **Tailnet** | owner away | `dnsmasq-tailnet` (wildcard) answers `${TAILSCALE_ADMIN_IP}` = the tailnet-admin gateway (100.83.124.109) → `traefik-tailnet-forwarder` (HAProxy inside `tailscale-admin`'s namespace) → PROXY-protocol connection → entrypoint `7` (trusts only the gateway's static IP) → `tailnet-admin-only` ipallowlist (sees the real client IP via the PROXY header) → service |
| **Public** | strangers, a short hostname list | DNS-only CNAME to the DDNS name → UniFi WAN TCP 443 forward (Region Blocking: Incoming, Allow CH+IT) → `traefik-public` (macvlan 192.168.1.94) → per-app `public-<app>` network → service. The core Traefik is not involved |
| **Git over SSH** (private only) | owner | `gitea-ssh.<domain>` is the one specific override in each dnsmasq: it answers the NAS (LAN IP 192.168.1.98 via `dnsmasq`, tailnet IP via `dnsmasq-tailnet`) → published host port 2222 → Gitea. Bypasses Traefik; the gateway never forwards it. Client ssh config needs `Port 2222` |

## Which edits need the caution below

**Routine additions are ordinary maintenance.** A new service needs no DNS step (both
dnsmasq instances are wildcard-only) and no certificate step (one wildcard certificate).
Making a service public is an additive router/service/network in `traefik-public/`
following its own `README.md`.

**These need the caution**: anything touching a core stack's structure (`network_mode`,
image, core `command`/CLI flags, entrypoint definitions, port publishing,
capability/security settings, the DNS wildcard/override lines). Before editing
`traefik/`, `traefik-public/`, `traefik-private-forwarder/`,
`tailscale-admin_traefik-tailnet-forwarder/`, `tailscale/`, `dnsmasq/`,
`dnsmasq-tailnet/` or `macvlan-host-shim/`, read this file completely: these stacks are
shared plumbing with repo-wide blast radius (a config change here has caused a full
outage of every Traefik-routed service at least twice, and a third incident,
2026-09-08, came from the tailnet gateway pair being two stacks) and are tightly
coupled, so a change that looks local often is not.

## What each stack does

**`traefik`** owns HTTP(S) routing, TLS certificates and access rules for the private
and tailnet paths (the `tailnet-admin-only` ipallowlist middleware lives here). Docker
provider only. Entrypoints (numbering kept on purpose after 1, 2, 4 and 5 were retired
2026-11-03, so other stacks' variables did not change; do not reintroduce them):

| Entrypoint | Variables | Port | Notes |
|---|---|---|---|
| `3` private (`asDefault`) | `TRAEFIK_ENTRYPOINT_3`, `TRAEFIK_PORT_3` | 8444 | host-published; the private forwarder reaches it over `traefik-proxy` |
| `6` internal | `TRAEFIK_ENTRYPOINT_6`, `TRAEFIK_PORT_6` | 8080 | ping/dashboard API, no host port |
| `7` tailnet-admin | `TRAEFIK_ENTRYPOINT_7`, `TRAEFIK_PORT_7` | 8446 | no host port, PROXY protocol, trusted only from `TAILSCALE_ADMIN_INTERNAL_IP` |
| `web` | - | 80 | host-published, redirect to https only |

**One wildcard certificate** (`${DOMAIN}` + `*.${DOMAIN}`, DNS-01 via Cloudflare DNS,
token `CF_DNS_API_TOKEN`) is requested by the single router `traefik-dashboard`, the
only router allowed to carry `tls.certresolver`/`tls.domains`. Every other router has
bare `tls: "true"` and is served that certificate by SNI (a second router with its own
certresolver would race and request its own). The same two settings also sit on
entrypoints 3 and 7 as defaults.

**`traefik-public`** is a second, separate Traefik for the few hostnames strangers may
reach: own macvlan IP (same macvlan network as the private forwarder), TCP 443 only, no
host ports, file provider only (no Docker socket, no dashboard). The hostname list, per-app
networks and subnets, egress guard, per-hostname DNS-01 certificates (resolver
`cf_dns_public`, token `CF_DNS_API_TOKEN_PUBLIC`), path rules, rate limits and the
procedure for making an app public all live in `traefik-public/README.md`; never expose
an app publicly through the core Traefik.

**`tailscale`** (the primary node, `network_mode: host`) puts the NAS on the tailnet and
advertises the LAN subnet route. Host mode puts `tailscale0` in the same namespace as
every other host-published port, which is why nothing else can bind a port directly on
this node's tailnet IP (including Traefik's wildcard binds).

**`dnsmasq`** (LAN) and **`dnsmasq-tailnet`** (tailnet) are wildcard-only, no per-service
overrides: every `*.${DNS_WILDCARD_DOMAIN}` name answers the forwarder/gateway IP above,
except `gitea-ssh` (see the table). A hostname without a `-tailnet` router therefore
answers Traefik's own 404 on the tailnet path.

**`traefik-private-forwarder`** is a socat TCP-passthrough sidecar that gives the private
tier a clean `hostname:443` URL on the LAN without giving Traefik's container a second,
conflicting bind. It uses **macvlan** (its own LAN IP, a separate L2 identity from the
NAS) and creates the one live macvlan network,
`traefik-private-forwarder_traefik_forwarder_net`, that `traefik-public`, `adguard` and
anything else needing its own LAN IP join as `external: true` (`networking.md`).

**`macvlan-host-shim`** creates a host-side macvlan interface and `/32` routes so the NAS
can reach the macvlan IPs listed in `MACVLAN_ATTACHED_IPS` (load-bearing for AdGuard's
DNS chain; `dnsmasq` binds its shim IP). `traefik-public`'s IP is deliberately not in
that list.

**`tailscale-admin_traefik-tailnet-forwarder`** is ONE stack with these services:
- `tailscale-admin`: a SECOND, independent Tailscale identity, deliberately not
  `network_mode: host` (ordinary Docker networking with `NET_ADMIN`/`SYS_MODULE` and a
  `/dev/net/tun` device), so it has its own isolated namespace where the forwarder can
  bind 443/80 away from Traefik's wildcard binds. Not a gateway: no subnet route.
- `haproxy-config-init`: one-shot, writes `haproxy.cfg` on every deploy.
- `traefik-tailnet-forwarder`: HAProxy in `network_mode: container:tailscale-admin`
  (macvlan cannot attach to a TUN device). Forwards into Traefik's static IP
  (`TRAEFIK_INTERNAL_IP`) on `TRAEFIK_PORT_7` with `send-proxy-v2`, which is how Traefik
  sees the real client IP.
- `tailscale-admin-watcher`: see the residual-risk section below.

### Residual risk of the gateway pair (read before touching either service)

Docker pins `container:tailscale-admin` to that container's raw ID at creation time, and
Compose never cascades a recreate to a `network_mode: container:X` dependent. If
`tailscale-admin` is recreated alone (rotating `TS_AUTHKEY_ADMIN`, bumping its image tag,
a Portainer-UI env edit to just that service), the forwarder keeps pointing at the dead
namespace: tailnet traffic gets an instant "Connection refused" while everything looks
healthy. Portainer's `AutoUpdate.ForceUpdate` does not help (it redeploys on schedule but
does not recreate a container whose own config is unchanged). History: 2026-09-08, when
the two were still separate stacks with independent 5-minute poll timers; merging them
and adding the watcher closed it.

**The watcher is the structural fix.** `tailscale-admin-watcher` (official
`docker:27-cli` image, read-write `docker.sock`, a read-only mount of this stack's own
compose file from Portainer's checkout) runs `docker events` filtered to
`tailscale-admin` starts, waits `${WATCHER_RESTART_WAIT_TIME}` seconds, then
`docker compose up -d --force-recreate traefik-tailnet-forwarder`. Two third-party
watcher images were evaluated and rejected (one needs Unraid host paths, the other has no
verifiable source and would hold `docker.sock`). Keep the forwarder's literal
`container:tailscale-admin` form (not Compose's `service:` sugar) as long as
`container_name: tailscale-admin` stays fixed.

**Check** (suspect this whenever tailnet access fails but `traefik` and its routers look
fine): `docker_proxy` `GET /containers/tailscale-admin/json` and
`/containers/traefik-tailnet-forwarder/json`, projected to `State.StartedAt`; a NEWER
`tailscale-admin` means a stale forwarder. Confirm by comparing the forwarder's
`HostConfig.NetworkMode` (`container:<id>`) with `tailscale-admin`'s current `Id`.
**Fallback fix** (watcher down): recreate `traefik-tailnet-forwarder`; it re-resolves
against the running `tailscale-admin`.

## Structural constraints (why these stacks look the way they do)

Every extra stack solves one problem: something must bind a port at an address that is
not Traefik's own wildcard bind, without colliding with it. The mechanism differs only by
available interface (a real L2 NIC on the LAN, a TUN device on Tailscale).

- **A wildcard-bound port and a specific-IP bind on the same port cannot coexist in one
  network namespace.** Hence macvlan for the private tier and a second Tailscale identity
  for the tailnet path. Binding the forwarder to `tailscale0` via `network_mode: host`
  was tried and reverted after a real outage (host mode shares the host's namespace; it
  isolates nothing).
- **Docker's userland proxy rewrites the source IP of connections arriving on a published
  port** to a Docker gateway address. Hence the PROXY-protocol forwarder path for the
  ipallowlist. (`traefik-public` avoids it the other way: macvlan IP, no published ports,
  so it sees the real client address.)
- **Macvlan needs a real L2 parent** (the NAS's `bridge0`, see
  `gotchas/macvlan-parent-bridge0.md`); it cannot serve anything Tailscale-facing.
- **The NAS host cannot reach a macvlan IP on its own parent interface** except through
  `macvlan-host-shim` routes (not set up for `traefik-public`). Test the private
  forwarder and `traefik-public` from another LAN device (public: from outside the LAN).

## A 404 does not tell you why

The core Traefik uses only the Docker provider: when a container stops, its router
disappears, so a stopped service, a hostname with no router on the entrypoint hit (e.g. no
`-tailnet` router, reached over the tailnet) and an app that matched but returned its own
`404` at that path all look the same by status code. To tell them apart without Docker
API access, check for the `Strict-Transport-Security` response header: every real router
carries `hsts-headers@docker`, while Traefik's internal "no route matched" fallback runs
no middleware and never has it. With Docker API access, check `/containers/json`
instead. (`traefik-public` uses the file provider, so its routers survive a stopped
backend.)
