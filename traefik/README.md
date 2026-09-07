# traefik

The single reverse proxy and TLS-termination point for every hostname in this repo. Owns HTTP(S) routing, certificates, and per-service access rules. Every other core infra stack (`traefik-private-forwarder`, `tailscale-admin_traefik-tailnet-forwarder`, `dnsmasq`/`dnsmasq-tailnet`, `cloudflared`) exists purely to get the right traffic to this container's front door with the right source IP intact - none of them touch Traefik's own routing/TLS logic.

Two containers: `fix-permissions` (a one-shot init container that fixes `acme.json`'s ownership/permissions on start, since Traefik refuses to run otherwise) and `traefik` itself.

## Entrypoints (access tiers)

Numbered generically on purpose - this repo is public, and even a variable *name* like `TRAEFIK_ENTRYPOINT_FAMILY` would leak this household's trust-tier vocabulary. Only the *value* describes the tier.

| Entrypoint | Tier (this instance's mapping) | Port | Host-published? |
|---|---|---|---|
| `TRAEFIK_ENTRYPOINT_1` | family | 443 | yes |
| `TRAEFIK_ENTRYPOINT_2` | guest | 8443 | yes |
| `TRAEFIK_ENTRYPOINT_3` | private (`asDefault`) - the default for new services | 8444 | yes, but internal-use only (see below) |
| `TRAEFIK_ENTRYPOINT_4` | friends | 8445 | yes |
| `TRAEFIK_ENTRYPOINT_5` | internal, `cloudflared`-facing only | 9080 | no |
| `TRAEFIK_ENTRYPOINT_6` | internal, ping/dashboard-API only | 8080 | no |
| `TRAEFIK_ENTRYPOINT_7` | tailnet-admin - admin-gated, no host port | 8446 | no - reached only via `../tailscale-admin_traefik-tailnet-forwarder/` |

The private entrypoint's port (8444) is deliberately never `443` - that would collide with the family entrypoint's own wildcard `:443` bind inside this same container. Clean, no-port private-tier access is handled entirely by `../traefik-private-forwarder/` (LAN, macvlan) and `../tailscale-admin_traefik-tailnet-forwarder/` (tailnet), never by this container binding a second address itself.

Plain HTTP on port 80 is redirect-only (to the family entrypoint) - without it, any client defaulting to `http://` gets connection-refused instead of a clean redirect (confirmed real "could not connect" report, 2026-08-22). Well-known ports 80/443 are reserved for infra services; a conflicting app should move its own port instead.

## Certificates: SAN-bundle groups

Traefik's naive default is one ACME certificate per router - with ~80 hostnames on one domain, that burns through Let's Encrypt's 50-certs/week/domain rate limit fast (two real incidents in this repo's history). Fixed by bundling related hostnames into 6 groups, each backed by one multi-SAN certificate requested by a single "anchor" router per group. Full mechanism, the group table, and the mandatory rules for adding a router to a group (get this wrong and you silently re-trigger the rate-limit problem) are in `.claude/rules/san-cert-groups.md` - read it before touching `tls.certresolver`/`tls.domains` on any router anywhere in this repo.

**Confirmed live bug, not a style preference**: once a router sets `tls: "true"`, it overrides the entrypoint's own `tls.certresolver` default entirely - every router needs its cert config explicit (either the anchor's full `certresolver`+`domains`, or nothing at all if it's a bundle member).

## The tailnet-admin path

Every private-tier-only service also gets a second router on `TRAEFIK_ENTRYPOINT_7`, giving Tailscale-connected admin devices a clean, port-free URL instead of appending the private tier's host port. Gated by the shared `tailnet-admin-only` IP-allowlist middleware (defined on this container, `TAILNET_ADMIN_IPS` - specific known device IPs, deliberately never the full Tailscale CGNAT range). This only works because tailnet traffic arrives via `../tailscale-admin_traefik-tailnet-forwarder/`'s PROXY-protocol forwarder, not a published port - see that stack's own README for why (`docker-proxy` rewrites source IPs on any published port, which would otherwise defeat the allowlist entirely). `proxyProtocol.trustedIPs` on this entrypoint trusts PROXY headers only from that forwarder's own known static IP (`TAILSCALE_ADMIN_INTERNAL_IP`).

## Environment variables

| Variable | Purpose |
|---|---|
| `DOMAIN` | Base domain; routers are host-matched as `<service>.${DOMAIN}`. |
| `CF_DNS_API_TOKEN` | Cloudflare DNS API token (Zone:DNS:Edit) for the ACME DNS-01 challenge. |
| `ACME_EMAIL` | Email registered with Let's Encrypt. |
| `TRAEFIK_DASHBOARD_HTPASSWD` | Pre-generated `user:apr1-hash` string for dashboard basic auth. |
| `TRAEFIK_ENTRYPOINT_1..7` / `TRAEFIK_PORT_1..7` | Entrypoint names/ports - see table above. |
| `TRAEFIK_INTERNAL_IP` | This container's own static IP on `traefik-proxy` - other sidecars target it directly since they can't always resolve it by name. |
| `TAILNET_ADMIN_IPS` | Comma-separated `/32` CIDRs for the tailnet-admin allowlist. |
| `TAILSCALE_ADMIN_INTERNAL_IP` | The tailnet-admin forwarder's own static IP - the only address the tailnet-admin entrypoint trusts PROXY headers from. |
| `VOLUME_CONFIG`, `TZ` | Shared conventions. |

## Deployment gotchas

- **Never add an explicit `ipam:` block to `traefik_proxy_network`.** Confirmed real outage (2026-08-22): Compose treats an added `ipam:` block as a network config change and tries to remove+recreate the network to apply it, even when the subnet matches exactly. Docker blocks the removal (the network has ~55 other active endpoints) and the whole redeploy fails with Traefik's container already gone. The network already exists live (subnet `172.27.0.0/16`) and is deliberately *not* `external: true` - Compose reuses it as-is as long as this file doesn't declare a diverging config.
- **This container is core infra** - read `.claude/rules/core-infra-topology.md` fully before any structural change (network mode, image, CLI flags, entrypoints, capabilities).
