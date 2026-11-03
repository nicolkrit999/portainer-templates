# macvlan-host-shim

Host-side macvlan "shim" interface plus host routes, working around a Docker `macvlan` kernel-level limitation that otherwise breaks **[AdGuard Home](../adguard/)**'s conditional forwarding of internal-domain lookups to `dnsmasq`.

## The problem

Docker's `macvlan` networking has a well-known kernel-level restriction: the host's own network namespace (this includes the host OS itself, and any container using `network_mode: host`, such as this repo's `dnsmasq`) can **never** exchange traffic with anything attached to a `macvlan` network, in either direction. This isn't a bug or misconfiguration - it's how the Linux `macvlan` driver works (the parent interface's own address is categorically excluded from the switching domain its macvlan children live on).

Confirmed live on this NAS: `dnsmasq` (host-mode, its own LAN IP) could not reach `adguard`'s macvlan IP, and `adguard` (macvlan) could not reach `dnsmasq` either - AdGuard's own upstream-DNS test reported the host target as unreachable.

**Crucially, ARP/L2 address resolution between a macvlan container and the host is not the same as the host being reachable** - in testing, ARP resolved correctly even while actual data traffic (ICMP, then DNS) was silently dropped. Don't treat successful `ping`/ARP as proof this is fixed.

## The fix - three parts, all required

1. **A second macvlan interface created directly in the host's own network namespace** (this container is `network_mode: host`, `${MACVLAN_SHIM_IFACE}` on `${LAN_INTERFACE}`, address `${MACVLAN_SHIM_IP}/32`) - gives the host itself a legitimate presence on the same macvlan L2 segment, so it can be reached by (and reach) other macvlan-attached containers.
2. **A host-scope `/32` route for each macvlan-attached IP** (`${MACVLAN_ATTACHED_IPS}`), pointing at the shim interface. Without this, the shim's *reply* traffic still gets routed back out via the host's normal, broader, pre-existing LAN route instead of the shim - the exact same parent-exclusion restriction, just hit on the way out. This was the non-obvious part, only found via live testing: the interface alone was **not sufficient** - `nslookup` from inside AdGuard timed out even with the shim interface up, because the kernel's routing table preferred the broader pre-existing subnet route over the shim, and that broader route's egress is the macvlan parent interface itself.
3. **`dnsmasq` listens on the shim IP directly.** `dnsmasq` runs `network_mode: host`, so it binds `${MACVLAN_SHIM_IP}` itself (`--listen-address`, with `--bind-dynamic` because the interface lives in this separate stack); there is no relay in between. See `../dnsmasq/docker-compose.yml`.

The container applies parts 1 and 2 idempotently on every start, then sleeps; `restart: always` makes Docker re-apply them on every daemon start (i.e. every host boot). Its healthcheck verifies the interface address **and every route**, not just the interface.

History: until 2026-09-08 this container also ran a `socat` DNS relay; it was removed (commit `f563e30`) because `dnsmasq` can bind the shim IP itself, which also removed a `socat` UDP process-leak risk. Background: [`../adguard/INCIDENT-2026-09-08-dns-relay-outage.md`](../adguard/INCIDENT-2026-09-08-dns-relay-outage.md).

## Operational rule

AdGuard's conditional-forward upstream for your internal domain **must** point at the shim's IP (this instance: `192.168.1.95`), **never** the real internal resolver's own IP (`192.168.1.98`, `dnsmasq`) - the latter is permanently unreachable from AdGuard no matter what, by the same restriction described above. A past design had this pointed at the real IP - don't repeat that mistake.

Add an IP to `MACVLAN_ATTACHED_IPS` whenever another macvlan-attached service needs to reach the host (currently only AdGuard, `192.168.1.96`). `LAN_INTERFACE` must be `bridge0` on this NAS (see `.claude/rules/gotchas/macvlan-parent-bridge0.md`).

## Why a Compose service instead of an `/etc/rc.local` edit

This repo's convention is that all host-state-affecting configuration is git-tracked and reviewable through compose files, not raw vendor boot scripts, and every opinionated value is an `${VAR}`, not hardcoded. Same precedent as `tailscale`/`tailscale-admin`: a `network_mode: host` container with elevated capabilities manages real host-level network state from inside a container.

**This is load-bearing infrastructure** for AdGuard's DNS forwarding to `dnsmasq` - do not remove without re-verifying the macvlan limitation no longer applies.

## Compose gotcha worth keeping

The route loop's shell variable (`for ip in ...; do ip route add "$$ip/32" ...`) must stay `$$`-escaped in both the startup command and the healthcheck: Compose interpolates any bare `$IDENTIFIER` in the raw file text, not just `${VAR}`. Unescaped, every route-add became `ip route add "/32" ...`, which always fails and left the container permanently **unhealthy** (a leftover manual route masked the impact until the next reboot would have lost it). If you hit one bare-`$VAR` interpolation bug in a compose file, grep the rest of that file for the same pattern.
