# traefik-public

Internet-facing Traefik for services that must be reachable from the public internet **without** the Cloudflare Tunnel (which caps uploads at 100 MB and restricts video). It is a separate instance from `../traefik/` on purpose: small, hardened and isolated from the rest of the estate.

## Address

Own macvlan LAN IP `${TRAEFIK_PUBLIC_IP}` (this instance: `192.168.1.94`), TCP **443** only - no port 80, no HTTP/3, no published host ports. The UniFi gateway forwards WAN TCP 443 to that IP. Clients connect directly, so Traefik logs the real client IP (confirmed 2026-11-03 with a request through the UniFi forward).

The container joins the existing macvlan network `traefik-private-forwarder_traefik_forwarder_net` (Docker allows only one per parent/subnet - see `.claude/rules/networking.md`). The NAS host itself cannot reach a macvlan IP on its own parent interface; test from another LAN device or from outside the LAN.

## What it does

- **File provider only.** No Docker socket, no Docker provider, no dashboard, no API. Routers, the service and the middleware are generated into `${VOLUME_CONFIG}/traefik-public/dynamic/dynamic.yml` by the `traefik-public-init` container on every deploy. The compose file is the only source of truth; never hand-edit `dynamic.yml`.
- **Routers** (single entrypoint `websecure`): `${PUBLIC_TEST_SUBDOMAIN}.${DOMAIN}` and `${IMMICH_SUBDOMAIN}.${DOMAIN}`, both to `http://immich_server:2283`. Any other hostname gets Traefik's default 404, and `sniStrict` rejects TLS handshakes for names without a certificate. Each router sets `certResolver` explicitly: a router-level `tls` section replaces the entrypoint's TLS settings entirely.
- **Certificates:** one per router hostname via ACME DNS-01 (resolver `cf_dns_public`, Cloudflare), EC256 keys, own `acme.json`, own token. No wildcard. These count against the same Let's Encrypt registered-domain quota (50 per week) as the core Traefik, so keep the hostname count small and keep `acme.json` backed up.
- **Headers and TLS:** `public-secure-headers` (HSTS 1 year + subdomains + preload, nosniff, frame deny, `same-origin` referrer policy). TLS 1.2 minimum, AEAD cipher suites only. Request headers with aliasing names (`X_Foo`, `X.Foo`) are stripped.
- **Timeouts:** read and write 86400s (24h), idle 180s. The read and write values are total per-request budgets, not inactivity timers; 24h covers about 100 GB at 10 Mbit/s in a single request. Slow-client limits come from the planned per-source controls below, not from these values. Resumable/chunked clients (Gokapi chunks, OpenCloud/TUS) remain the robust way to move very large files, because a dropped single-request upload restarts from zero.
- **Logs:** JSON access log on stdout. Headers are dropped except `User-Agent`; query strings are dropped. The request path is kept on purpose and contains Immich share keys (`/share/<key>`), so treat the logs as sensitive. Docker rotation keeps ~30 MB, so ship the logs elsewhere if they are needed for forensics.
- **Hardening:** non-root (UID 65532), read-only rootfs, `no-new-privileges`, all capabilities dropped (port 443 binds through the `net.ipv4.ip_unprivileged_port_start` sysctl), ping endpoint on loopback only, `public-apps` has no default route. Resource limits: `cpu_shares: 2048`, `cpus: 2.0`, `mem_limit: 512m`, `pids_limit: 512`, `nofile` 65536, `oom_score_adj: 500` (first to be sacrificed under memory pressure). The init container is digest-pinned, read-only, capability-limited and has no network.
- **Restart policy:** `unless-stopped`, so a manual stop sticks.

## Networks

| Network | Role |
|---|---|
| `traefik-private-forwarder_traefik_forwarder_net` (external, macvlan) | LAN IP `${TRAEFIK_PUBLIC_IP}`, default route, ACME egress |
| `public-apps` (created here, `internal: true`) | Immich's backend network. Immich attaches to it as `external: true`. No default route, no egress. |

Deliberately not on `cloudflare-web` or `traefik-proxy`, and there is no Cloudflare Tunnel handoff: the point of this stack is to bypass the tunnel.

## Environment variables

All are required except `TZ`: an unset or empty value fails the deploy instead of generating a broken rule such as ``Host(`foto.`)``.

