---
description: How the core/setup infrastructure stacks (Traefik, both forwarders, both Tailscale nodes, both dnsmasq instances, Cloudflare Tunnel) fit together. Read this fully before modifying any of these specific stacks - they are not ordinary application services.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Core infrastructure topology

## Two different kinds of edit to these files - only one needs extra caution

**Routine, well-defined per-service list additions are expected, ordinary
maintenance of these files, not what the caution below is about.** Adding
one line to `dnsmasq`/`dnsmasq-tailnet`'s existing per-hostname override
list for a new service (see `adding-compose-services`), or adding a
hostname to the `sans` list on an existing SAN-bundle anchor router (see
`.claude/rules/san-cert-groups.md`) - even when that anchor happens to live
in a core stack's directory, which it normally doesn't - are exactly the
kind of change these files are designed to keep accepting. Do these
routinely, without extra ceremony, as part of the normal service-adding
workflow.

**What genuinely needs the caution below**: anything touching a core
stack's own structure - `network_mode`, image, core `command`/CLI flags,
entrypoint definitions, port publishing, capability/security settings, or
anything that isn't a simple additive entry to an established per-service
list. That class of change is what caused real repo-wide outages before.

## Rule: never modify a core/setup compose's structure without reading this file first

The stacks listed below are **not application services** - they are the
shared plumbing every other service in this repo depends on. A mistake in
one of these has repo-wide blast radius (confirmed by real incidents: a
config change here has caused a full outage of every Traefik-routed
service at least twice). Before editing `traefik/`, `traefik-private-forwarder/`,
`traefik-tailnet-forwarder/`, `tailscale/`, `tailscale-admin/`, `dnsmasq/`,
`dnsmasq-tailnet/`, or `cloudflared/`, read this file completely and
understand which OTHER stacks the change could affect - these seven are
tightly coupled, and a change that looks local to one file often isn't.

Ordinary application services (everything else in this repo) do not need
this level of caution - this file is specifically about the shared
infrastructure layer.

## What each stack's job is

**`traefik`** - the only stack that owns HTTP(S) routing, TLS certificates,
and per-service access rules (Cloudflare tier, family/guest/friends/private
tier routers, the tailnet-admin ipallowlist middleware). Everything else in
this list exists purely to get the right traffic to Traefik's front door
with the right source IP intact - none of the other stacks change Traefik's
actual routing/TLS logic. Listens on host-published ports 80 (redirect
only), family/guest/private/friends tiers, plus internal-only entrypoints
(cloudflared-facing, dashboard-API/ping, tailnet-admin) never published to
any host port.

**`tailscale`** (the primary/original node, `network_mode: host`) - puts
this NAS on the household's tailnet, advertises the LAN subnet route so
other tailnet devices can reach LAN-only things through it. Runs
`network_mode: host` because Tailscale needs direct control of a TUN
device and host-level routing - this is also exactly why nothing else can
bind a host-published port directly on this node's tailnet IP: host mode
puts `tailscale0` in the same network namespace as every other
host-published port on this machine, including Traefik's own wildcard
bind for the family entrypoint.

