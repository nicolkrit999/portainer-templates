---
name: tailscale-adguard-service
description: tailscale-adguard stack - 3rd Tailscale identity giving AdGuard a tailnet IP (exit-node DNS-bypass fix); dnsdist relay sharing its namespace via network_mode:service:
metadata:
  type: project
---

`tailscale-adguard/docker-compose.yml` (+ `README.md`, which is the authoritative description).

**Purpose:** give AdGuard Home (`adguard/`) its own tailnet IP so it can be registered in the Tailscale admin console as the tailnet's DNS server. A device with an active exit node otherwise bypasses AdGuard because nothing is registered as the tailnet nameserver. Registering the IP, and disabling key expiry on the node, are manual admin-console steps outside this repo.

**Three services in ONE compose file** (so the same-project `network_mode: service:` form is valid; contrast with the cross-stack `container:` form that the tailnet-admin pair used before its merge):
- `tailscale-adguard`: third independent Tailscale identity (ordinary networking, `NET_ADMIN`+`SYS_MODULE`, `/dev/net/tun`, `TS_USERSPACE=false`), static IP `${TAILSCALE_ADGUARD_INTERNAL_IP}` on `traefik-proxy` (default `172.27.255.248`), `net.ipv4.ip_unprivileged_port_start=0` so the relay can bind :53 unprivileged, `cpu_shares: 4096`, `oom_score_adj: -800`, `restart: always`. Advertises no subnet routes.
- `dnsdist-config-init`: alpine one-shot that regenerates `dnsdist.yml` and `dnsdist-client.conf` on EVERY deploy (dnsdist YAML has no `${VAR}` interpolation; always-write avoids stale-file manual deletes).
- `dns-relay`: `powerdns/dnsdist-20:2.0.9` in `tailscale-adguard`'s namespace, forwards :53 to `${ADGUARD_INTERNAL_IP}`. It replaced a `socat` relay on 2026-09-08 after two household-wide outages (socat `fork` leaks one child per UDP peer; dnsdist is event-driven); incident and burst-test results: `adguard/INCIDENT-2026-09-08-dns-relay-outage.md`. If you ever write a `socat ...,fork` UDP relay, pair it with `-T<seconds>`.

**Gotchas kept from the incident:** the dnsdist healthcheck must authenticate through the client config file (`-C ... -c -e 'showVersion()'`); `-k/--setkey` silently fails auth in 2.0.9 and the CLI still exits 0, giving a false-positive health. `network_mode: service:` does not share cgroups, so the relay needs its own `cpu_shares`. dnsdist resolves its backend IP once at startup, so `ADGUARD_INTERNAL_IP` must match `adguard`'s static IP exactly.

**No Traefik routers** (Tailscale-only, no HTTP surface, like `iperf3/`). Portainer needs the real `TS_AUTHKEY_ADGUARD` and `DNSDIST_CONSOLE_KEY` (never print or commit them); the other variables have defaults in `.env.example`.

Sibling pattern: [[tailscale_admin_traefik_tailnet_forwarder_service]].
