# tailscale-adguard

Gives **[AdGuard Home](../adguard/)** its own Tailscale identity, so a device connected to Tailscale with an active exit node still resolves DNS through AdGuard instead of bypassing it.

## The problem

A device connected to Tailscale with an active exit node (tested with Mullvad's official Tailscale integration) has its DNS resolution overridden system-wide by Tailscale's own DNS config, bypassing AdGuard entirely - even though the device is still physically on the home LAN and would normally resolve through AdGuard via DHCP. This happens because Tailscale's client claims the OS's global default-route DNS domain (`~.`) whenever it's connected, regardless of exit-node status, and routes to whatever nameserver *is* registered for the tailnet - which, without the fix below, is nothing AdGuard-related.

## The fix

Give AdGuard its own Tailscale identity, and register that identity as the tailnet's DNS nameserver in the Tailscale admin console. This stack has three services:

- **`tailscale-adguard`** - a dedicated Tailscale node (ordinary, non-host networking, since `tailscale0` is a TUN device and can't be macvlan'd). One of four independent Tailscale identities in this repo (see `../tailscale/README.md`).
- **`dnsdist-config-init`** - a one-shot container that regenerates `dnsdist.yml` and `dnsdist-client.conf` under `${VOLUME_CONFIG}/tailscale-adguard/` on every deploy (`dnsdist` YAML has no `${VAR}` interpolation, and the files contain the console key).
- **`dns-relay`** - a `dnsdist` relay (`powerdns/dnsdist-20`) that forwards DNS traffic arriving on that node's tailnet IP to the real `adguard` container over the `traefik-proxy` Docker network (both containers share that network, so no macvlan-crossing is involved in this path at all - unlike the `macvlan-host-shim` case). It joins `tailscale-adguard`'s network namespace (`network_mode: service:`) and has no package cache on purpose, so AdGuard's own query log and blocklist changes stay authoritative.

## Required manual steps (Tailscale admin console, not part of this repo)

1. Deploy this stack, note its assigned Tailscale IP (`tailscale status` or the admin console's Machines list).
2. **DNS tab → Nameservers → Add nameserver** → paste that IP → enable **"Override local DNS"**.
3. **Machines → find the new node → "Disable key expiry"** - without this, the node silently drops off the tailnet after the tailnet's key-expiry window (commonly 90-180 days) and the whole fix quietly stops working with no obvious symptom.

AdGuard's own side of this (an `entrypoint:` patch so it actually accepts connections from this relay) is documented in `../adguard/README.md`.

## History: why the relay is `dnsdist`, not `socat`

The relay was a `socat ...,fork` forwarder until 2026-09-08. It caused two confirmed household-wide internet outages: in `fork` mode `socat` never terminates a child that handled a UDP query (UDP has no "connection closed" signal), so under sustained household DNS traffic leaked processes accumulated (2000+ within about an hour in the first incident) until new connections, TCP included, were refused. A `-T5` inactivity timeout was added as a stop-gap, then `dnsdist` (event-driven, bounded concurrency) replaced `socat` on `:53` after a `:5300` canary survived 100x+ the outage-causing query rate with 0/500 failures. The `dns-relay-canary` service is gone. Full root cause, healthcheck pitfalls (the `dnsdist 2.0.9` `-k` flag is broken, the CLI exits 0 on auth failure) and burst-test data: **[`../adguard/INCIDENT-2026-09-08-dns-relay-outage.md`](../adguard/INCIDENT-2026-09-08-dns-relay-outage.md)**.

**If you write a `socat ...,fork` UDP relay anywhere**: always pair it with `-T<seconds>`; there is no default timeout and the leak only shows up after sustained real traffic.

## A visibility limitation worth knowing

Every device using this Tailscale-relay path shows up in AdGuard's query log as the **same single client identity** (the relay container's own internal IP), not the real end-user device's IP - the `dnsdist` relay is a plain forwarder (no EDNS client subnet, no PROXY protocol in `dnsdist.yml`), so the original source address is not passed on. Per-client rules/stats in AdGuard won't distinguish between devices using this path.