**`dnsmasq`** - LAN-facing DNS. Answers `*.${DOMAIN}` queries from LAN/
guest/friends devices with the right IP for each tier (family → NAS LAN
IP, private → the private forwarder's dedicated LAN IP) - a per-hostname
split, not a universal answer.

**`dnsmasq-tailnet`** - the Tailscale-facing sibling of the above. Answers
`*.${DOMAIN}` queries from Tailscale-connected devices. Mostly one
universal answer (the primary node's tailnet IP) for the whole domain,
EXCEPT admin-gated hostnames, which get a more-specific override pointing
at the `tailscale-admin` node's IP instead (dnsmasq resolves the
most-specific match, so this coexists safely with the wildcard rule).

**`traefik-private-forwarder`** - a narrow TCP-passthrough sidecar (socat)
that lets the private tier be reached at a clean `hostname:443` URL from
the LAN, without giving Traefik's own container a second, conflicting IP
bind. Solves this via **macvlan**: it gets its own dedicated LAN IP,
genuinely separate L2 identity from the NAS's own IP, so its 443 bind
never collides with Traefik's own wildcard bind.

**`tailscale-admin`** - a SECOND, independent Tailscale node/identity,
deliberately not the same node as `tailscale` above, and deliberately NOT
`network_mode: host`. Uses ordinary Docker networking (`cap_add: [NET_ADMIN,
SYS_MODULE]` + a `/dev/net/tun` device) so it gets its own real, isolated
network namespace - genuinely separate from the host's, unlike
`network_mode: host` which only looks separate but actually shares the
host's namespace with everything else published there. Exists purely so
`traefik-tailnet-forwarder` has somewhere to bind port 443/80 that isn't
the same namespace as Traefik's own listener. Does not advertise any LAN
subnet route - it's not a gateway, just a reachable node.

**`traefik-tailnet-forwarder`** - the tailnet-facing sibling of
`traefik-private-forwarder`, same job (clean, no-port URL for admin-gated
traffic) but a different mechanism because Tailscale's interface is a TUN
device (macvlan can't attach to it): it joins `tailscale-admin`'s network
namespace directly (`network_mode: container:tailscale-admin`, NOT
Compose's `service:` form - that only resolves within one compose
project, and these are separate stacks) and binds port 443/80 there. It
forwards into Traefik's own container using the PROXY protocol
(`send-proxy-v2`), which is what lets Traefik trust the real original
client IP even though the connection arrives via this forwarder -
Traefik's `proxyProtocol.trustedIPs` on the tailnet-admin entrypoint only
trusts PROXY headers from this forwarder's own static IP.

**Cloudflare Tunnel** (`cloudflared`) - the fully independent public-internet
access path. Untouched by anything above - none of the Tailscale/tailnet-admin
plumbing affects public/Cloudflare access at all.

## Known structural constraints (the reasons these 7 stacks look the way they do)

- **A wildcard-bound port and a specific-IP bind on the same port cannot
  coexist in the same network namespace.** This is why the private tier
  needed macvlan (a genuinely separate L2 identity) instead of a second
  bind on Traefik's own container, and why the tailnet-admin path needed
  a second Tailscale identity instead of just binding the forwarder
  directly to `tailscale0` via `network_mode: host` (that was tried and
  reverted after it caused a real outage - host mode shares the host's
  own namespace, it doesn't isolate anything).
- **Docker's userland-proxy silently rewrites the source IP of any
  connection arriving on a published port** to a Docker-internal gateway
  address before the container ever sees it. This is why the tailnet-admin
  ipallowlist middleware needed the PROXY-protocol forwarder path at all -
  a router relying on the raw TCP source IP for access control will see a
  rewritten, useless address for any traffic that transits a published
  port, not the real client IP.
- **Macvlan requires a real L2-capable parent interface.** It works for
  the LAN-facing private forwarder (parent: the NAS's own bridge
  interface) but cannot be used for anything Tailscale-facing, since
  `tailscale0` is a TUN device, not a physical/bridge NIC.

## How a request flows, per access path

- **LAN device → a private-tier-only service**: LAN `dnsmasq` → the private
  forwarder's own macvlan IP → `traefik-private-forwarder` (raw TCP
  passthrough) → Traefik's private entrypoint → the service.
- **Any device (LAN or Tailscale) → a family-tier service**: `dnsmasq`/
  `dnsmasq-tailnet` → the NAS's own IP (LAN or the primary Tailscale
  node's IP) → Traefik's family entrypoint (wildcard-bound, reached
  directly, no forwarder involved) → the service.
- **Admin device via Tailscale → an admin-gated hostname**: `dnsmasq-tailnet`
  (specific override) → `tailscale-admin`'s IP → `traefik-tailnet-forwarder`
  (bound inside `tailscale-admin`'s namespace) → PROXY-protocol-tagged
  connection → Traefik's tailnet-admin entrypoint (trusts the forwarder's
  static IP only) → the ipallowlist middleware (sees the real client IP
  via the PROXY header) → the service.
- **Public internet device → a Cloudflare-tunneled service**: Cloudflare
  Tunnel → `cloudflared` → Traefik's cloudflared entrypoint → the service.
  Nothing above touches this path.

## The one-sentence version

Every extra stack in this list exists to solve exactly one recurring
problem: something needs to bind a port at an address that isn't Traefik's
own wildcard bind, without colliding with it or requiring Traefik itself
to change - and the specific mechanism differs (macvlan vs a second
Tailscale identity) only because of what kind of network interface is
available on each path (a real L2 NIC for LAN, a TUN device for Tailscale).
