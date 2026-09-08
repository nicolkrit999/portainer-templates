# tailscale-adguard

Gives **[AdGuard Home](../adguard/)** its own Tailscale identity, so a device connected to Tailscale with an active exit node still resolves DNS through AdGuard instead of bypassing it.

## The problem

A device connected to Tailscale with an active exit node (tested with Mullvad's official Tailscale integration) has its DNS resolution overridden system-wide by Tailscale's own DNS config, bypassing AdGuard entirely - even though the device is still physically on the home LAN and would normally resolve through AdGuard via DHCP. This happens because Tailscale's client claims the OS's global default-route DNS domain (`~.`) whenever it's connected, regardless of exit-node status, and routes to whatever nameserver *is* registered for the tailnet - which, without the fix below, is nothing AdGuard-related.

## The fix

Give AdGuard its own Tailscale identity, and register that identity as the tailnet's DNS nameserver in the Tailscale admin console. This is a two-container stack:

- **`tailscale-adguard`** - a dedicated Tailscale node (ordinary, non-host networking, since `tailscale0` is a TUN device and can't be macvlan'd - third independent Tailscale identity in this repo, after `../tailscale/` and `../tailscale-admin_traefik-tailnet-forwarder/`).
- **`dns-relay`** - a `socat` relay that forwards DNS traffic arriving on that node's tailnet IP to the real `adguard` container over the `traefik-proxy` Docker network (both containers share that network, so no macvlan-crossing is involved in this path at all - unlike the `macvlan-host-shim` case).

## Required manual steps (Tailscale admin console, not part of this repo)

1. Deploy this stack, note its assigned Tailscale IP (`tailscale status` or the admin console's Machines list).
2. **DNS tab → Nameservers → Add nameserver** → paste that IP → enable **"Override local DNS"**.
3. **Machines → find the new node → "Disable key expiry"** - without this, the node silently drops off the tailnet after the tailnet's key-expiry window (commonly 90-180 days) and the whole fix quietly stops working with no obvious symptom.

AdGuard's own side of this (an `entrypoint:` patch so it actually accepts connections from this relay) is documented in `../adguard/README.md`.

## Incident: a socat process leak took down the whole household's internet

Found after the fix above was already live: the household's internet started failing entirely a few minutes after connecting Tailscale, every time, only recoverable by disconnecting Tailscale - not a DNS-specific symptom, `ping` itself stopped working.

**Root cause**: `socat`'s `fork` mode never terminates a forked child that handled a UDP query, since UDP has no "connection closed" signal the way TCP does - each child just sits there indefinitely waiting for more traffic from that same peer. Under real sustained household DNS traffic this grew to **2000+ leaked processes within about an hour**, eventually exhausting the relay container and causing new connections (TCP included) to get refused.

**Fix**: added `-T5` (a 5-second inactivity timeout) to every `socat` invocation in this relay and the structurally-identical `macvlan-host-shim` relay (which carries far less traffic so hadn't hit the failure point yet, but had the same latent bug). Verified against the real `adguard` target over the real network path before deploying, using a throwaway test container: a burst of queries left 13 processes alive immediately, down to 3 (just the listener) seven seconds later. 5 seconds is comfortably longer than any real single DNS exchange takes, so this never disrupts a legitimate in-flight query.

**If you're writing a `socat ...,fork` UDP relay of your own**: always pair it with `-T<seconds>`. There is no default timeout, and the leak is invisible in normal testing - it only shows up after sustained real traffic, by which point it's already taken the service down.

## 2026-09-08 outage and planned fix

This relay (`dns-relay`, the `socat` UDP/TCP forwarder above) is the one
that actually caused two confirmed household-wide internet outages - see
**[`../adguard/INCIDENT-2026-09-08-dns-relay-outage.md`](../adguard/INCIDENT-2026-09-08-dns-relay-outage.md)**
for the full root cause and the verified fix plan (replacing `socat` with
`dnsdist`, staged via a canary before cutover). The `dns-relay-canary`
service is deployed and confirmed healthy on `:5300` as of this write - the
live `dns-relay` (`socat`, `:53`) is still what actually serves traffic
until burst-testing is done and the cutover commit lands.

## A visibility limitation worth knowing

Every device using this Tailscale-relay path shows up in AdGuard's query log as the **same single client identity** (the relay container's own internal IP), not the real end-user device's IP - `socat`'s plain TCP/UDP relay doesn't preserve or forward the original source address. Per-client rules/stats in AdGuard won't distinguish between devices using this path.
