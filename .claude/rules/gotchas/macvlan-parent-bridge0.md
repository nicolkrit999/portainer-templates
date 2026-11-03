# Gotcha: macvlan `parent` must be `bridge0`, not `eth0`

Nicol-NAS's UGOS Control Panel has "Virtual Network Bridging" enabled (Network
settings), turned on 2026-08-21 to support Docker macvlan networking. This
creates a `bridge0` interface that takes over the physical NIC's L2 identity:
`bridge0` and `eth0` share the same MAC address, and `eth0` is enslaved
underneath `bridge0`. The NAS's real LAN IP now lives on `bridge0` (shown in
the NAS UI as `VBR-LAN1`).

**Consequence:** any Docker macvlan network's `driver_opts.parent` (or a
`LAN_INTERFACE` env var feeding it) must be `bridge0`, not `eth0`. The kernel
refuses macvlan attachment directly on a NIC that's already enslaved to a
bridge.

**Confirmed failure:** `traefik-private-forwarder` first tried
`parent: eth0` and failed to deploy with `failed to create the macvlan port:
device or resource busy`. Switching `LAN_INTERFACE` to `bridge0` in that
stack's env resolved it.

**Where `LAN_INTERFACE` is set:** `traefik-private-forwarder` (it creates the
one macvlan network, `traefik-private-forwarder_traefik_forwarder_net`) and
`macvlan-host-shim`; both `.env.example` files say `bridge0`. Every other
macvlan user (`adguard`, `traefik-public`) joins that existing network as an
`external` network and defines no `parent` of its own. Docker allows only one
macvlan per parent/subnet, so never define a second one.

**How to apply:** before deploying or debugging any macvlan-networked
service on this NAS, check `LAN_INTERFACE`/`parent` is `bridge0`. If a
future `ip -br link show` ever shows a different bridge interface name,
re-verify rather than assuming `bridge0` still applies.
