# AdGuard Home

Network-wide DNS ad/tracker blocking ([AdGuard Home](https://github.com/AdguardTeam/AdGuardHome)), deployed as a self-contained DNS resolver on its own dedicated LAN IP via Docker `macvlan` - separate from this NAS's own IP, so it can bind port 53 without colliding with anything else on the host.

Access to the admin dashboard is intentionally **private-only** (Traefik `private` + `tailnet-admin` tiers, no public/Cloudflare route, no `family`/`guest` tier) - this is a household DNS/admin tool, not a user-facing app.

## Why `macvlan` instead of a normal Docker network

AdGuard needs to act as a real DNS server reachable at its own IP on the LAN (port 53, UDP+TCP). A container on Docker's default bridge network only gets a private, NAT'd IP that isn't reachable from other devices on the LAN - so this service joins a `macvlan` network instead, which gives it a genuine second LAN IP (`${ADGUARD_STATIC_IP}` - this instance: `192.168.1.96`) that any device on the network can reach directly, just like a separate physical machine would.

**Docker only allows one macvlan network per parent interface/subnet.** If your own homelab already has a macvlan network on the same LAN subnet (e.g. for another statically-addressed service), you cannot define a second one - every additional macvlan-attached service must join the *existing* network as `external: true` instead of declaring its own. See this repo's `.claude/rules/networking.md` ("Giving a new service its own static LAN IP (macvlan)") for the full pattern.

## The macvlan host-reachability limitation

Docker's `macvlan` networking has a kernel-level restriction: the host's own network namespace (and any `network_mode: host` container, like this repo's `dnsmasq`) can never exchange traffic with anything on a `macvlan` network, in either direction. That silently broke AdGuard's conditional forwarding of internal-domain lookups to `dnsmasq` - the fix (a host-side relay "shim") lives in the sibling stack **[`macvlan-host-shim`](../macvlan-host-shim/README.md)**, including why `ping`/ARP succeeding is *not* proof it's working. Read that README before touching either service's networking, or if you hit the same issue running any other DNS-serving container on `macvlan`.

**Operationally**: AdGuard's conditional-forward upstream for your internal domain must point at the shim's IP (this instance: `192.168.1.95`), never the real internal resolver's own IP (`192.168.1.98`) - the latter is permanently unreachable from AdGuard.

## Surviving an active Tailscale exit node

A device connected to Tailscale with an active exit node has its DNS bypass AdGuard entirely by default - Tailscale's own DNS override routes to whatever nameserver is registered for the tailnet, and normally nothing is. The fix - giving AdGuard its own Tailscale identity, registered as the tailnet's DNS server - lives in the sibling stack **[`tailscale-adguard`](../tailscale-adguard/README.md)**, including the required Tailscale admin-console steps and a real process-leak incident worth reading if you're building something similar.

### The `entrypoint:` patch this needs on AdGuard's own side

`tailscale-adguard`'s relay needs to reach AdGuard over the `traefik-proxy` Docker network, but AdGuard's DNS listener only binds to interfaces explicitly listed in its own `dns.bind_hosts` config (set once by the first-run wizard, no env var or later UI toggle) - by default just its macvlan IP. `adguard/docker-compose.yml`'s `entrypoint:` override patches `0.0.0.0` into `bind_hosts` on first start to fix this. Getting that patch right took three iterations worth knowing if you're writing something similar:

- **Docker Compose interpolates any bare `$IDENTIFIER` in the raw compose file text**, not just `${VAR}` - including inside a quoted shell script meant to run at container runtime. A shell-local variable assigned inside the script itself (not a real Compose/stack env var) gets silently substituted with an empty string before the container ever starts, with no error. Escape it as `$$IDENTIFIER` (Compose's literal-dollar escape) if your entrypoint/command script needs its own local shell variables.
- **Overriding `entrypoint:` without also setting `command:` silently clears the image's default `CMD`** - it is not preserved and passed through via `"$@"` automatically, contrary to what might be assumed. Explicitly restore the original default command args (check via `docker inspect` on the un-overridden image) or the app may silently start with no arguments and fall back to unexpected defaults.
- **When patching a config file's YAML by text-munging (awk/sed) instead of a real YAML parser, indentation mismatches are dangerous, not cosmetic.** Inserting a new list item at a different column than its sibling causes YAML to treat the two lines as one continued scalar rather than two list entries - this actually crashed AdGuard's config parser and put it in a restart loop in this deployment's history. Copy the sibling item's own leading whitespace rather than hardcoding an indent.
- **Any entrypoint patch that runs on every container start, combined with `restart: always`, means a latent bug compounds with every crash-restart cycle instead of failing once.** Gate one-time config mutations behind a persistent marker file (in the same bind-mounted volume) so they can run at most once per volume lifetime.

**A visibility limitation worth knowing**: every device using the Tailscale-relay path shows up in AdGuard's query log as the **same single client identity** (the relay container's own internal IP), not the real end-user device's IP - `socat`'s plain TCP/UDP relay doesn't preserve or forward the original source address. Per-client rules/stats in AdGuard won't distinguish between devices using this path.

## 2026-09-08 outage and planned fix

Two confirmed real outages (one CPU-contention-driven, one a genuine DNS
query burst) root-caused to the `socat` relay chain used by both
`tailscale-adguard` and `macvlan-host-shim` - both relays are getting
replaced. The `tailscale-adguard` canary (`dnsdist` alongside the still-live
`socat` relay) is deployed and confirmed healthy as of this write; cutover
and the `macvlan-host-shim` change are still pending. Full incident
writeup, ruled-out theories, and the fully-verified fix plan (4/4
independent reviews):
**[`INCIDENT-2026-09-08-dns-relay-outage.md`](INCIDENT-2026-09-08-dns-relay-outage.md)**.
Read that before re-investigating any AdGuard/Tailscale DNS outage.

## Configuration

| Variable | Purpose | This instance |
|---|---|---|
| `${ADGUARD_STATIC_IP}` | AdGuard's dedicated macvlan LAN IP | `192.168.1.96` |
| `${ADGUARD_SUBDOMAIN}` | Hostname segment for the private-tier Traefik router | `adguard` |
| `${VOLUME_CONFIG}` | Config/filter-list storage (fast pool) | see `.claude/rules/volumes.md` |
| `${VOLUME_DATA}` | Query logs/stats storage (bulk pool) | see `.claude/rules/volumes.md` |
| `${DOMAIN}`, `${TRAEFIK_ENTRYPOINT_3}`, `${TRAEFIK_ENTRYPOINT_7}` | Shared repo-wide Traefik vars, already set once on the `traefik` stack | see `.claude/rules/networking.md` |

AdGuard Home itself takes no environment-based configuration - everything (admin login, DNS rewrites, filter lists, upstream servers) is set through its own web UI on first run and persisted in `${VOLUME_CONFIG}/adguard/conf`.

## First-run setup

On first boot, AdGuard listens on port 3000 (setup wizard) before switching permanently to port 80 once configured. The setup wizard is **only reachable directly via the macvlan IP** (`http://192.168.1.96:3000`) from another device on the LAN - not from the Docker host itself (same macvlan limitation as above), and not yet through Traefik (which only forwards to port 80). Leave AdGuard's own built-in DHCP server **disabled** if, as in this deployment, your router/gateway remains the DHCP authority.

## Certificate group

This service is a non-anchor member of the `infra-ops` SAN-bundle certificate group - see `.claude/rules/san-cert-groups.md`. It carries bare `tls: "true"` with no `certresolver`/`tls.domains` of its own.
