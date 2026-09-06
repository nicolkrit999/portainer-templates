# AdGuard Home

Network-wide DNS ad/tracker blocking ([AdGuard Home](https://github.com/AdguardTeam/AdGuardHome)), deployed as a self-contained DNS resolver on its own dedicated LAN IP via Docker `macvlan` - separate from this NAS's own IP, so it can bind port 53 without colliding with anything else on the host.

Access to the admin dashboard is intentionally **private-only** (Traefik `private` + `tailnet-admin` tiers, no public/Cloudflare route, no `family`/`guest` tier) - this is a household DNS/admin tool, not a user-facing app.

## Why `macvlan` instead of a normal Docker network

AdGuard needs to act as a real DNS server reachable at its own IP on the LAN (port 53, UDP+TCP). A container on Docker's default bridge network only gets a private, NAT'd IP that isn't reachable from other devices on the LAN - so this service joins a `macvlan` network instead, which gives it a genuine second LAN IP (`${ADGUARD_STATIC_IP}` - this instance: `192.168.1.96`) that any device on the network can reach directly, just like a separate physical machine would.

**Docker only allows one macvlan network per parent interface/subnet.** If your own homelab already has a macvlan network on the same LAN subnet (e.g. for another statically-addressed service), you cannot define a second one - every additional macvlan-attached service must join the *existing* network as `external: true` instead of declaring its own. See this repo's `.claude/rules/networking.md` ("Giving a new service its own static LAN IP (macvlan)") for the full pattern.

## ⚠️ The Docker macvlan limitation this deployment works around

This is the part worth understanding if you're adapting this repo for your own setup: **Docker's `macvlan` networking has a well-known kernel-level restriction - the Docker host's own network namespace (the host OS itself, and any container using `network_mode: host`) can never exchange traffic with anything on a `macvlan` network, in either direction.** This isn't a bug or a misconfiguration; it's how the Linux `macvlan` driver works by design (the parent interface's own address is categorically excluded from the switching domain its macvlan children live on).

In this deployment, that meant:
- `adguard` (macvlan, `192.168.1.96`) could not reach this NAS's own LAN-facing DNS resolver (`dnsmasq`, `network_mode: host`, bound to the NAS's own IP) - so AdGuard's conditional forwarding of internal-domain DNS lookups to `dnsmasq` failed outright.
- The reverse direction failed too (the host, or any host-networked container, cannot reach `adguard`'s macvlan IP either) - confirmed both ways during development.

Crucially, **ARP/L2 address resolution between a macvlan container and the host is not the same as the host being reachable** - in testing, ARP resolved correctly even while actual data traffic (ICMP, then DNS) was silently dropped. Don't treat successful `ping`/ARP as proof this is fixed.

### The workaround: a macvlan "shim" + DNS relay + host route

See the sibling service **[`macvlan-host-shim`](../macvlan-host-shim/)** in this repo for the actual fix, which has three parts:

1. **A second macvlan interface created directly in the host's own network namespace** (not inside a container) - this gives the host itself a legitimate presence on the same macvlan L2 segment, so it can be reached by (and reach) other macvlan-attached containers like this one.
2. **A DNS relay** running in that same host-namespace container, listening on the shim's own IP and forwarding to the real host-networked DNS resolver (`dnsmasq`) - because the shim's new address is *not* the same as the host's original, still-unreachable-from-macvlan address.
3. **A host-scope route** for each macvlan-attached IP, pointing at the shim interface. Without this, the shim's *reply* traffic still gets routed back out via the host's normal (pre-existing, broader) LAN route instead of the shim - which is the exact same parent-interface restriction, just hit on the way out instead of the way in. This was the non-obvious part: the interface and relay alone were not sufficient, and this needed a live test to actually discover.

**Operationally, this means:** AdGuard's own "conditional forwarding" / upstream DNS configuration for your internal domain must point at the shim's IP (this instance: `192.168.1.95`), never at the real internal resolver's own IP (this instance: `192.168.1.98`, `dnsmasq`) - the latter is permanently unreachable from AdGuard no matter what, by the same restriction described above.

If you're deploying AdGuard Home (or any other DNS-serving container) on `macvlan` in your own environment and it can't reach another DNS resolver running directly on the host, this is almost certainly the same issue - see `macvlan-host-shim/docker-compose.yml`'s inline comments for the exact commands and reasoning.

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
