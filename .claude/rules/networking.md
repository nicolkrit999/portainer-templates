---
description: Networking, hostnames, Traefik routers and access-path conventions for compose files.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Networking

Current model (2026-11-03): no Cloudflare Tunnel, no `cloudflare-web` network, no
family/guest/friends tiers, no SAN-bundle certificate groups. Three access paths
exist (LAN, tailnet, public); the mechanism is in `.claude/rules/core-infra-topology.md`.
A service compose only deals with the first two, via two Traefik routers.

## Hostname convention
Unless the user specifies otherwise, a service's hostname is
`<service-name>.${DOMAIN}`, using dashes for multi-word names
(`n8n.${DOMAIN}`, `uptime-kuma.${DOMAIN}`, `actual-budget.${DOMAIN}`).
Use this default for `N8N_HOST`, `WEBHOOK_URL`, and any hostname/URL env vars -
never hardcode a real domain in a committed compose file. The actual domain
lives in `.env` / Portainer stack env (this instance: `DOMAIN=nicolkrit.ch` in
`.env.example`). Every hostname resolves through the wildcard in `dnsmasq` (LAN)
and `dnsmasq-tailnet` (tailnet), so there is **no DNS step per service**.

## Traefik reverse-proxy network
**Every user-facing application service joins the shared `traefik-proxy`
network and gets exactly two routers, no confirmation needed.** Backing
dependencies (databases, caches, brokers, migration jobs) do not join it.

Top-level networks block (`external: true` in every service's own compose -
only `traefik/docker-compose.yml` itself creates the network):
```yaml
networks:
  traefik_proxy_network:
    name: traefik-proxy
    external: true
```

Per-service reference:
```yaml
networks:
  - traefik_proxy_network
```

A stack with databases or helpers also gets ONE per-stack backend network
(`<stack>-backend`): `internal: true` unless a member needs egress or published
ports (Docker skips port publishing for internal-only containers), an explicit
/28 `subnet` with `gateway` `.1` and `ip_range` `.8/29`, all three as
env-overridable defaults (`${<STACK>_BACKEND_SUBNET:-172.16.x.0/28}`). Docker's
default address pools on this NAS are nearly exhausted, so the /28 is allocated
from the registry at `/home/krit/momentary/proxy-research/findings/subnets.md`
(outside the repo; add the new row there before editing the compose). Never
define an `ipam:` block on `traefik-proxy` itself (see `traefik/README.md`).

Label set (`<service>` is the compose service name, `<port>` its internal
listening port):
```yaml
labels:
  traefik.enable: "true"
  traefik.http.routers.<service>-private.rule: "Host(`${<SERVICE>_SUBDOMAIN}.${DOMAIN}`)"
  traefik.http.routers.<service>-private.entrypoints: "${TRAEFIK_ENTRYPOINT_3}"
  traefik.http.routers.<service>-private.tls: "true"
  traefik.http.routers.<service>-private.service: "<service>"
  traefik.http.routers.<service>-private.middlewares: "hsts-headers@docker"
  traefik.http.routers.<service>-tailnet.rule: "Host(`${<SERVICE>_SUBDOMAIN}.${DOMAIN}`)"
  traefik.http.routers.<service>-tailnet.entrypoints: "${TRAEFIK_ENTRYPOINT_7}"
  traefik.http.routers.<service>-tailnet.tls: "true"
  traefik.http.routers.<service>-tailnet.service: "<service>"
  traefik.http.routers.<service>-tailnet.middlewares: "hsts-headers@docker,tailnet-admin-only@docker"
  traefik.http.services.<service>.loadbalancer.server.port: "<port>"
  traefik.docker.network: "traefik-proxy"
```

