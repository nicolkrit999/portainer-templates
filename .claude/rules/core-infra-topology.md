---
description: How the core/setup infrastructure stacks (Traefik, traefik-public, both forwarders, both Tailscale nodes, both dnsmasq instances) fit together. Read this fully before modifying any of these specific stacks - they are not ordinary application services.
paths: ["**/docker-compose.yml", "**/docker-compose.yaml"]
---

# Core infrastructure topology

Current model (rewritten 2026-11-03, after the Cloudflare Tunnel, the
family/guest/friends tiers and the SAN-bundle certificate groups were
retired). Exactly three access paths exist: **LAN** (owner at home →
`dnsmasq` → `traefik-private-forwarder` → Traefik entrypoint 3),
**tailnet** (owner away → `dnsmasq-tailnet` → the tailnet-admin gateway →
Traefik entrypoint 7) and **public** (strangers, a short hostname list →
UniFi WAN TCP 443 forward → `traefik-public`, never the core Traefik).

## Two different kinds of edit to these files - only one needs extra caution

**Routine, well-defined additions are ordinary maintenance, not what the
caution below is about.** A new service needs **no** DNS step (both
dnsmasq instances are wildcard-only) and **no** certificate step (one
wildcard certificate, see the `traefik` entry below). Making a service
public is an additive router/service/network in `traefik-public/` following
its own `README.md`, not a structural change to the core Traefik.

**What genuinely needs the caution below**: anything touching a core
stack's own structure - `network_mode`, image, core `command`/CLI flags,
entrypoint definitions, port publishing, capability/security settings, or
the DNS wildcard/override lines. That class of change is what caused real
repo-wide outages before.

## Rule: never modify a core/setup compose's structure without reading this file first

