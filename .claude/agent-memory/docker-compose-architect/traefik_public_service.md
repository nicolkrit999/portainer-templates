---
name: traefik-public-service
description: traefik-public design choices and Traefik 3.7 / Docker facts verified while building it (egress guard, holder pattern, header handling); the README is authoritative for routers, networks, variables, numbers
metadata:
  type: project
---

`traefik-public/README.md` is authoritative for the router list, networks, subnets, variables, timeouts, rate limits and the deploy procedure. This file keeps only the reasoning and verified facts that are not there. To make an app public, follow the README ("Adding a public service": router in the init heredoc, its OWN `internal: true` `public-<app>` network with an explicit /28 from the registry, `gateway` + `ip_range`, DNS-only CNAME to `wg.${DOMAIN}`); never use the private Traefik for it.

**Wording rule (public repo):** do not advertise missing controls in compose comments or the README ("no rate limiting"); say "planned hardening". Keep compose comments to non-obvious constraints; future-work notes live in the README.

## Deliberate design choices
- **Config generation:** init container + quoted heredoc (`<< 'EOF'`) inside a double-quoted YAML string with `\n` (the repo has no `configs:` usage). Compose interpolates `${VAR}` before the shell sees it, and the quoted heredoc protects the backticks in `Host(...)`. Written to `.dynamic.yml.tmp`, then `mv` into `dynamic/` (the watched dir never sees a partial file).
- **Init hardening:** digest-pinned alpine, `read_only`, `no-new-privileges`, `cap_drop ALL` + CHOWN/FOWNER/DAC_OVERRIDE, `network_mode: none`. DAC_OVERRIDE is genuinely required (root cannot mkdir in a directory owned by another uid; verified with a control run).
- **Proxy:** non-root `65532:65532` (literal on purpose), zero capabilities (CapEff all zero verified). Port 443 binds through `net.ipv4.ip_unprivileged_port_start=0` on the holder; `NET_BIND_SERVICE` was shown to be unnecessary.
- **`pids_limit` and `oom_score_adj: 500`** have no repo precedent; the proxy is deliberately sacrificial (opposite of adguard's -800).
- **Required variables** use `${VAR:?set VAR}` (DOMAIN, every `*_SUBDOMAIN`, `TRAEFIK_PUBLIC_IP`, `ACME_EMAIL`, `CF_DNS_API_TOKEN_PUBLIC`, `VOLUME_CONFIG`; `TZ` stays plain), so `docker compose config -q` needs a full env file and a missing variable fails the deploy BEFORE touching running containers (also true for a missing external network).
- **Ping entrypoint on `127.0.0.1:8082`** because macvlan exposes every listening port on the LAN IP. `traefik healthcheck` needs both `--ping.entryPoint=ping` and `--entryPoints.ping.address=...` on the healthcheck command itself (the CLI rebuilds static config from its own flags).
- The access-log path includes Immich share keys (`/share/<key>`); only the query string is dropped.

## Egress guard: holder design "B'"
`traefik-public-net` (holder) owns networks, `ipv4_address`, dns and sysctls and applies the iptables guard itself at every start; the proxy joins with `network_mode: "service:traefik-public-net"` and `depends_on: traefik-public-net: service_healthy`. Because the proxy has `network_mode: service:`, it cannot declare `networks:`: every new `public-<app>` network is attached to the HOLDER, and adding one recreates holder AND proxy on `up -d`.
- **Why not the alternatives (measured on a laptop, nft backend):** a plain sidecar leaves the guard in a dead netns after a proxy restart (proxy fully open); a pause holder + one-shot rules container is perfect at `compose up` but never re-runs after a host/holder restart (`restart: no`). B' puts the rules in place 0.12-0.21 s after the holder starts. Restarting the proxy alone keeps netns and rules; restarting the holder alone leaves the proxy with only `lo` yet "healthy" (loopback ping), so restart the proxy afterwards. Starting the proxy while the holder is down is refused by Docker.
- **Image:** `registry.k8s.io/build-image/distroless-iptables` (maintained; not the abandoned debian-iptables). It has no sleep/ip/awk/grep/head: the default interface is read from `/proc/net/route` in dash and the final block is `read _` with `stdin_open: true`.
- **Caps/backend:** nft needs only `NET_ADMIN` (root uid required). Backend = the one whose `-t nat` save contains `DOCKER_OUTPUT` (what dockerd used in that netns), else the first that works. NAS userland/kernel nft-vs-legacy is UNVERIFIED (the laptop kernel has no legacy filter table).
- **IPv6:** Docker disables IPv6 on IPv4-only network interfaces, so no sysctl; the guard refuses to start if the guarded interface has any IPv6 address (`/proc/net/if_inet6`).
- `docker compose config` prints `$$`; the container sees a single `$`.

## Traefik 3.7 facts (docs + local `traefik:v3.7.17`)
- A router-level `tls` section REPLACES the entrypoint's TLS settings, so every router sets `certResolver` explicitly.
- 3.7.12+ warns per entrypoint unless `aliasHeadersStrategy` is set; `--global.aliasHeadersStrategy=delete` strips underscore/dot headers and keeps dash ones.
- `accesslog.fields.queryparameters.defaultmode=drop` drops the query from `RequestPath`; header default is `drop`; `User-Agent=keep` works.
- Without `trustedIPs` Traefik OVERWRITES client `X-Forwarded-For` (several lines become one value, the peer), SETS `X-Real-Ip` to the peer, overwrites `X-Forwarded-Proto/Host/Port/Server`, drops `X-Forwarded-Prefix/Uri`, and passes `CF-Connecting-IP`, `True-Client-IP`, `X-Client-IP`, `Forwarded`, `Remote-User`, `X-Forwarded-User` through. Hence `public-strip-client-headers` (empty `customRequestHeaders` values delete) runs first on every router, and `X-Real-IP` must NOT be in its list (the middleware runs after Traefik set the genuine value).
- lego's Cloudflare token needs Zone:Read + DNS:Edit (single zone). Its power is every record in the zone; do not advise client-IP filtering of the token (the WAN IPv4 is dynamic, rotation would silently break renewal).
- Live plain env values (e.g. `*_SUBDOMAIN`) are readable with `StackInspect` and a narrow `select` such as `Env[?contains(name,'SUBDOMAIN')]`; never an unprojected call, and never print secrets.

## Pocket-ID
Pocket-ID v1.16.0: `ALLOW_USER_SIGNUPS` alone is IGNORED (tested with the exact image; it needs `UI_CONFIG_DISABLED=true`, which moves ALL settings to env/defaults, so never add that casually). The admin-UI "User signups" setting is the real control; check the live value via `GET /api/application-configuration` (`allowUserSignups` must be `disabled` before its public record goes live).

## Test-environment traps
- A laptop container inherits the host's DNS search domains; with a public wildcard record an unresolvable backend name dials Cloudflare IPs and hangs ~30 s (504). NAS containers have no search line (checked read-only via `GET /containers/<n>/archive?path=/etc/resolv.conf`), so absent backends give a fast 502. `dns_search: ["."]` fixes it where needed (tested, not applied).
- Local full-stack recipe: stand-in bridge named like the macvlan network (`--subnet 10.99.0.0/24`), overlay with `ports: 127.0.0.1:18443:443` on the HOLDER, `logging: !override json-file` (journald rejects `max-file`), `command: !override` with an unreachable `caServer`, a self-signed wildcard cert dropped into the dynamic dir as root, whoami stand-ins named like the real containers, `curl --resolve`. `yq` here is the python one.
- In a worktree-isolated session the hook-rewritten `git` can be refused; compound commands (`cd && ...`, loops, globs, strings containing "git") too: use one plain command per call.

## Unverified at write time (2026-11-03; re-check before relying on them)
Static IP outside the network `ip_range` on the NAS daemon, forwarded-header stripping from untrusted clients in production (tested locally only), and which host-side addresses the proxy can reach on the macvlan segment (the `macvlan-host-shim` IP is a host-namespace address on the same segment). Real client IPs through the UniFi forward and real ACME issuance were confirmed later (README, 2026-11-03).
