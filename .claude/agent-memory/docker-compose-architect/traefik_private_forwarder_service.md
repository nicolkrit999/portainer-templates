---
name: traefik-private-forwarder-service
description: traefik-private-forwarder - socat TCP passthrough on a macvlan LAN IP forwarding to Traefik entrypoint 3; owns the one live macvlan network
metadata:
  type: project
---

`traefik-private-forwarder/docker-compose.yml` (+ `README.md`, authoritative). It is the LAN path: `dnsmasq` answers every `*.${DOMAIN}` name with this container's macvlan IP `${TRAEFIK_PRIVATE_IP}` (`.99` on this LAN), and it forwards raw TCP to Traefik's private entrypoint. See `.claude/rules/core-infra-topology.md` for the whole picture.

- **Image/command:** `alpine/socat:1.8.0.3`; the image's entrypoint is `socat`, so `command:` is just `TCP-LISTEN:443,fork,reuseaddr TCP:traefik:${TRAEFIK_PORT_3}`. Pure TCP/SNI passthrough: Traefik keeps all TLS and certificate work.
- **Why a separate macvlan container:** a wildcard bind and a specific-IP bind cannot coexist in one network namespace, so Traefik's own container is not given a second IP.
- **Networks:** `traefik_forwarder_net` (macvlan, `parent: ${LAN_INTERFACE}`, which must be `bridge0` on this NAS: `.claude/rules/gotchas/macvlan-parent-bridge0.md`; subnet/gateway from `${LAN_SUBNET}`/`${LAN_GATEWAY}`; `ip_range` is the single address) and `traefik-proxy` (to reach `traefik:${TRAEFIK_PORT_3}` by name). Compose names the macvlan network `traefik-private-forwarder_traefik_forwarder_net`; `traefik-public` and any other stack needing its own LAN IP join it as `external: true` (Docker allows one macvlan network per parent/subnet).
- **No Traefik labels** on itself (infrastructure exposing an IP, not a routed app); LAN only.
- **`restart: always`** (critical path, same tier as Traefik; unlike the manual-only dnsmasq stopgap), `cpu_shares: 4096`, healthcheck `nc -z 127.0.0.1 443`.
- The NAS host cannot reach a macvlan IP on its own parent interface; test from another LAN device.
