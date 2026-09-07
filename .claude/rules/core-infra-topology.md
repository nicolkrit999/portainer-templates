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
service at least twice, and a THIRD incident, 2026-09-08, was caused by
`tailscale-admin` and `traefik-tailnet-forwarder` being separate stacks in
the first place - see that pair's note below). Before editing `traefik/`,
`traefik-private-forwarder/`, `tailscale-admin_traefik-tailnet-forwarder/`,
`tailscale/`, `dnsmasq/`, `dnsmasq-tailnet/`, or `cloudflared/`, read this
file completely and understand which OTHER stacks the change could affect -
these six are tightly coupled, and a change that looks local to one file
often isn't.

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
`*.${DOMAIN}` queries from Tailscale-connected devices. One universal
wildcard answer (the primary node's tailnet IP) for the whole domain,
EXCEPT hostnames with a `tailnet-admin` Traefik router, which get a
more-specific override pointing at the `tailscale-admin` node's IP instead
(dnsmasq resolves the most-specific match, so this coexists safely with the
wildcard rule). **In practice this "except" list covers almost every
service, not a small special-case set** - since `adding-compose-services`
gives every new private-tier service a `tailnet-admin` router by default,
virtually every new service needs its hostname added to this override list
too, or it silently falls through to the wildcard and never reaches
Traefik's `tailnet-admin` entrypoint correctly (confirmed real bug,
2026-09-02 - see that skill's DNS step).

**`traefik-private-forwarder`** - a narrow TCP-passthrough sidecar (socat)
that lets the private tier be reached at a clean `hostname:443` URL from
the LAN, without giving Traefik's own container a second, conflicting IP
bind. Solves this via **macvlan**: it gets its own dedicated LAN IP,
genuinely separate L2 identity from the NAS's own IP, so its 443 bind
never collides with Traefik's own wildcard bind.

**`tailscale-admin` + `traefik-tailnet-forwarder`** - as of 2026-09-08 these
are TWO SERVICES IN ONE MERGED STACK
(`tailscale-admin_traefik-tailnet-forwarder/docker-compose.yml`), not two
separate stacks as they used to be. See that file's own top-of-file comment
for the full incident writeup; short version: `traefik-tailnet-forwarder`'s
`network_mode: container:tailscale-admin` is a hard runtime coupling
(Docker pins tailscale-admin's raw container ID at creation time), but
being two INDEPENDENT Portainer git stacks meant their separate 5-minute
auto-poll timers could recreate one without the other, leaving the
forwarder bound inside a stale, orphaned network namespace - real
tailnet-admin traffic then got an instant "Connection refused" while
everything looked locally "healthy". Merging into one stack, plus setting
this stack's Portainer `AutoUpdate.ForceUpdate` to `true`, fully closed
*that specific trigger* (a change touching both services' config in one
commit). It did **not** close the underlying gap completely - see the
dedicated section below, read it before making any future change to
either service.

### ⚠️ This pair's residual risk - not fully closed by the 2026-09-08 merge

**Verified via Portainer's own docs and Docker Compose's documented
behavior (2026-09-08), not assumed:**
- Portainer's `AutoUpdate.ForceUpdate` only means "redeploy on schedule
  even if the git commit hasn't changed" - it does NOT force recreation of
  a container whose own config is unchanged. ([Portainer docs](https://docs.portainer.io/faqs/troubleshooting/stacks-deployments-and-updates/how-do-automatic-updates-for-stacks-applications-work):
  "we do not force a redeployment if the image has not updated... if
  Docker determines the image hasn't changed for a container it will not
  redeploy that container.")
- Native Docker Compose has no mechanism to cascade-recreate a
  `network_mode: service:X`/`container:X` dependent when X itself gets
  recreated - a long-standing, documented Compose gap (third-party tools
  like "ContainerNetwork AutoFix" and "whalewatcher" exist specifically
  because vanilla Compose doesn't handle this).

**What this means in practice:** the merge prevents the *exact* trigger
that caused the 2026-09-08 incident (one commit changing both services'
config, previously split across two independently-timed stacks - now one
`docker compose up` invocation recreates both together, since both
actually changed). It does **not** prevent a *narrower* future trigger:
any change that touches `tailscale-admin`'s own config **without** also
touching something in `traefik-tailnet-forwarder`'s block in that same
commit/deploy - e.g. rotating `TS_AUTHKEY_ADMIN` alone, bumping
`tailscale-admin`'s image tag alone, or any Portainer-UI-only env edit to
just that service. In that case Compose will recreate only
`tailscale-admin`, and the forwarder will be left pointing at the old,
now-stale container ID - reproducing the identical bug.

**How to check if this has already happened** (suspect this whenever
tailnet-admin access is failing but `traefik` itself and its cert/router
config look fine): compare `tailscale-admin`'s current container start
time against how long ago `traefik-tailnet-forwarder` was last (re)created
- `docker_proxy` `GET /containers/tailscale-admin/json` and
`GET /containers/traefik-tailnet-forwarder/json`, both projected to
`State.StartedAt`. If `tailscale-admin`'s `StartedAt` is NEWER than the
forwarder's, the forwarder is stale. Confirm by checking the forwarder's
actual `HostConfig.NetworkMode` value (a raw `container:<id>` string) against
`tailscale-admin`'s CURRENT container `Id` - if they don't match, this is
happening right now, not just a suspicion.

**How to tackle it - two real options, not yet decided as of 2026-09-08:**
1. **Documented discipline (no new moving parts, relies on remembering):**
   any future edit to `tailscale-admin`'s own block must also touch
   something in `traefik-tailnet-forwarder`'s block in the same
   commit/deploy (even a harmless comment bump) so Compose sees a diff on
   both and recreates them together. Cheap, but the exact same category of
   human-discipline failure already caused this incident once.
2. **Add a small watcher sidecar** (e.g. a container-recreation-watcher
   image such as "whalewatcher" or "ContainerNetwork AutoFix") to this same
   merged stack, whose only job is to detect when `tailscale-admin` gets a
   new container ID and automatically force-recreate
   `traefik-tailnet-forwarder` in response. Still an off-the-shelf image
   (no custom build - consistent with this repo's "no build steps"
   convention), genuinely closes the gap automatically, at the cost of one
   more moving part in an already infra-dense area.
3. **Immediate manual fix if the check above confirms staleness right
   now:** just restart/recreate `traefik-tailnet-forwarder` (its
   `network_mode: container:tailscale-admin` reference re-resolves fresh
   against whatever `tailscale-admin` container is currently running at
   that moment) - this is the same one-line fix that resolved the live
   2026-09-08 incident before the structural merge was even in place.

`tailscale-admin` - a SECOND, independent Tailscale node/identity,
deliberately not the same node as `tailscale` above, and deliberately NOT
`network_mode: host`. Uses ordinary Docker networking (`cap_add: [NET_ADMIN,
SYS_MODULE]` + a `/dev/net/tun` device) so it gets its own real, isolated
network namespace - genuinely separate from the host's, unlike
`network_mode: host` which only looks separate but actually shares the
host's namespace with everything else published there. Exists purely so
`traefik-tailnet-forwarder` has somewhere to bind port 443/80 that isn't
the same namespace as Traefik's own listener. Does not advertise any LAN
subnet route - it's not a gateway, just a reachable node.

`traefik-tailnet-forwarder` - the tailnet-facing sibling of
`traefik-private-forwarder`, same job (clean, no-port URL for admin-gated
traffic) but a different mechanism because Tailscale's interface is a TUN
device (macvlan can't attach to it): it joins `tailscale-admin`'s network
namespace directly (`network_mode: container:tailscale-admin` - kept in its
literal raw-Docker form even post-merge, not switched to Compose's
`service:` sugar, since both resolve identically as long as
`tailscale-admin`'s `container_name` stays fixed) and binds port 443/80
there. It forwards into Traefik's own container using the PROXY protocol
(`send-proxy-v2`), which is what lets Traefik trust the real original
client IP even though the connection arrives via this forwarder -
Traefik's `proxyProtocol.trustedIPs` on the tailnet-admin entrypoint only
trusts PROXY headers from this forwarder's own static IP.

**Cloudflare Tunnel** (`cloudflared`) - the fully independent public-internet
access path. Untouched by anything above - none of the Tailscale/tailnet-admin
plumbing affects public/Cloudflare access at all.

## Known structural constraints (the reasons these 6 stacks look the way they do)

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

## A stopped container looks identical to "no router for this tier"

This repo's Traefik uses only the Docker provider (no file/static
provider) - every router/service is built from labels on a currently
running container. **When a container stops, Traefik's Docker provider
detects this and removes that router/service from its dynamic config
entirely - it does not keep the router around returning a 502 for a dead
backend.** This means a genuinely-stopped service and a wrong-tier request
(e.g. hitting a private-tier-only host's family port) both produce the
exact same `404` (no router matched) - they are not distinguishable by
HTTP status code alone. Confirmed 2026-08-23 while designing an
access-control verification script (see the household's memory
`family-tier-dns-access-incident` for the debugging session this came out
of). To tell them apart, check the container's actual running state
directly (`docker_proxy` `/containers/json`), not the HTTP response.

**A second, distinct ambiguous-404 case, with an actual HTTP-only fix**:
a real router that matched and routed correctly can still have its
backend app return its own `404` at that path (e.g. an API-only service
with nothing served at `/`) - indistinguishable from "no router matched at
all" by status code alone, same problem as above but for a different
reason (nothing to do with the container being down). Found 2026-08-23
while a verification script hit false-positive failures on `budget-api`/
`budget-ical` (a known-benign case, see `family-tier-dns-access-incident`).
**Fix that doesn't need `docker_proxy` access**: check for the
`Strict-Transport-Security` response header. Every real router in this
repo has `hsts-headers@docker` in its `middlewares` list (see
`.claude/rules/networking.md`), so that header is only present when a
router's actual middleware chain ran - Traefik's own internal "no route
matched" fallback never runs any middleware, so it never has that header,
regardless of status code. Useful specifically for HTTP-only test scripts
that can't query the Docker API to check container state directly.

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
