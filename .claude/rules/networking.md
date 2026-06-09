---
description: Networking, hostnames, and Cloudflare Tunnel conventions for compose files.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Networking & Cloudflare Tunnel

## Hostname convention
Unless the user specifies otherwise, a service's public hostname is
`<service-name>.nicolkrit.ch`, using dashes for multi-word names
(`n8n.nicolkrit.ch`, `uptime-kuma.nicolkrit.ch`, `actual-budget.nicolkrit.ch`).
Use this default for `N8N_HOST`, `WEBHOOK_URL`, and any hostname/URL env vars.

## Cloudflare Tunnel network
**Default: every user-facing application service is attached to the Cloudflare
Tunnel.** Do not ask, do not skip — if in doubt, use Cloudflare. Only omit it
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
- Internal-only services (databases, caches) do **not** need this network — use
  the default bridge or a named internal network.
- A service with both internal deps and external access includes both networks.

## Host references (NAS)
- Local network IP: `192.168.1.98`
- Docker gateway IP: `192.168.48.1`

## Tailscale fallback (last resort only)
If Cloudflare Tunnel cannot be used, Tailscale is available. NAS node name
`nicol-nas`, IP `100.101.189.91`. Always prefer Cloudflare.

## Cloudflare connector handoff
After writing/modifying any compose attached to `cloudflare_web_network`, state
the exact connector target for the Tunnel public-hostname config:

> Cloudflare Tunnel target: `http://<container_name_or_service>:<internal_port>`

Use the service/`container_name` as host (it resolves inside the `cloudflare-web`
network) and the **internal** port (tunneled services don't publish ports).

**Exception — services NOT on `cloudflare_web_network`** (reached on the host,
e.g. Portainer itself, or composes that only expose ports to localhost):

> Cloudflare Tunnel target: `http://host.docker.internal:<host_port>`

Use the host-mapped port from `ports:`, not the internal container port. Example:
NAS web UI (`nas.nicolkrit.ch`) on host port 9443 → `https://host.docker.internal:9443`.
