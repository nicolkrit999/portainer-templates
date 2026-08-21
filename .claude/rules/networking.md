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

## Host references (NAS)
Never hardcode host IPs in a committed compose file - reference them as
variables, with the real values in `.env` / Portainer stack env:
- `${NAS_IP}` - local network IP of the host (this instance's `.env.example`:
  `192.168.1.98`)
- `${DOCKER_GATEWAY_IP}` - Docker bridge gateway IP (this instance:
  `192.168.48.1`)

## Tailscale fallback (last resort only)
If Cloudflare Tunnel cannot be used, Tailscale is available - reference the
node via `${TAILSCALE_IP}`, never a hardcoded address (this instance's
`.env.example`: node `nicol-nas`, `100.101.189.91`). Always prefer Cloudflare.

**Host-port bind address, when a `tailscale serve` route may reuse the same
port number:** publish the port to `127.0.0.1` (`"127.0.0.1:<port>:<port>"`),
not `0.0.0.0`. A 2026-08 incident confirmed that `tailscaled` and
`docker-proxy` binding the *same port number to `0.0.0.0`* can race on
daemon/container restart - whichever binds first wins, and the loser's
container comes up with no network attachment at all (this broke Immich,
ActualBudget, and Portainer on one reboot). Ports published only to
`127.0.0.1` never hit this race, confirmed against five other same-port serve
routes on this instance that never failed. If a service genuinely needs
LAN-IP reachability (not just Cloudflare/Tailscale), keep the `0.0.0.0`
publish and instead point the `tailscale serve` listener at a *different*
port number.

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
