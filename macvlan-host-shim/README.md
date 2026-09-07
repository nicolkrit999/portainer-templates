# macvlan-host-shim

Host-side macvlan "shim" interface plus an active DNS relay, working around a Docker `macvlan` kernel-level limitation that otherwise breaks **[AdGuard Home](../adguard/)**'s conditional forwarding of internal-domain lookups to `dnsmasq`.

## The problem

Docker's `macvlan` networking has a well-known kernel-level restriction: the host's own network namespace (this includes the host OS itself, and any container using `network_mode: host`, such as this repo's `dnsmasq`) can **never** exchange traffic with anything attached to a `macvlan` network, in either direction. This isn't a bug or misconfiguration - it's how the Linux `macvlan` driver works (the parent interface's own address is categorically excluded from the switching domain its macvlan children live on).

Confirmed live on this NAS: `dnsmasq` (host-mode, its own LAN IP) could not reach `adguard`'s macvlan IP, and `adguard` (macvlan) could not reach `dnsmasq` either - AdGuard's own upstream-DNS test reported the host target as unreachable.

**Crucially, ARP/L2 address resolution between a macvlan container and the host is not the same as the host being reachable** - in testing, ARP resolved correctly even while actual data traffic (ICMP, then DNS) was silently dropped. Don't treat successful `ping`/ARP as proof this is fixed.

## The fix - three parts, all required

1. **A second macvlan interface created directly in the host's own network namespace** (not inside a container) - gives the host itself a legitimate presence on the same macvlan L2 segment, so it can be reached by (and reach) other macvlan-attached containers.
2. **A DNS relay** (`socat`, UDP+TCP) running in that same host-namespace container, bound only to the shim's own IP (never `0.0.0.0` - `dnsmasq` already holds the NAS's own IP:53 specifically), forwarding to the real host-networked `dnsmasq`. Since this container is `network_mode: host` (same netns as `dnsmasq`), it has unrestricted access there - the macvlan restriction only applies to macvlan-child-to-parent traffic, not ordinary same-netns routing.
3. **A host-scope `/32` route for each macvlan-attached IP**, pointing at the shim interface. Without this, the shim's *reply* traffic still gets routed back out via the host's normal, broader, pre-existing LAN route instead of the shim - the exact same parent-exclusion restriction, just hit on the way out. This was the non-obvious part, only found via live testing: the interface and relay alone were **not sufficient** - `nslookup` from inside AdGuard timed out even with the shim interface up and the relay listening, because the kernel's routing table preferred the broader pre-existing subnet route over the shim, and that broader route's egress is the macvlan parent interface itself.

## Operational rule

AdGuard's conditional-forward upstream for your internal domain **must** point at the shim's IP (this instance: `192.168.1.95`), **never** the real internal resolver's own IP (`192.168.1.98`, `dnsmasq`) - the latter is permanently unreachable from AdGuard no matter what, by the same restriction described above. A past design had this pointed at the real IP - don't repeat that mistake.

## Why a Compose service instead of an `/etc/rc.local` edit

This repo's convention is that all host-state-affecting configuration is git-tracked and reviewable through compose files, not raw vendor boot scripts, and every opinionated value is an `${VAR}`, not hardcoded. Same precedent as `tailscale`/`tailscale-admin`: a `network_mode: host` container with elevated capabilities manages real host-level network state from inside a container, persisted via `restart: always` (Docker re-applies these on every daemon start, i.e. every host boot).

**This is load-bearing infrastructure** for AdGuard's DNS forwarding to `dnsmasq` - do not remove without re-verifying the macvlan limitation no longer applies.

## Two incidents worth knowing if you're adapting this

**Process leak**: `socat`'s `fork` mode never terminates a forked child that handled a UDP query - UDP has no "connection closed" signal, so each child just sits there indefinitely waiting for more traffic from that same peer. This relay carries much less traffic than its sibling in `tailscale-adguard` (only internal conditional-forward lookups, not general household DNS) so it hadn't hit the failure point when found (21 processes vs. 2000+ on the busier relay), but had the identical latent bug. Fixed by adding `-T5` (5-second inactivity timeout) to both `socat` invocations - see `tailscale-adguard/README.md` for the full incident and verification, since it's where the bug was actually caught in production.

**`$ip` interpolation bug**: the route-repair loop (`for ip in ...; do ip route add "$ip/32" ...`) used a shell-local loop variable that Docker Compose silently interpolated to an empty string - Compose interpolates any bare `$IDENTIFIER` in the raw compose file text, not just `${VAR}`, including shell-local variables never meant to be Compose stack env vars. This turned every route-add into `ip route add "/32" ...`, which always fails, leaving this container permanently reporting **unhealthy**. A leftover route from an earlier one-off manual fix masked the practical impact - the internal-domain path kept working since the route already existed at the kernel level (host routes survive container recreates, since this runs `network_mode: host`) - but it would have failed for real on the next NAS reboot, when that manual route would finally be gone. Fixed by escaping the loop variable as `$$ip` in both the startup command and the healthcheck test (both had the identical bug). If you hit one bare-`$VAR` interpolation bug in a compose file, grep the rest of that file for the same pattern rather than assuming it's a one-off.
