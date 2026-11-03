# traefik-public

Internet-facing Traefik for services that must be reachable from the public internet **without** the Cloudflare Tunnel (which caps uploads at 100 MB and restricts video). It is a separate instance from `../traefik/` on purpose: small, hardened and isolated from the rest of the estate.

## Address

Own macvlan LAN IP `${TRAEFIK_PUBLIC_IP}` (this instance: `192.168.1.94`), TCP **443** only - no port 80, no HTTP/3, no published host ports. The UniFi gateway forwards WAN TCP 443 to that IP. Clients connect directly, so Traefik logs the real client IP (confirmed 2026-11-03 with a request through the UniFi forward).

The container joins the existing macvlan network `traefik-private-forwarder_traefik_forwarder_net` (Docker allows only one per parent/subnet - see `.claude/rules/networking.md`). The NAS host itself cannot reach a macvlan IP on its own parent interface; test from another LAN device or from outside the LAN.

## What it does

- **File provider only.** No Docker socket, no Docker provider, no dashboard, no API. Routers, the service and the middleware are generated into `${VOLUME_CONFIG}/traefik-public/dynamic/dynamic.yml` by the `traefik-public-init` container on every deploy. The compose file is the only source of truth; never hand-edit `dynamic.yml`.
- **Routers** (single entrypoint `websecure`, hostnames are `<subdomain>.${DOMAIN}`):

  | Subdomain variable | Backend |
  |---|---|
  | `PUBLIC_TEST_SUBDOMAIN`, `IMMICH_SUBDOMAIN` | `http://immich_server:2283` |
  | `POCKET_ID_SUBDOMAIN` | `http://pocket-id:1411` |
  | `JELLYFIN_SUBDOMAIN` | `http://jellyfin:8096` |
  | `NAVIDROME_SUBDOMAIN` | `http://navidrome:4533` |
  | `GOKAPI_SUBDOMAIN` | `http://gokapi:53842` |
  | `GITEA_SUBDOMAIN` | `http://gitea:3000` |
  | `PRIVATEBIN_SUBDOMAIN` | `http://privatebin:8080` |

  Any other hostname gets Traefik's default 404, and `sniStrict` rejects TLS handshakes for names without a certificate. Each router sets `certResolver` explicitly: a router-level `tls` section replaces the entrypoint's TLS settings entirely.
