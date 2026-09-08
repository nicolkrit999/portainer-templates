# traefik-private-forwarder

TCP-passthrough sidecar so private-tier Traefik access works at a clean `hostname:443` URL on the LAN - no port number to remember, no changes to Traefik's own container.

## What it does

A `socat` TCP-LISTEN on port 443, forwarding raw bytes to `traefik:${TRAEFIK_PORT_3}` (Traefik's private entrypoint, container-internal only). Pure SNI-passthrough - it does not terminate, inspect, or touch the TLS handshake in any way; all TLS/cert work still happens on Traefik's end exactly as it does for every other entrypoint.

Gets its own dedicated **macvlan** LAN IP (`${TRAEFIK_PRIVATE_IP}`) rather than giving Traefik's own container a second IP bind - a wildcard bind (family entrypoint) and a specific-IP bind can't coexist in the same network namespace, confirmed risk, deliberately avoided.

Deliberately not attached to `cloudflare-web` (LAN-only, not tunnel-reachable) and has no Traefik router labels of its own - it's infrastructure that exposes an IP, not a routed application; Traefik on the other end already owns routing/TLS for whatever it forwards to.

## The tailnet equivalent

`../tailscale-admin_traefik-tailnet-forwarder/` solves the identical problem (clean, no-port private-tier URL) for Tailscale-connected clients instead of LAN ones - via a different mechanism (shared Tailscale namespace instead of macvlan) since Tailscale's `tailscale0` interface is a TUN device, not a macvlan-attachable L2 NIC. See that stack's README for why it also needs PROXY-protocol injection, which this LAN-facing sidecar does not.

## Environment variables

| Variable | Purpose |
|---|---|
| `TRAEFIK_PRIVATE_IP` | This sidecar's dedicated macvlan LAN IP. |
| `LAN_INTERFACE` | Physical/bridge parent interface for the macvlan network (this NAS: `bridge0` - Virtual Network Bridging enslaves the physical NIC under it, so the macvlan `parent` must target `bridge0`, not the raw NIC). |
| `LAN_SUBNET`, `LAN_GATEWAY` | The LAN's real subnet/gateway, for the macvlan network's IPAM config. |
| `TRAEFIK_PORT_3` | Traefik's private-entrypoint port (matches `../traefik/`'s own env). |

## Adding another macvlan-based service later

**Docker only allows one macvlan network per parent interface per subnet.** This container creates the one live macvlan network in this repo (`traefik-private-forwarder_traefik_forwarder_net`, default Compose naming - never given an explicit `name:` override). Any future service needing its own static LAN IP must join this *existing* network as `external: true` rather than defining a new macvlan network on the same subnet - a second definition fails at deploy time with `failed to allocate gateway: Address already in use` (confirmed real failure, 2026-09-06). See `.claude/rules/networking.md`'s macvlan section for the exact pattern to copy.