- **Bare `tls: "true"` on both routers - no `tls.certresolver`, no `tls.domains`.**
  One wildcard certificate (`${DOMAIN}` + `*.${DOMAIN}`) is requested by the single
  router `traefik-dashboard` in `traefik/docker-compose.yml`, the only router
  allowed to carry those labels; every other router is served that certificate by
  SNI. A router with its own `certresolver` would request its own certificate and
  race the wildcard. Verify a new hostname by checking the served certificate's
  issuer/SAN, not by absence of log errors (a missing certificate silently falls
  back to Traefik's self-signed default).
- **`hsts-headers@docker` on every router, listed first** in `middlewares`
  (chains short-circuit, so a rejecting middleware listed before it would drop the
  HSTS header on 401/403). `tailnet-admin-only@docker` is the shared ipallowlist
  middleware defined on the `traefik` service (owner device IPs only); it goes
  after HSTS.
- **Never two entrypoints on one router** (comma-separated `entrypoints`; Traefik
  GitHub issue #11889) - hence the separate `-tailnet` router.
- **Both routers are required.** The LAN wildcard sends every hostname to the
  private tier and the tailnet wildcard sends every hostname to the tailnet-admin
  gateway, so a hostname missing either router answers Traefik's own 404 on that path.
- **`${<SERVICE>_SUBDOMAIN}`**: always a dedicated `${VAR}` (e.g.
  `ACTUAL_BUDGET_SUBDOMAIN`), never a hardcoded literal in the router rule - this
  repo is public and even the hostname segment counts as an opinionated value.
  Default its *value* to the service's directory name, **except** when an
  established hostname already differs from it (ask the user to confirm before
  assuming). Known overrides: `actual-budget`→`budget`, `immich`→`foto`,
  `homehub`→`casa`, `mealie`→`ricette`, `surmai`→`viaggi`, `mini-qr`→`miniqr`,
  `omni-tools`→`omnitools`, `easy-appointments`→`appuntamenti`, `ghost`→`blog`,
  `vikunja`→`promemoria`.
- **`.env.example` and the Portainer env contain only variables the compose
  actually references** - drop a variable when the label or setting that used it goes.

**Entrypoint variables - generically numbered on purpose, never named after
their tier** (this repo is public; even a var *name* like
`TRAEFIK_ENTRYPOINT_FAMILY` would leak this household's trust-tier vocabulary -
only the *value* should describe the tier):

| Variable | Meaning this instance | Port var | Port |
|---|---|---|---|
| `TRAEFIK_ENTRYPOINT_3` | private (`asDefault`), LAN via `traefik-private-forwarder` | `TRAEFIK_PORT_3` | 8444 |
| `TRAEFIK_ENTRYPOINT_6` | internal, ping/dashboard-API only, no host port | `TRAEFIK_PORT_6` | 8080 |
| `TRAEFIK_ENTRYPOINT_7` | tailnet-admin - owner devices only, no host port | `TRAEFIK_PORT_7` | 8446 |

Numbers 1, 2, 4 and 5 are retired (family, guest, friends and `cloudflared` were
removed 2026-11-03); the other numbers were kept so no stack's variables had to
change. Do not reintroduce them.

## Making a service public
Public access never goes through the core Traefik. It is a router, a service and
a per-app `public-<app>` network added to `traefik-public/docker-compose.yml`,
plus a DNS-only CNAME for the hostname in Cloudflare (Cloudflare is DNS hosting
only; it is not proxying or tunnelling anything), following
`traefik-public/README.md` step by step. The app's own compose then also joins
its external `public-<app>` network (created by the `traefik-public` stack, which
must be deployed first) and keeps its two ordinary routers above, so the same
hostname still works on the LAN and the tailnet. Only do this when the user asks.

## Host references (NAS)
Never hardcode host IPs in a committed compose file - reference them as
variables, with the real values in `.env` / Portainer stack env:
- `${NAS_IP}` - local network IP of the host (this instance's `.env.example`:
  `192.168.1.98`)
- `${DOCKER_GATEWAY_IP}` - Docker bridge gateway IP (this instance:
  `192.168.48.1`)

## Giving a new service its own static LAN IP (macvlan)

A service that needs to be reachable directly on the LAN at its own IP
(not through Traefik) - e.g. a DNS resolver needing port 53, or any
service that can't share a container's usual bridge networking - needs a
macvlan network. **Docker only allows ONE macvlan network per parent
interface per subnet** - attempting to define a second macvlan network on
the same `parent`/`subnet`/`gateway` (even in a different service's own
compose file) fails at deploy time with `failed to allocate gateway
(<gateway-ip>): Address already in use`. Confirmed real deploy failure,
2026-09-06, when `adguard/docker-compose.yml` first tried to define its
own `adguard_net` macvlan network on the same `${LAN_SUBNET}`/`${LAN_GATEWAY}`
already claimed by `traefik-private-forwarder`'s macvlan network.

**The fix - join the existing macvlan network, don't define a new one.**
This repo's one live macvlan network (created by `traefik-private-forwarder`,
see `.claude/rules/core-infra-topology.md`) is named
`traefik-private-forwarder_traefik_forwarder_net` (Compose's default
`<project>_<network-key>` naming - it was never given an explicit `name:`
override). Any new service needing its own static LAN IP should reference
it as `external: true` and give the service its own `ipv4_address`,
exactly like this repo already does for `traefik_proxy_network`:

```yaml
services:
  <service>:
    networks:
      <service>_net:
        ipv4_address: "${<SERVICE>_STATIC_IP}"

networks:
  <service>_net:
    external: true
    name: traefik-private-forwarder_traefik_forwarder_net
```

Do **not** copy the `driver: macvlan` / `driver_opts` / `ipam` block from
`adguard`'s original stale draft or any other pre-2026-09-06 example - that
pattern only works for the very first macvlan service on a given subnet;
every one after that must attach to the already-existing network instead.
This does not require touching `traefik-private-forwarder`'s own compose
file at all - referencing an already-running network by name is a safe,
additive read from a different stack.

## Tailscale access - via the tailnet-admin router, not a direct IP bind

**Superseded 2026-08-22**: the old `tailscale serve` port-forwarding
mechanism (and the guidance below it in earlier versions of this file about
referencing `${TAILSCALE_IP}` directly or binding host ports to `127.0.0.1`
to avoid a `tailscaled`/`docker-proxy` same-port race) has been fully
removed from this repo - all 9 `tailscale serve` mappings were deleted and
replaced by the `dnsmasq-tailnet` + Traefik `tailnet-admin` entrypoint
mechanism described above. **Do not reference `${TAILSCALE_IP}` directly in
a new compose file, and do not bind a host port to `127.0.0.1` on the
assumption of a `tailscale serve` conflict - that conflict class no longer
exists.** The correct, current way for a service to be reachable over
Tailscale is the `-tailnet` router block above; it needs no `ports:` entry
of its own at all, since Traefik reaches every service over the internal
Docker network, not a published host port.

## Direct LAN/Tailscale port (bypassing Traefik entirely) - opt-in only

A small, explicit set of bandwidth-heavy or large-upload services
(`jellyfin`, `navidrome`, `gitea`, `duplicati`, `convertx`, `filebrowser`,
`stirling-pdf` as of 2026-08-23; UNVERIFIED which of these still publish one,
check the compose or `.claude/rules/service-directory.md`) also publish a
plain HTTP host port so they can be reached directly over LAN or Tailscale
without going through Traefik's TLS termination at all - useful when
Traefik's overhead is a real problem for that specific service, and only
for services that already have their own login (this bypasses HSTS/TLS and,
for tailnet-admin services, the ipallowlist middleware too). Non-HTTP
services follow the same logic: Git over SSH is published on the NAS as
host port 2222 (private only; `gitea-ssh.${DOMAIN}` is the one hostname the
DNS wildcards answer with the NAS's own address, and the gateway never
forwards it). Any published host port is reachable by every device that can
reach the NAS and bypasses Traefik entirely, so add one only deliberately.
**This is not a default** - only
add a host-port publish when the user explicitly asks for LAN-speed direct
access for a specific service, bind to `0.0.0.0` (not `127.0.0.1` - see
above, the old race this used to guard against no longer applies), and
record the chosen port in `.claude/rules/service-directory.md`'s port table
first to avoid colliding with another service's already-published port -
duplicate host-port bindings fail silently late (the losing container just
won't start) rather than at compose lint time.