- **Certificates:** one per router hostname via ACME DNS-01 (resolver `cf_dns_public`, Cloudflare), EC256 keys, own `acme.json`, own token. No wildcard. These count against the same Let's Encrypt registered-domain quota (50 per week) as the core Traefik, so keep the hostname count small and keep `acme.json` backed up.
- **Headers and TLS:** `public-secure-headers` (HSTS 1 year + subdomains + preload, nosniff, frame deny, `same-origin` referrer policy). TLS 1.2 minimum, AEAD cipher suites only. Request headers with aliasing names (`X_Foo`, `X.Foo`) are stripped.
- **Client-supplied identity headers:** every router lists `public-strip-client-headers` before `public-secure-headers`. It deletes (an empty `customRequestHeaders` value removes the header) the client-IP headers `CF-Connecting-IP`, `CF-Connecting-IPv6`, `True-Client-IP`, `X-Client-IP`, `X-Cluster-Client-IP` and `Forwarded`, and the proxy-authentication identity headers `Remote-User`, `Remote-Email`, `Remote-Name`, `Remote-Groups`, `X-Forwarded-User`, `X-Forwarded-Email`, `X-Webauth-User`, `X-Webauth-Email` and `X-Webauth-Fullname`. This path never sets any of them, so nothing legitimate is lost, and a backend with a trusted-proxy or header-authentication feature cannot be fed a forged value. `X-Forwarded-For`, `X-Real-Ip` and `X-Forwarded-Proto/Host/Port/Server` need no stripping: with no `forwardedHeaders.trustedIPs` configured, Traefik replaces them with values derived from the TCP peer (and drops `X-Forwarded-Prefix` and `X-Forwarded-Uri`), so `X-Real-IP` is deliberately not in the list (deleting it would remove the genuine value Traefik sets). Checked against `traefik:v3.7.17` with spoofed values for every header named here.
- **Timeouts:** read and write 86400s (24h), idle 180s. The read and write values are total per-request budgets, not inactivity timers; 24h covers about 100 GB at 10 Mbit/s in a single request. Slow-client limits come from the planned per-source controls below, not from these values. Resumable/chunked clients (Gokapi chunks, OpenCloud/TUS) remain the robust way to move very large files, because a dropped single-request upload restarts from zero.
- **Logs:** JSON access log on stdout. Headers are dropped except `User-Agent`; query strings are dropped. The request path is kept on purpose and contains Immich share keys (`/share/<key>`), so treat the logs as sensitive. Docker rotation keeps ~30 MB, so ship the logs elsewhere if they are needed for forensics.
- **Hardening:** non-root (UID 65532), read-only rootfs, `no-new-privileges`, all capabilities dropped (port 443 binds through the `net.ipv4.ip_unprivileged_port_start` sysctl on `traefik-public-net`), ping endpoint on loopback only, the backend networks have no default route, and an [egress guard](#egress-guard) in the proxy's network namespace blocks new connections from the macvlan interface into private address space. Resource limits: `cpu_shares: 2048`, `cpus: 2.0`, `mem_limit: 512m`, `pids_limit: 512`, `nofile` 65536, `oom_score_adj: 500` (first to be sacrificed under memory pressure). The init container is digest-pinned, read-only, capability-limited and has no network.
- **Restart policy:** `unless-stopped`, so a manual stop sticks.

## Networks

| Network (all attached to `traefik-public-net`) | Role |
|---|---|
| `traefik-private-forwarder_traefik_forwarder_net` (external, macvlan) | LAN IP `${TRAEFIK_PUBLIC_IP}`, default route, ACME egress |
| `public-apps` (created here, `internal: true`) | Immich's backend network. Immich attaches to it as `external: true`. No default route, no egress. |
| `public-pocket-id` (created here, `internal: true`, explicit subnet) | Pocket-ID's backend network. Pocket-ID attaches to it as `external: true`, next to its existing networks. No default route, no egress. |
| `public-jellyfin` (created here, `internal: true`, explicit subnet) | Jellyfin's backend network. Default subnet `172.16.78.0/28`. |
| `public-navidrome` (created here, `internal: true`, explicit subnet) | Navidrome's backend network. Default subnet `172.16.79.0/28`. |
| `public-gokapi` (created here, `internal: true`, explicit subnet) | Gokapi's backend network. Default subnet `172.16.80.0/28`. |
| `public-gitea` (created here, `internal: true`, explicit subnet) | Gitea's backend network. Default subnet `172.16.81.0/28`. |
| `public-privatebin` (created here, `internal: true`, explicit subnet) | PrivateBin's backend network. Default subnet `172.16.82.0/28`. |

Each backend's own stack declares its network as `external: true`. A `/28` holds only the proxy and its one backend. The proxy appears to the backend as an address inside that subnet, which is what the backend's trusted-proxy setting has to cover. On the five application networks the proxy has a fixed address, so a backend whose trusted-proxy field takes only host addresses (Jellyfin's Known Proxies) can name it; the others can use the `/28` itself:

| Network | Subnet | Gateway (Docker) | Proxy address |
|---|---|---|---|
| `public-jellyfin` | `172.16.78.0/28` | `172.16.78.1` | `172.16.78.2` |
| `public-navidrome` | `172.16.79.0/28` | `172.16.79.1` | `172.16.79.2` |
| `public-gokapi` | `172.16.80.0/28` | `172.16.80.1` | `172.16.80.2` |
| `public-gitea` | `172.16.81.0/28` | `172.16.81.1` | `172.16.81.2` |
| `public-privatebin` | `172.16.82.0/28` | `172.16.82.1` | `172.16.82.2` |

The backend gets the next free address (`.3` in practice) unless its own stack pins one. `public-apps` and `public-pocket-id` keep Docker-assigned proxy addresses.

Deliberately not on `cloudflare-web` or `traefik-proxy`, and there is no Cloudflare Tunnel handoff: the point of this stack is to bypass the tunnel.

The networks and the address are attached to `traefik-public-net`, not to `traefik-public` itself: the proxy joins that container's network namespace (`network_mode: service:traefik-public-net`), which is what lets the guard below stay out of the proxy's reach.

## Egress guard

A compromised proxy process must not be able to open new connections to other devices through its macvlan interface. The UniFi gateway cannot filter that: macvlan siblings on the NAS exchange traffic inside the kernel and it never reaches the gateway. So the filter lives in the proxy's own network namespace.

- **Who applies it:** `traefik-public-net` owns the namespace (networks, address, DNS, sysctls) and installs the rules at every start with `NET_ADMIN` and nothing else. `traefik-public` joins the namespace with no capabilities and a read-only filesystem, so it cannot change the rules, and it starts only after the holder is healthy.
- **What it drops:** new connections out of the macvlan interface to `192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`, `169.254.0.0/16` and `100.64.0.0/10`. The interface is the one holding the default route, found at start, not hard-coded. Untouched: replies to inbound connections (conntrack `ESTABLISHED,RELATED`), the public internet (ACME, DNS), loopback and the other interfaces (the internal backend networks).
- **Backend:** `iptables-nft` or `iptables-legacy`, whichever Docker itself uses for its embedded-DNS rules in this namespace (otherwise whichever works). The image is `registry.k8s.io/build-image/distroless-iptables`, digest-pinned, with no package installs at runtime.
- **IPv4 only:** Docker leaves IPv4-only networks without IPv6. If the guarded interface ever has an IPv6 address the holder refuses to start, so the proxy does not start either.
- **Failure behaviour:** closed. If the interface, the backend or the rules cannot be set, the holder exits non-zero and the proxy never starts. Restarting or recreating only the proxy keeps the rules. If `traefik-public-net` is restarted on its own, the proxy stays attached to the old namespace (no interfaces, no traffic) while still reporting healthy, because its health endpoint is on loopback: restart `traefik-public` afterwards. A redeploy that changes the holder's configuration recreates both.
- **Verify after a deploy** (Portainer docker exec or a shell):
  1. `docker logs traefik-public-net` ends with `egress-guard: backend=<iptables-nft|iptables-legacy> interface=<ethN> rules applied`, and the container is healthy.
  2. `docker exec traefik-public-net <backend> -S OUTPUT` shows `-A OUTPUT -o <ethN> -j EGRESS_GUARD`; `<backend> -S EGRESS_GUARD` lists the `RETURN` for established traffic followed by five `DROP` rules.
  3. `docker exec traefik-public nc -z -w2 <host> <port>` (exit status): a LAN host, the gateway and another macvlan IP must fail; a public address on 443, `acme-v02.api.letsencrypt.org` 443, `immich_server` 2283 and `pocket-id` 1411 must succeed.
  4. The usual checks: the public routes answer through the forward, and `docker logs traefik-public` shows no ACME errors.
- **Rollback:** revert the commit and redeploy. No host state is touched.

## Environment variables

All are required except `TZ` and the `PUBLIC_*_SUBNET` variables: an unset or empty value fails the deploy instead of generating a broken rule such as ``Host(`foto.`)``.

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
| `POCKET_ID_SUBDOMAIN` | Hostname segment of the Pocket-ID router; same value as the pocket-id stack, and the host of Pocket-ID's `APP_URL`. |
| `JELLYFIN_SUBDOMAIN` | Hostname segment of the Jellyfin router; same value as the jellyfin stack. |
| `NAVIDROME_SUBDOMAIN` | Hostname segment of the Navidrome router; same value as the navidrome stack. |
| `GOKAPI_SUBDOMAIN` | Hostname segment of the Gokapi router; same value as the gokapi stack. |
| `GITEA_SUBDOMAIN` | Hostname segment of the Gitea router; same value as the gitea stack, and the host of Gitea's `ROOT_URL`. |
| `PRIVATEBIN_SUBDOMAIN` | Hostname segment of the PrivateBin router; same value as the privatebin stack. |
| `PUBLIC_POCKET_ID_SUBNET` | Optional. Subnet of the `public-pocket-id` network (default `172.16.77.0/28`). Outside Docker's default address pools, the LAN/VLANs and the tailnet. |
| `PUBLIC_JELLYFIN_SUBNET`, `PUBLIC_NAVIDROME_SUBNET`, `PUBLIC_GOKAPI_SUBNET`, `PUBLIC_GITEA_SUBNET`, `PUBLIC_PRIVATEBIN_SUBNET` | Optional. Subnets of the matching backend networks (defaults `172.16.78.0/28` to `172.16.82.0/28`, in that order). Same placement rules as above; each must be unique among all Docker networks on the host. A subnet can only be changed while no container is attached to the network. |
| `PUBLIC_JELLYFIN_PROXY_IP`, `PUBLIC_NAVIDROME_PROXY_IP`, `PUBLIC_GOKAPI_PROXY_IP`, `PUBLIC_GITEA_PROXY_IP`, `PUBLIC_PRIVATEBIN_PROXY_IP` | Optional. The proxy's fixed address on the matching backend network (defaults `172.16.78.2` to `172.16.82.2`). Must lie inside the matching `PUBLIC_*_SUBNET` and must not be its first address (the Docker gateway); change both together or the proxy container fails to start. |

## Deploy order

1. Create the dedicated Cloudflare token and set the variables on a new Portainer stack `traefik-public` (this directory's compose file).
2. Deploy `traefik-public` **first**. It creates the `public-apps` network and requests the certificates (DNS-01 needs neither the port forward nor public DNS records). Wait for the container to be healthy and for the certificates to appear in the logs / `acme.json`.
3. Only afterwards deploy the updated `immich` stack: it declares `public-apps` as external and fails to start if that network does not exist yet. Do not push the immich edit before step 2 is done.
4. Test with `curl --resolve <test-host>:443:<TRAEFIK_PUBLIC_IP> https://<test-host>/api/server/ping` from a LAN device other than the NAS (the LAN resolvers wildcard-override `*.${DOMAIN}` to the NAS, so plain names do not reach this stack from inside the LAN).
5. In UniFi, forward WAN TCP 443 to `${TRAEFIK_PUBLIC_IP}:443`. Create the public DNS records as **DNS only** (not proxied), IPv4 only unless an IPv6 path is set up.

## Adding Pocket-ID (second backend)

Pocket-ID keeps its passkey login and its existing private, tailnet and Cloudflare paths; this only adds the public router and a dedicated backend network.

1. Add `POCKET_ID_SUBDOMAIN` (and optionally `PUBLIC_POCKET_ID_SUBNET`) to the `traefik-public` stack's environment **before** the commit reaches it. The variable is required, so a deploy without it fails at interpolation and leaves the running containers untouched.
2. Deploy `traefik-public` **first**. It creates the `public-pocket-id` network and requests the Pocket-ID certificate (DNS-01). The proxy container is recreated, so the public Immich path has a short gap. Wait for the container to be healthy and for the certificate to appear.
3. Only afterwards deploy the updated `pocket-id` stack. It declares `public-pocket-id` as external; if the network does not exist yet the deploy fails before touching the running container, and the next poll retries. Pocket-ID itself is recreated: requests fail for a few seconds, while sessions and signing keys live in its data volume and survive.
4. Confirm self sign-up is off in the running instance before the public DNS record goes live: `curl -s https://<pocket-id-host>/api/application-configuration | jq -r '.[] | select(.key=="allowUserSignups") | .value'` must print `disabled` (admin UI: Application configuration, User signups). In Pocket-ID v1 the `ALLOW_USER_SIGNUPS` variable only takes effect together with `UI_CONFIG_DISABLED=true`, which would move every other setting to the environment, so the admin UI setting is the control.
5. Create the DNS-only public record and test with `curl --resolve <pocket-id-host>:443:<TRAEFIK_PUBLIC_IP> https://<pocket-id-host>/.well-known/openid-configuration` from a LAN device other than the NAS.

## Adding a batch of backends (Jellyfin, Navidrome, Gokapi, Gitea, PrivateBin)

Same mechanics as Pocket-ID, five backends at once: five routers sharing the header-strip middleware, five dedicated `internal: true` networks. The applications keep their existing private and tailnet paths; this only adds the public routers and networks.

1. Add the five `*_SUBDOMAIN` variables (and optionally the `PUBLIC_*_SUBNET` ones) to the `traefik-public` stack's environment **before** the commit reaches it. They are required, so a deploy without them fails at interpolation and leaves the running containers untouched.
2. Deploy `traefik-public` **first**. It creates the five networks and requests five certificates (DNS-01), which count toward the weekly Let's Encrypt quota. Because the networks are attached to `traefik-public-net`, that container and the proxy are both recreated, so the public Immich and Pocket-ID paths have a short gap. Wait until `traefik-public-net` and `traefik-public` are healthy and the certificates appear in the logs / `acme.json`.
3. Only afterwards deploy the updated application stacks, one at a time. Each declares its `public-<app>` network as external and attaches the backend service to it; if the network does not exist yet the deploy fails before touching the running container, and the next poll retries. Each application is recreated, so expect a few seconds of downtime per app.
4. Make each application trust the proxy as a forwarder: its trusted-proxy setting has to cover the proxy's address on the backend network: the `/28` where a CIDR is accepted, or the fixed proxy address from the Networks table where only host addresses are (Jellyfin: `172.16.78.2`). The proxy sets `X-Forwarded-For` to the real client address, so an application that ignores it would see every client as the proxy.
5. After the application is up, `docker exec traefik-public nc -z -w2 <container> <port>` (exit status 0) confirms the proxy reaches it over the backend network.
6. Create the DNS-only public records and test with `curl --resolve <host>:443:<TRAEFIK_PUBLIC_IP> https://<host>/` from a LAN device other than the NAS. A request carrying a forged `CF-Connecting-IP` or `True-Client-IP` header must reach the application without it.

## Rollback

1. Remove the UniFi WAN 443 forward.
2. Flip the affected public DNS record(s) back to their previous (Cloudflare Tunnel) target.
3. Optionally stop the `traefik-public` stack. Stopping keeps the `public-*` backend networks, so every backend keeps starting.

To delete the stack entirely, first revert the `public-*` network entries in each backend's own stack (`../immich`, `../pocket-id`, `../jellyfin`, `../navidrome`, `../gokapi`, `../gitea`, `../privatebin`) and redeploy them; otherwise the networks cannot be removed while attached and those stacks cannot start without them. To withdraw a single backend, flip its DNS record back, remove the network entries from its stack and redeploy it, then remove its router, service and network from this stack.

## Operating rules

- **Never add `TRAEFIK_PUBLIC_IP` to `MACVLAN_ATTACHED_IPS` in `../macvlan-host-shim/`.** That list creates host-side routes to the listed macvlan IPs and would remove the host/macvlan isolation this stack relies on, giving a compromised proxy a path to the NAS host.
- **Keep the egress guard's allowances narrow.** Any new need to reach a private address from the proxy goes through the backend networks (an `internal: true` network per backend), never by loosening the guard on the macvlan interface.
- **Remove the `public-test` router** (and `PUBLIC_TEST_SUBDOMAIN`) from the init command once the Immich cutover is verified.
- **One dedicated backend network per backend.** `public-apps` is Immich's, `public-pocket-id` is Pocket-ID's and `public-<app>` belongs to the application of that name. For each additional public service, create its own `internal: true` network in this stack with an explicit subnet outside Docker's default address pools (those pools are nearly exhausted, and an explicit subnet cannot collide with an auto-allocated one), declare it external in that service's stack and add it to the `traefik-public-net` service's networks. Never put several backends on one shared network.
- **Adding a public service:** add a router (and a service block if the backend differs) to the heredoc in `traefik-public-init`'s command, attach the backend as above, and create the DNS-only record. The router's `middlewares` list must be `public-strip-client-headers` followed by `public-secure-headers`; a router without the first one passes forged client-IP and identity headers through to the backend. Each new hostname requests its own certificate.

## Planned hardening

Before widening exposure beyond the first service:

- Per-source connection cap (CrowdSec or an nftables `ct count` rule) and a country allow-list on the gateway; rate limiting and forward-auth once real client IPs are confirmed in the access log, since they can break Immich bulk uploads and the mobile apps.
- Watch the UniFi gateway's conntrack table under load.
- Alert on certificate expiry (renewal failures are otherwise silent until a certificate lapses).
- Optional later upgrade: attach the container to a DMZ network on the NAS's second port. The [egress guard](#egress-guard) already contains the proxy without it; a DMZ would additionally route that traffic through the gateway, where a zone rule can see and filter it, and make the guard a second layer instead of the only one.

Before real services move over, narrow the DNS-01 credential. The Cloudflare token can edit every record in the zone. Option: delegate `_acme-challenge.<host>` by CNAME to a dedicated acme-dns zone so this host holds no Cloudflare token at all. TLS-ALPN-01 and HTTP-01 are not alternatives while a country allow-list on the gateway blocks Let's Encrypt's validators.