| Variable | Purpose |
|---|---|
| `TZ` | Timezone. |
| `DOMAIN` | Base domain; routers match `<subdomain>.${DOMAIN}`. |
| `VOLUME_CONFIG` | Base path for `traefik-public/acme.json` and the generated `dynamic/` directory. |
| `ACME_EMAIL` | Let's Encrypt contact address. |
| `CF_DNS_API_TOKEN_PUBLIC` | Dedicated Cloudflare token `traefik-public-dns01` (Zone.DNS:Edit + Zone.Zone:Read, single zone). Never the core Traefik's token. |
| `TRAEFIK_PUBLIC_IP` | Free static LAN IP for the macvlan interface; the UniFi forward targets it. |
| `PUBLIC_TEST_SUBDOMAIN` | Hostname segment of the test router. |
| `IMMICH_SUBDOMAIN` | Hostname segment of the Immich router; same value as the immich stack. |

## Deploy order

1. Create the dedicated Cloudflare token and set the variables on a new Portainer stack `traefik-public` (this directory's compose file).
2. Deploy `traefik-public` **first**. It creates the `public-apps` network and requests the certificates (DNS-01 needs neither the port forward nor public DNS records). Wait for the container to be healthy and for the certificates to appear in the logs / `acme.json`.
3. Only afterwards deploy the updated `immich` stack: it declares `public-apps` as external and fails to start if that network does not exist yet. Do not push the immich edit before step 2 is done.
4. Test with `curl --resolve <test-host>:443:<TRAEFIK_PUBLIC_IP> https://<test-host>/api/server/ping` from a LAN device other than the NAS (the LAN resolvers wildcard-override `*.${DOMAIN}` to the NAS, so plain names do not reach this stack from inside the LAN).
5. In UniFi, forward WAN TCP 443 to `${TRAEFIK_PUBLIC_IP}:443`. Create the public DNS records as **DNS only** (not proxied), IPv4 only unless an IPv6 path is set up.

## Rollback

1. Remove the UniFi WAN 443 forward.
2. Flip the affected public DNS record(s) back to their previous (Cloudflare Tunnel) target.
3. Optionally stop the `traefik-public` stack. Stopping keeps the `public-apps` network, so Immich keeps starting.

To delete the stack entirely, first revert the `public-apps` network entries in `../immich/docker-compose.yml` and redeploy Immich; otherwise the network cannot be removed while Immich is attached and Immich cannot start without it.

## Operating rules

- **Never add `TRAEFIK_PUBLIC_IP` to `MACVLAN_ATTACHED_IPS` in `../macvlan-host-shim/`.** That list creates host-side routes to the listed macvlan IPs and would remove the host/macvlan isolation this stack relies on, giving a compromised proxy a path to the NAS host.
- **Remove the `public-test` router** (and `PUBLIC_TEST_SUBDOMAIN`) from the init command once the Immich cutover is verified.
- **One dedicated backend network per backend.** `public-apps` is Immich's. For each additional public service, create its own `internal: true` network, declare it external in that service's stack and add it to this stack's `traefik-public` networks. Never put several backends on one shared network.
- **Adding a public service:** add a router (and a service block if the backend differs) to the heredoc in `traefik-public-init`'s command, attach the backend as above, and create the DNS-only record. Each new hostname requests its own certificate.

## Planned hardening

Before widening exposure beyond the first service:

- Per-source connection cap (CrowdSec or an nftables `ct count` rule) and a country allow-list on the gateway; rate limiting and forward-auth once real client IPs are confirmed in the access log, since they can break Immich bulk uploads and the mobile apps.
- Watch the UniFi gateway's conntrack table under load.
- Alert on certificate expiry (renewal failures are otherwise silent until a certificate lapses).
- **Move the container into a DMZ network on the NAS's second 2.5G port before widening the forward beyond a test source IP.** Probed from inside the container (2026-11-03): the `macvlan-host-shim` (`.95`) and the NAS host (`.98`) answer on none of the tested ports, but the AdGuard macvlan IP answers on :53 and :80, the private-tier forwarder on :443 and the gateway on :22 and :443. Macvlan siblings talk inside the NAS, so the UniFi firewall never sees that traffic and cannot block it. A DMZ network puts the traffic through the gateway, where a zone rule can.

Before real services move over, narrow the DNS-01 credential. The Cloudflare token can edit every record in the zone. Option: delegate `_acme-challenge.<host>` by CNAME to a dedicated acme-dns zone so this host holds no Cloudflare token at all. TLS-ALPN-01 and HTTP-01 are not alternatives while a country allow-list on the gateway blocks Let's Encrypt's validators.
