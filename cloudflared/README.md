# cloudflared

The Cloudflare Tunnel connector - the household's fully independent public-internet access path. Nothing in the Tailscale/tailnet-admin plumbing (`tailscale`, `tailscale-admin_traefik-tailnet-forwarder`, `dnsmasq-tailnet`) affects this path at all, and vice versa.

## What it does

Runs the `cloudflared` tunnel client, authenticated via `${TOKEN}` (a Cloudflare Tunnel token, not the DNS API token used by `../traefik/`'s ACME challenge - different credential, different purpose). Attached only to `cloudflare_web_network` - every service reachable via the tunnel is attached to that same external network (`.claude/rules/networking.md`).

Public-hostname routing (which hostname maps to which internal container:port) is configured entirely in the **Cloudflare Tunnel dashboard**, not in this repo - this compose file only runs the connector itself.

## Environment variables

| Variable | Purpose |
|---|---|
| `TOKEN` | Cloudflare Tunnel token (secret) - authenticates this connector to the tunnel. |
| `TZ` | Standard timezone. |
| `DOCKER_CONFIG_DIR` | Base path for this container's persistent config. |

## Adding a new tunneled service

After writing/modifying any compose file attached to `cloudflare_web_network`, the Cloudflare Tunnel dashboard needs a matching public-hostname entry pointing at `http://<container_name_or_service>:<internal_port>` (or `http://host.docker.internal:<host_port>` for a service reached on the host rather than this network) - see `.claude/rules/networking.md`'s "Cloudflare connector handoff" section for the exact convention. This repo tracks the compose side only; the tunnel dashboard's own hostname list is the source of truth for what's actually routed and is not mirrored here.
