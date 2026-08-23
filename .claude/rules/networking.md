---
description: Networking, hostnames, and Cloudflare Tunnel conventions for compose files.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Networking & Cloudflare Tunnel

## Hostname convention
Unless the user specifies otherwise, a service's public hostname is
`<service-name>.${DOMAIN}`, using dashes for multi-word names
(`n8n.${DOMAIN}`, `uptime-kuma.${DOMAIN}`, `actual-budget.${DOMAIN}`).
Use this default for `N8N_HOST`, `WEBHOOK_URL`, and any hostname/URL env vars -
never hardcode a real domain in a committed compose file. The actual domain
lives in `.env` / Portainer stack env (this instance: `DOMAIN=nicolkrit.ch` in
`.env.example`).

## Cloudflare Tunnel network
**Default: every user-facing application service is attached to the Cloudflare
Tunnel.** Do not ask, do not skip - if in doubt, use Cloudflare. Only omit it
when the user explicitly says a service is internal-only, or when the service is
a backing dependency (database, cache, message broker, migration job) that must
never be publicly reachable.

Services on the Cloudflare Tunnel need this exact configuration.

Top-level networks block (always at the end of the file):
```yaml
networks:
  cloudflare_web_network:
    name: cloudflare-web
    external: true
```

Per-service reference:
```yaml
networks:
  - cloudflare_web_network
```

- Network key is always `cloudflare_web_network`; the Docker network name is
  always `cloudflare-web`; always `external: true`.
- Internal-only services (databases, caches) do **not** need this network - use
  the default bridge or a named internal network.
- A service with both internal deps and external access includes both networks.

## Traefik reverse-proxy network
**Default: every user-facing application service is ALSO attached to the
Traefik network, with a router on the `private` tier only, in addition to
`cloudflare_web_network` above - not instead of it.** Both networks are
default-on together; this is additive, not a choice between the two. Only
ask the user whether to add further tiers (`family`/`guest`/`friends`) -
never ask whether to add Traefik-private access at all, and never skip it
for the same categories of service that skip Cloudflare (internal-only
backing dependencies).

Top-level networks block addition (`external: true` in every service's own
compose - only `traefik/docker-compose.yml` itself creates the network):
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

Default label set (private-only - `<service>` is the compose service name,
`<port>` its internal listening port):
```yaml
labels:
  traefik.enable: "true"
  traefik.http.routers.<service>.rule: "Host(`${<SERVICE>_SUBDOMAIN}.${DOMAIN}`)"
  traefik.http.routers.<service>.entrypoints: "${TRAEFIK_ENTRYPOINT_3}"
  traefik.http.routers.<service>.tls: "true"
  traefik.http.routers.<service>.tls.certresolver: "cf_dns"
  traefik.http.routers.<service>.service: "<service>"
  traefik.http.services.<service>.loadbalancer.server.port: "<port>"
  traefik.docker.network: "traefik-proxy"
```

**⚠️ `tls.certresolver` must be set explicitly on the router, every time -
this is a confirmed live bug, not a style preference.** Once a router sets
its own `tls: "true"`, it overrides the entrypoint's `tls.certresolver`
default entirely (confirmed against Traefik's own community docs and a real
production incident on this instance, 2026-08-21). Omitting the router-level
`tls.certresolver` label produces **no error and no crash** - Traefik just
silently falls back to serving its self-signed `TRAEFIK DEFAULT CERT`
forever. Verify by checking the certificate issuer after any change, not by
absence of errors in the logs.

**`${<SERVICE>_SUBDOMAIN}` naming:** always a dedicated `${VAR}` (e.g.
`ACTUAL_BUDGET_SUBDOMAIN`), never a hardcoded literal in the router rule -
this repo is public and even the service-specific hostname segment counts as
an opinionated value. Default the variable's *value* to the service's
directory name, **except** when a legacy Cloudflare hostname already exists
for that service and differs from it - ask the user to confirm before
assuming. Known overrides so far: `actual-budget`→`budget`, `immich`→`foto`,
`homehub`→`casa`, `mealie`→`ricette`, `surmai`→`viaggi`,
`mini-qr`→`miniqr`, `omni-tools`→`omnitools`,
`easy-appointments`→`appuntamenti`, `ghost`→`blog`, `vikunja`→`promemoria`.

**Entrypoint variables - generically numbered on purpose, never named after
their tier** (this repo is public; even a var *name* like
`TRAEFIK_ENTRYPOINT_FAMILY` would leak this household's trust-tier
vocabulary - only the *value* should describe the tier, per an explicit
household-member decision, 2026-08-21):

| Variable | Meaning this instance | Port var | Port |
|---|---|---|---|
| `TRAEFIK_ENTRYPOINT_1` | family tier | `TRAEFIK_PORT_1` | 443 |
| `TRAEFIK_ENTRYPOINT_2` | guest tier | `TRAEFIK_PORT_2` | 8443 |
| `TRAEFIK_ENTRYPOINT_3` | private tier (`asDefault`) - **the default for new services** | `TRAEFIK_PORT_3` | 8444 |
| `TRAEFIK_ENTRYPOINT_4` | friends tier | `TRAEFIK_PORT_4` | 8445 |
| `TRAEFIK_ENTRYPOINT_5` | internal, `cloudflared`-facing only, no host port | `TRAEFIK_PORT_5` | 9080 |
| `TRAEFIK_ENTRYPOINT_6` | internal, ping/dashboard-API only, no host port | `TRAEFIK_PORT_6` | 8080 |
| `TRAEFIK_ENTRYPOINT_7` | tailnet-admin - admin-gated, no host port (see below) | n/a | n/a |

