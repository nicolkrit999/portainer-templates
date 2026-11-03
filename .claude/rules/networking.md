---
description: Networking, hostnames, Traefik routers and access-path conventions for compose files.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Networking

A service compose deals with two of the three access paths (LAN and tailnet) through
two Traefik routers. The public path never touches a service compose's routers (see
"Making a service public"). How the paths work, entrypoint definitions and the core
stacks behind them: `.claude/rules/core-infra-topology.md`.

## Hostname convention
Unless the user specifies otherwise, a service's hostname is
`<service-name>.${DOMAIN}`, using dashes for multi-word names
(`n8n.${DOMAIN}`, `uptime-kuma.${DOMAIN}`). Use it for `N8N_HOST`, `WEBHOOK_URL`
and any hostname/URL env var. Never hardcode a real domain in a committed compose
file: the domain lives in `.env` / Portainer stack env (`DOMAIN=nicolkrit.ch` on
this instance). Both resolvers (`dnsmasq`, `dnsmasq-tailnet`) are wildcards, so there
is **no DNS step and no certificate step per service**.

## Traefik reverse-proxy network
**Every user-facing application service joins the shared `traefik-proxy` network and
gets exactly two routers, no confirmation needed.** Backing dependencies (databases,
caches, brokers, migration jobs) do not join it.

`traefik-proxy` is `external: true` in every service compose (only
`traefik/docker-compose.yml` creates it; never define an `ipam:` block on it, see
`traefik/README.md`):
```yaml
networks:
  traefik_proxy_network:
    name: traefik-proxy
    external: true
```
and per service `networks: [traefik_proxy_network]`.

A stack with databases or helpers also gets ONE per-stack backend network
(`<stack>-backend`): `internal: true` unless a member needs egress or published
ports (Docker skips port publishing for internal-only containers), an explicit /28
`subnet` with `gateway` `.1` and `ip_range` `.8/29`, all three as env-overridable
defaults (`${<STACK>_BACKEND_SUBNET:-172.16.x.0/28}`). Docker's default address pools
on this NAS are nearly exhausted, so the /28 is allocated from the registry at
`/home/krit/momentary/proxy-research/findings/subnets.md` (outside the repo; add the
new row there before editing the compose).

Router names: the tailnet router is always `<service>-tailnet` (all 85 hostnames).
The private router is `<service>-private` in new stacks but plain `<service>` in 63
older ones; when editing an existing stack keep its name (renaming a router changes
nothing functional but makes the diff noisy), in a new stack use `-private`.

Label set (`<service>` is the compose service name, `<port>` its internal listening
port):
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
A service needs no `ports:` entry for tailnet or LAN access: Traefik reaches it over
`traefik-proxy`. Do not reference `${TAILSCALE_IP}` or bind a host port to `127.0.0.1`
for Tailscale reasons (the old `tailscale serve` mechanism is gone).

- **Bare `tls: "true"` on both routers: no `tls.certresolver`, no `tls.domains`.** The
  one wildcard certificate is requested by the `traefik-dashboard` router alone; a
  router with its own `certresolver` would request a second certificate and race it
  (mechanism: `core-infra-topology.md`, `traefik` entry). Verify a new hostname by the
  served certificate's issuer/SAN, not by absence of log errors: a missing certificate
  silently falls back to Traefik's self-signed default.
- **`hsts-headers@docker` first in `middlewares`** on every router (chains
  short-circuit, so a rejecting middleware listed before it would drop the HSTS header
  on 401/403). `tailnet-admin-only@docker` (the shared ipallowlist on the `traefik`
  service, owner device IPs only) goes after it, on the tailnet router only.
- **Never two entrypoints on one router** (comma-separated `entrypoints`; Traefik issue
  #11889), hence the separate `-tailnet` router.
- **Both routers are required.** The LAN wildcard sends every hostname to the private
  tier and the tailnet wildcard sends every hostname to the tailnet-admin gateway, so
  a hostname missing either router answers Traefik's own 404 on that path.
- **`${<SERVICE>_SUBDOMAIN}`**: always a dedicated `${VAR}` (e.g. `ACTUAL_BUDGET_SUBDOMAIN`),
  never a literal in the router rule (this repo is public). Default its *value* to the
  service's directory name, **except** when an established hostname already differs
  (ask the user to confirm before assuming). The established hostnames, overrides
  included, are in `.claude/rules/service-directory.md`.
- **`.env.example` and the Portainer env contain only variables the compose actually
  references**: drop a variable when the label or setting that used it goes.

**Entrypoint variables are numbered, never named after their tier** (this repo is
public; a variable *name* like `..._FAMILY` would leak the household's trust-tier
vocabulary): a service compose uses `TRAEFIK_ENTRYPOINT_3` (private, LAN) and
`TRAEFIK_ENTRYPOINT_7` (tailnet-admin), plain, without `:-` defaults. Values, ports,
entrypoint 6 and the retired numbers 1/2/4/5: `core-infra-topology.md`.

## Making a service public
Public access never goes through the core Traefik. It is a router, a service and a
per-app `public-<app>` network added to `traefik-public/docker-compose.yml`, plus a
DNS-only CNAME for the hostname in Cloudflare (Cloudflare is DNS hosting only),
following `traefik-public/README.md` (Operating rules, "Adding a public service").
The app's own compose
then also joins its external `public-<app>` network (created by the `traefik-public`
stack, which must be deployed first) and keeps its two ordinary routers, so the same
hostname still works on the LAN and the tailnet. Only do this when the user asks. The
current public hostnames are the "Public" column of `service-directory.md`.

## Giving a new service its own static LAN IP (macvlan)
A service that must be reachable directly on the LAN at its own IP (not through
Traefik), e.g. a DNS resolver on port 53, needs a macvlan network. **Docker allows only
ONE macvlan network per parent interface per subnet**: a second definition (even in
another stack) fails at deploy time with `failed to allocate gateway (<ip>): Address
already in use`.

**So join the existing one, never define a new one.** The repo's one macvlan network is
created by `traefik-private-forwarder` and is named
`traefik-private-forwarder_traefik_forwarder_net` (Compose's `<project>_<key>` naming,
no explicit `name:`). `adguard` and `traefik-public` already attach to it this way:
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
Never copy a `driver: macvlan` / `driver_opts` / `ipam` block into another stack. Only
`traefik-private-forwarder` (and the `macvlan-host-shim` helper) set `LAN_INTERFACE`,
which must be `bridge0` (`gotchas/macvlan-parent-bridge0.md`). Referencing the running
network by name changes nothing in `traefik-private-forwarder`'s own compose.

## Published host ports (bypass Traefik entirely): opt-in only
A published host port skips Traefik's TLS, HSTS and the tailnet allowlist, and is
reachable by every device that can reach the NAS. **It is not a default.** Add one only
when the user explicitly asks (typically bandwidth-heavy or large-upload services that
have their own login) or for a protocol Traefik cannot carry (Git over SSH is host port
2222, private only: `gitea-ssh.${DOMAIN}` is the one hostname the wildcards answer
with the NAS's own address, see `core-infra-topology.md`). Bind `0.0.0.0` for LAN
reach; `privatebin` and `sparkyfitness` bind `127.0.0.1` instead (loopback only).
Check the host-port table in `service-directory.md` (the single list of what is
published today) for a free port first, and record the new one there: the Docker
daemon rejects a duplicate bind late (the container just fails to start), not at
compose lint time.