The stacks listed below are **not application services** - they are the
shared plumbing every other service in this repo depends on. A mistake in
one of these has repo-wide blast radius (confirmed by real incidents: a
config change here has caused a full outage of every Traefik-routed
service at least twice, and a THIRD incident, 2026-09-08, was caused by
`tailscale-admin` and `traefik-tailnet-forwarder` being separate stacks in
the first place - see that pair's note below). Before editing `traefik/`,
`traefik-public/`, `traefik-private-forwarder/`,
`tailscale-admin_traefik-tailnet-forwarder/`, `tailscale/`, `dnsmasq/`, or
`dnsmasq-tailnet/`, read this file completely and understand which OTHER
stacks the change could affect - these are tightly coupled, and a change
that looks local to one file often isn't.

Ordinary application services (everything else in this repo) do not need
this level of caution - this file is specifically about the shared
infrastructure layer.

## What each stack's job is

**`traefik`** - the only stack that owns HTTP(S) routing, TLS certificates,
and per-service access rules for the private and tailnet paths (the
tailnet-admin ipallowlist middleware lives here). Everything else in this
list exists purely to get the right traffic to a Traefik front door with
the right source IP intact. Entrypoints (numbering kept on purpose after
1, 2, 4 and 5 were retired): `3` private (`asDefault`, port 8444, the only
one besides 80 that is host-published, though the forwarder reaches it over
`traefik-proxy`, not via the host port), `6`
internal ping/dashboard-API (8080, no host port), `7` tailnet-admin (8446,
no host port, PROXY protocol, reached only via the tailnet forwarder);
plus plain `:80` as a redirect to https only. Variables:
`TRAEFIK_ENTRYPOINT_3/6/7`, `TRAEFIK_PORT_3/6/7`. **One wildcard
certificate** (`${DOMAIN}` + `*.${DOMAIN}`, DNS-01 via Cloudflare DNS, token
`CF_DNS_API_TOKEN`) is requested by the single router `traefik-dashboard`,
the only router allowed to carry `tls.certresolver`/`tls.domains`; every
other router has a bare `tls: "true"` and is served that certificate by SNI
(a second router carrying its own certresolver would race and request its
own certificate). The same two certresolver/domains settings sit on
entrypoints 3 and 7 as defaults.

**`traefik-public`** - a second, separate Traefik instance for the few
hostnames strangers may reach. Own macvlan LAN IP (joined to the same
macvlan network as the private forwarder), TCP 443 only, no host ports,
file provider only (no Docker socket, no dashboard). UniFi forwards WAN
TCP 443 to it, with UniFi Region Blocking (Incoming, Allow CH+IT) in
front. Per-app internal networks `public-<app>`, an egress guard,
per-hostname DNS-01 certificates (resolver `cf_dns_public`, token
`CF_DNS_API_TOKEN_PUBLIC`), per-app path rules and rate limits. Public DNS
for each hostname is a DNS-only (grey cloud) CNAME to the DDNS name that
tracks the WAN address. The router list, the exact variables and the
procedure for making an app public live in `traefik-public/README.md`;
never expose an app publicly through the core Traefik.

**`tailscale`** (the primary/original node, `network_mode: host`) - puts
this NAS on the household's tailnet, advertises the LAN subnet route so
other tailnet devices can reach LAN-only things through it. Runs
`network_mode: host` because Tailscale needs direct control of a TUN
device and host-level routing - this is also exactly why nothing else can
bind a host-published port directly on this node's tailnet IP: host mode
puts `tailscale0` in the same network namespace as every other
host-published port on this machine, including Traefik's own wildcard
binds (80 and the private entrypoint).

**`dnsmasq`** - LAN-facing DNS, wildcard only: every `*.${DNS_WILDCARD_DOMAIN}`
name answers `${DNS_PRIVATE_IP}` (the private forwarder's macvlan LAN IP).
The single exception is `gitea-ssh`, which answers `${DNS_TARGET_IP}` (the
NAS's own LAN IP) because Git over SSH is not HTTP and is published on the
NAS directly (host port 2222). No per-service overrides exist any more.

**`dnsmasq-tailnet`** - the Tailscale-facing sibling. Wildcard only: every
`*.${DNS_WILDCARD_DOMAIN}` name answers `${TAILSCALE_ADMIN_IP}` (the
tailnet-admin gateway's tailnet IP), and `gitea-ssh` answers `${TAILNET_IP}`
(the primary node, i.e. the NAS). A hostname without a `-tailnet` router
therefore answers Traefik's own 404 on this path - every service compose
carries both routers (`.claude/rules/networking.md`).

**`traefik-private-forwarder`** - a narrow TCP-passthrough sidecar (socat)
that lets the private tier be reached at a clean `hostname:443` URL from
the LAN, without giving Traefik's own container a second, conflicting IP
bind. Solves this via **macvlan**: it gets its own dedicated LAN IP,
genuinely separate L2 identity from the NAS's own IP, so its 443 bind
never collides with Traefik's own wildcard bind. It creates the one live
macvlan network (`traefik-private-forwarder_traefik_forwarder_net`) that
`traefik-public` and anything else needing its own LAN IP join as
`external: true` (see `.claude/rules/networking.md`).

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

**RESOLVED 2026-09-08 (same day): a watcher sidecar was implemented as the
permanent fix**, not left as an open decision. `tailscale-admin-watcher`
was added to this same merged stack (see the compose file itself) - a
custom `command:` on the official `docker:27-cli` image (no custom build,
same off-the-shelf-image pattern as `haproxy-config-init` above), not
either of the two third-party images that were evaluated and rejected:
`buxxdev/containernetwork-autofix` (hard-requires Unraid plugin host paths
absent on this NAS) and `treyturner/whalewatcher` (no verifiable public
source repo - a supply-chain concern for an image needing read-write
docker.sock access). It pipes `docker events --filter event=start --filter
container=tailscale-admin` into an infinite `while read` loop, waits
`${WATCHER_RESTART_WAIT_TIME}` seconds after each restart it detects (lets
the new Tailscale identity establish its tailnet connection first), then
runs `docker compose -f /stack/docker-compose.yml -p
tailscale-admin_traefik-tailnet-forwarder up -d --force-recreate
traefik-tailnet-forwarder` against a read-only mount of this exact stack's
own compose file at its real Portainer-on-disk path
(`${VOLUME_CONFIG}/portainer/compose/${PORTAINER_STACK_ID}/tailscale-admin_traefik-tailnet-forwarder/docker-compose.yml`).
This closes the narrower trigger structurally - staleness can no longer
depend on remembering to touch both services' config in the same
commit/deploy.

The manual-fix and documented-discipline paths below remain useful as
fallbacks (e.g. if the watcher container itself is ever down), but are no
longer the primary mitigation:
1. **Documented discipline (fallback only):** any edit to `tailscale-admin`'s
   own block that also touches something in `traefik-tailnet-forwarder`'s
   block in the same commit/deploy still forces Compose to recreate both
   together - still true, just no longer load-bearing now that the watcher
   exists.
2. **Immediate manual fix if staleness is ever found regardless:** just
   restart/recreate `traefik-tailnet-forwarder` (its `network_mode:
   container:tailscale-admin` reference re-resolves fresh against whatever
   `tailscale-admin` container is currently running) - the same one-line
   fix that resolved the live 2026-09-08 incident before either the
   structural merge or the watcher existed.

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

## Known structural constraints (the reasons these stacks look the way they do)

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
  port, not the real client IP. (`traefik-public` avoids the problem the
  other way: it has its own macvlan IP and no published ports, so it sees
  the real client address directly.)
- **Macvlan requires a real L2-capable parent interface.** It works for
  the LAN-facing private forwarder and `traefik-public` (parent: the NAS's
  own bridge interface, `bridge0`, see `gotchas/macvlan-parent-bridge0.md`)
  but cannot be used for anything Tailscale-facing, since `tailscale0` is a
  TUN device, not a physical/bridge NIC.
- **The NAS host itself cannot reach a macvlan IP on its own parent
  interface.** Test the private forwarder and `traefik-public` from another
  LAN device (or, for public, from outside the LAN), not from the NAS.

## A stopped container looks identical to "no router for this entrypoint"

The core Traefik uses only the Docker provider (no file/static provider) -
every router/service is built from labels on a currently running container.
**When a container stops, Traefik's Docker provider detects this and
removes that router/service from its dynamic config entirely - it does not
keep the router around returning a 502 for a dead backend.** This means a
genuinely-stopped service and a hostname that never had a router on the
entrypoint being hit (e.g. a service missing its `-tailnet` router,
reached over the tailnet) both produce the exact same `404` (no router
matched) - they are not distinguishable by HTTP status code alone.
Confirmed 2026-08-23 while designing an access-control verification script
(see the household's memory `family-tier-dns-access-incident` - historical,
the family tier it describes no longer exists). To tell them apart, check
the container's actual running state directly (`docker_proxy`
`/containers/json`), not the HTTP response. (`traefik-public` uses the file
provider, so its routers do not disappear when a backend stops.)

**A second, distinct ambiguous-404 case, with an actual HTTP-only fix**:
a real router that matched and routed correctly can still have its
backend app return its own `404` at that path (e.g. an API-only service
with nothing served at `/`) - indistinguishable from "no router matched at
all" by status code alone, same problem as above but for a different
reason (nothing to do with the container being down). Found 2026-08-23
while a verification script hit false-positive failures on `budget-api`/
`budget-ical` (a known-benign case; those hostnames no longer exist).
**Fix that doesn't need `docker_proxy` access**: check for the
`Strict-Transport-Security` response header. Every real router on the core
Traefik has `hsts-headers@docker` in its `middlewares` list (see
`.claude/rules/networking.md`), so that header is only present when a
router's actual middleware chain ran - Traefik's own internal "no route
matched" fallback never runs any middleware, so it never has that header,
regardless of status code. Useful specifically for HTTP-only test scripts
that can't query the Docker API to check container state directly.

## How a request flows, per access path

- **LAN device (owner, at home) → any service**: `dnsmasq` (wildcard) →
  the private forwarder's own macvlan IP → `traefik-private-forwarder`
  (raw TCP passthrough) → Traefik's private entrypoint (3) → the service.
- **Tailscale device (owner, away) → any service**: `dnsmasq-tailnet`
  (wildcard) → `tailscale-admin`'s IP → `traefik-tailnet-forwarder`
  (bound inside `tailscale-admin`'s namespace) → PROXY-protocol-tagged
  connection → Traefik's tailnet-admin entrypoint (7; trusts the
  forwarder's static IP only) → the ipallowlist middleware (sees the real
  client IP via the PROXY header; owner devices only) → the service.
- **Public internet → one of the public hostnames**: public DNS
  (DNS-only CNAME to the DDNS name) → WAN TCP 443 → UniFi Region Blocking →
  UniFi forward → `traefik-public` (macvlan IP) → the per-app `public-<app>`
  network → the service. The core Traefik is not involved.
- **Git over SSH (private only)**: `gitea-ssh.<domain>` resolves to the NAS
  on the LAN (`dnsmasq`) and on the tailnet (`dnsmasq-tailnet`, the primary
  node's tailnet IP) → published host port 2222 on the NAS → Gitea. Bypasses
  Traefik entirely; never forwarded by the gateway. Client ssh config needs
  `Port 2222`.

## The one-sentence version

Every extra stack in this list exists to solve exactly one recurring
problem: something needs to bind a port at an address that isn't Traefik's
own wildcard bind, without colliding with it or requiring Traefik itself
to change - and the specific mechanism differs (macvlan vs a second
Tailscale identity) only because of what kind of network interface is
available on each path (a real L2 NIC for LAN, a TUN device for Tailscale).