**Ask the user, every time a new service is added: does this need to be
reachable beyond your own private access (family/guest/friends), or is
private-only (the default) correct?** If they want an additional tier, add
a **separate router label block per entrypoint** - e.g.
`traefik.http.routers.<service>-family.*` alongside
`traefik.http.routers.<service>.*` (which stays `private`) - never a single
router with a comma-separated `entrypoints` value (Traefik GitHub issue
#11889: this doesn't bind cleanly to a single router in practice). Each
additional router block needs its own `tls.certresolver` label too, per the
gotcha above.

## Tailnet-admin clean-URL router (default, additive on top of `private`)

**Every private-tier-only service also gets a second router on
`${TRAEFIK_ENTRYPOINT_7}` (`tailnet-admin`) by default, no confirmation
needed** - this became standard for all 53+ private-tier services in
2026-08-23's rollout (GitHub PR #2) and applies to every new one going
forward. It gives admin-allowlisted Tailscale devices a clean, port-free
URL (same hostname as the private router) instead of having to append the
private tier's host port. Add this block alongside the private router,
same `Host()` rule, same service name:

```yaml
labels:
  traefik.http.routers.<service>-tailnet.rule: "Host(`${<SERVICE>_SUBDOMAIN}.${DOMAIN}`)"
  traefik.http.routers.<service>-tailnet.entrypoints: "${TRAEFIK_ENTRYPOINT_7}"
  traefik.http.routers.<service>-tailnet.tls: "true"
  traefik.http.routers.<service>-tailnet.service: "<service>"
  traefik.http.routers.<service>-tailnet.middlewares: "hsts-headers@docker,tailnet-admin-only@docker"
```

No `tls.certresolver`/`tls.domains` on this router - it shares the same
backing service as the private router, so it rides on whatever cert that
hostname already gets via its SAN-bundle group (Rule 8 elsewhere in this
file's sibling docs), it doesn't request its own. `tailnet-admin-only@docker`
is the shared ipallowlist middleware, already defined once on the `traefik`
service itself - always list it **after** `hsts-headers@docker` (middleware
chains short-circuit, and HSTS should still apply even on a rejected
request). Full mechanism (why this needs a dedicated entrypoint + a second
Tailscale identity + PROXY protocol, not just a plain Tailscale IP bind) is
in `.claude/rules/core-infra-topology.md` - read it before touching any of
the stacks that implement this path (`traefik-tailnet-forwarder`,
`tailscale-admin`, `dnsmasq-tailnet`'s admin override list), though adding
this router block to an ordinary new service needs none of that caution.

## Host references (NAS)
Never hardcode host IPs in a committed compose file - reference them as
variables, with the real values in `.env` / Portainer stack env:
- `${NAS_IP}` - local network IP of the host (this instance's `.env.example`:
  `192.168.1.98`)
- `${DOCKER_GATEWAY_IP}` - Docker bridge gateway IP (this instance:
  `192.168.48.1`)

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
(`jellyfin`, `plex`, `navidrome`, `gitea`, `duplicati`, `convertx`,
`filebrowser`, `stirling-pdf`, `audiobookshelf` as of 2026-08-23) also
publish a plain HTTP host port so they can be reached directly over LAN or
Tailscale without going through Traefik's TLS termination at all - useful
when Cloudflare's ~100MB upload limit or Traefik's overhead is a real
problem for that specific service, and only for services that already
have their own login (this bypasses HSTS/TLS and, for tailnet-admin
services, the ipallowlist middleware too). **This is not a default** - only
add a host-port publish when the user explicitly asks for LAN-speed direct
access for a specific service, bind to `0.0.0.0` (not `127.0.0.1` - see
above, the old race this used to guard against no longer applies), and
record the chosen port in `.claude/rules/service-directory.md`'s port table
first to avoid colliding with another service's already-published port -
duplicate host-port bindings fail silently late (the losing container just
won't start) rather than at compose lint time.

## Cloudflare connector handoff
After writing/modifying any compose attached to `cloudflare_web_network`, state
the exact connector target for the Tunnel public-hostname config:

> Cloudflare Tunnel target: `http://<container_name_or_service>:<internal_port>`

Use the service/`container_name` as host (it resolves inside the `cloudflare-web`
network) and the **internal** port (tunneled services don't publish ports).

**Exception - services NOT on `cloudflare_web_network`** (reached on the host,
e.g. Portainer itself, or composes that only expose ports to localhost):

> Cloudflare Tunnel target: `http://host.docker.internal:<host_port>`

Use the host-mapped port from `ports:`, not the internal container port. Example:
NAS web UI (`nas.${DOMAIN}`) on host port 9443 → `https://host.docker.internal:9443`.
