# traefik-public

Internet-facing Traefik for the 18 services that must be reachable from the public internet. It carries all public traffic; there is no Cloudflare Tunnel any more (it capped uploads at 100 MB and restricted video, and was retired 2026-11-03). Cloudflare only hosts DNS: each public name is a DNS-only (grey cloud) CNAME to `wg.${DOMAIN}`, which UniFi DDNS keeps pointed at the WAN address. It is a separate instance from `../traefik/` on purpose: small, hardened and isolated from the rest of the estate.

## Address

Own macvlan LAN IP `${TRAEFIK_PUBLIC_IP}` (this instance: `192.168.1.94`), TCP **443** only - no port 80, no HTTP/3, no published host ports. The UniFi gateway forwards WAN TCP 443 to that IP, with UniFi Region Blocking (Incoming, Allow CH and IT) in front. Clients connect directly, so Traefik logs the real client IP (confirmed 2026-11-03 with a request through the UniFi forward).

The container joins the existing macvlan network `traefik-private-forwarder_traefik_forwarder_net` (Docker allows only one per parent/subnet - see `.claude/rules/networking.md`). The NAS host itself cannot reach a macvlan IP on its own parent interface; test from another LAN device or from outside the LAN.

## What it does

- **File provider only.** No Docker socket, no Docker provider, no dashboard, no API. Routers, the service and the middleware are generated into `${VOLUME_CONFIG}/traefik-public/dynamic/dynamic.yml` by the `traefik-public-init` container on every deploy. The compose file is the only source of truth; never hand-edit `dynamic.yml`.
- **Routers** (single entrypoint `websecure`, hostnames are `<subdomain>.${DOMAIN}`):

  | Subdomain variable | Backend |
  |---|---|
  | `IMMICH_SUBDOMAIN` | `http://immich_server:2283` |
  | `POCKET_ID_SUBDOMAIN` | `http://pocket-id:1411` |
  | `JELLYFIN_SUBDOMAIN` | `http://jellyfin:8096` |
  | `NAVIDROME_SUBDOMAIN` | `http://navidrome:4533` |
  | `GOKAPI_SUBDOMAIN` | `http://gokapi:53842` |
  | `GITEA_SUBDOMAIN` | `http://gitea:3000` |
  | `PRIVATEBIN_SUBDOMAIN` | `http://privatebin:8080` |
  | `MEALIE_SUBDOMAIN` | `http://mealie:9000` (`/docs`, `/redoc` and `/openapi.json` answer 404) |
  | `HOMEBOX_SUBDOMAIN` | `http://homebox:7745` |
  | `KAVITA_SUBDOMAIN` | `http://kavita:5000` |
  | `OPENCLOUD_SUBDOMAIN` | `http://opencloud:9200` (app-framing header profile) |
  | `HI_EVENTS_SUBDOMAIN` | `http://all-in-one:80` |
  | `EASY_APPOINTMENTS_SUBDOMAIN` | `http://easy-appointments-nginx:80` (Host header passed unchanged, REST API prefixes answer 404) |
  | `TREK_SUBDOMAIN` | `http://trek:3000` (app-framing header profile) |
  | `PAPERLESS_SUBDOMAIN` | `http://paperlessngx:8000` (app-framing header profile, `/api/schema...` and `/api/remote_version/` answer 404; WebSocket `/ws/status/`) |
  | `LINKWARDEN_SUBDOMAIN` | `http://linkwarden:3000` (app-framing header profile) |
  | `ACTUAL_BUDGET_SUBDOMAIN` | `http://ActualBudget:5006` (the Actual server; its own COOP/COEP headers pass through) |
  | `BYTESTASH_SUBDOMAIN` | `http://bytestash:5000` (public snippets only: two routers accept `GET`/`HEAD` for an explicit path allowlist, everything else answers 404; see [Public snippets only](#bytestash-public-snippets-only)) |

  Any other hostname gets Traefik's default 404, and `sniStrict` rejects TLS handshakes for names without a certificate. Each router sets `certResolver` explicitly: a router-level `tls` section replaces the entrypoint's TLS settings entirely.
- **Certificates:** one per router hostname via ACME DNS-01 (resolver `cf_dns_public`, Cloudflare), EC256 keys, own `acme.json`, own token. No wildcard. These count against the same Let's Encrypt registered-domain quota (50 per week) as the core Traefik, so keep the hostname count small and keep `acme.json` backed up.
- **Headers and TLS:** `public-secure-headers` (HSTS 1 year + subdomains + preload, nosniff, frame deny, `same-origin` referrer policy). TLS 1.2 minimum, AEAD cipher suites only. Request headers with aliasing names (`X_Foo`, `X.Foo`) are stripped.
- **Header profiles:** every router uses `public-secure-headers` except OpenCloud, TREK, Paperless-ngx and Linkwarden, which use `public-secure-headers-app-framing`: the same HSTS and nosniff, but `X-Frame-Options: SAMEORIGIN` instead of `DENY` and `Referrer-Policy: strict-origin-when-cross-origin`. OpenCloud and TREK send their own `X-Frame-Options: SAMEORIGIN`, a CSP with `frame-ancestors 'self'` and the same referrer policy, and their web UIs frame their own origin (TREK's `/plugin-frame/*`, OpenCloud's embedded apps), so `DENY` would break them; Paperless-ngx previews documents in an `<object>` of its own `/api/documents/<id>/preview/` and sends `SAMEORIGIN` itself, and Linkwarden shows archived pages and PDFs in an `<iframe>` of its own `/api/v1/archives/...` (read from `PreservationContent.tsx`), which `DENY` would also block, even for the same origin; Paperless's own `Referrer-Policy: same-origin` becomes `strict-origin-when-cross-origin` on this profile, which is harmless there; the proxy adds no CSP and the apps' CSP passes through untouched. The referrer policy matches what the apps send because TREK's browser loads map tiles from third-party tile servers (some providers want a Referer); `strict-origin-when-cross-origin` sends only the origin to another site, never a path or query, so share and invite tokens in URLs do not leak. Hi.Events (its ticket widget is not embedded on other sites), Easy!Appointments and the Actual server routers keep frame deny. The Actual server sets its own `Cross-Origin-Opener-Policy: same-origin`, `Cross-Origin-Embedder-Policy: require-corp` and CSP (needed for `SharedArrayBuffer`); the proxy never touches those. Whether the Easy!Appointments booking page is embedded on another site is not known; if it is, neither profile fits (a third-party embed needs no `X-Frame-Options` and a CSP `frame-ancestors` naming that site), so it needs a profile of its own.
- **Excluded paths:** four router rules carry path exclusions. The Actual server (`budget`) excludes `/openid/enable`, `/openid/disable`, `/openid/config`, `/account/bootstrap`, `/account/change-password` and `/account/server-prefs`, each with any sub-path, case-insensitively and with an optional trailing slash, because Express ignores case and trailing slashes (`/OpenID/Enable/` reaches the same handler). Nobody needs them from the internet: the owner is already claimed, so bootstrap and `openid/config` only answer `already-bootstrapped`, and `openid/disable` checks the password without a rate limit of its own. Left open on purpose: `/openid/callback` (the IdP redirects the browser there), `/account/login-methods`, `/account/validate`, `/account/needs-bootstrap`, `/info`, `/sync/*`, `/admin/owner-created/*`. The router also carries the `[^/A-Za-z0-9._~-]` character guard (see Encoded paths); none of the 193 files in the 26.11.0 web build has an unsafe character, and the API paths are fixed names and UUIDs. Paperless-ngx excludes `/api/schema` and below (the unauthenticated OpenAPI schema and Swagger UI; `/api/` redirects there, so it ends in a 404 too) and `/api/remote_version/` (unauthenticated; it only says whether a newer release exists, which tells a scanner the instance is behind; the web UI's update notice stops working, the UI itself is unaffected). Mealie excludes `/docs`, `/docs/...`, `/redoc` and `/openapi.json` (FastAPI's docs; they answer without a login; Mealie's own `API_DOCS=false` only removes `/docs`; `/redoc` and `/openapi.json` stay, from the v3.30.0 source; Mealie now follows `:latest`, so re-check these paths after an upgrade). Easy!Appointments excludes `/api`, `/api/...`, `/index.php/api` and `/index.php/api/...` (the REST API). The match is on whole path segments on purpose: `/index.php/api_settings` is the staff API-settings page and stays reachable. A request for an excluded path matches no router, so Traefik answers 404 itself: no middleware runs (no HSTS header on that response) and the access log shows the request without a router name, with its path. Dot segments and doubled slashes are normalized before matching (`//api/...`, `/x/../api/...`, `/%61pi/...` are all caught). **Limit:** a Traefik rule sees only the path. CodeIgniter (Easy!Appointments) also takes the route from a query string that starts with `/`, so `/?/api/v1/appointments`, `/index.php?/api/v1/appointments` and `/index.php/?/api/v1/appointments` reached the REST API controller through this proxy in a local test with the real 1.6.1 code. Closing that needs the app's own nginx vhost (`../easy-appointments/nginx/default.conf.template`) to refuse a query string that starts with `/` (`if ($args ~ "^/") { return 404; }` in the server block; tested locally, the three forms then answer 404 and the booking and staff pages are unaffected). Until the vhost has it, the REST API (HTTP basic auth or API token required) is only blocked for the path forms. Checked locally against `traefik:v3.7.17` (stand-in backends): the Paperless schema and update-check forms answer 404 (also `/api/%73chema/`), `/api/documents/` and `/ws/status/` reach it.
- **Encoded paths:** Traefik decodes percent-encoded unreserved characters before routing but leaves encoded reserved ones (`%2f`, `%3b`, `%00`...) as they are, and its default entrypoint settings allow them through. In a local test with `traefik:v3.7.17` the ByteStash forms `/assets/..%2fapi%2fsnippets`, `/assets/%2e%2e%2fapi%2fsnippets`, `/monacoeditorwork/..%2f..%2fapi%2fsnippets`, `/assets/..;/api/snippets` were routed to the backend. Whether the backend would have acted on them was not tested (Express matches its route table on the raw path, so most would be a 404 there). The ByteStash router therefore carries `!PathRegexp(`[^/A-Za-z0-9._~-]`)`: a path with any character outside letters, digits and `/._~-` matches no router (404), which covers `%`, `;`, spaces and control characters. After that all the probes above answer 404, the allowlisted ByteStash paths are still routed. The entrypoint-wide `encodedCharacters` switches were left alone: they would reject legitimate encoded `#`, `?`, `;` and `%` in file names on OpenCloud, Gokapi and others.
- **Rate limits (per source address, a starting point):** `rateLimit` middlewares keyed on the TCP peer address, which on this entrypoint is the real client (no `forwardedHeaders.trustedIPs`), listed after the header middlewares so a 429 still carries HSTS. Clients behind one NAT share a bucket. Each router has its own bucket. A router that carries a limit for only some paths is a separate router with `priority: 1000` (the other routers on those hosts have their rule length as priority, a few hundred at most), so the normal UI and uploads are unaffected.

  | Middleware | Used by | Numbers | Notes |
  |---|---|---|---|
  | `public-ratelimit-login` | `paperless-login`: `/api/token/`, `/api/auth/login/`, everything under `/accounts/` (login, 2FA, password reset, logout; all in `src/paperless/urls.py` of Paperless-ngx). `linkwarden-login`: `/api/v1/auth/callback...` (credentials login), `/api/v1/auth/forgot-password`, `reset-password`, `request-verification-email`, `/api/v1/session` (login for an API token) and `POST /api/v1/users` (registration) | 6 per minute, burst 10 | A mistyped login is two to three requests, so about four attempts fit in the burst, then one every 10 s. Linkwarden's `/api/v1/auth/session` and `/csrf` are not limited because the web UI polls them |
  | `public-ratelimit-budget-login` | `budget-login`: `POST /account/login` on the Actual server, matched as `(?i)^/account/login/?$` (case and trailing slash do not get around it) | 10 per minute, burst 10 | `/account/login` is also the OIDC start for the web UI and the Actuali iOS app, so it cannot be blocked, and Traefik cannot tell a password login from an OIDC start (same path and method, only the JSON body differs). A normal login is one or two calls, so the cap never touches it; the app's own limit is 5 failures per 15 minutes per address, this is a front cap. Everything else on the host is not limited |
  | `public-bytestash-api-ratelimit` | `bytestash-api` | 10 per second, burst 30 | A page view makes about three API calls |

  Checked with `traefik:v3.7.17` and stand-in backends: 20 rapid `POST /api/token/` gave 10 routed and 10 `429`; the same burst against Linkwarden's credentials callback gave 10 and 10; 20 `POST /api/v1/users` all `429` after that router's bucket was used; `/api/documents/`, `post_document`, Linkwarden's `/api/v1/users` GET, `/api/v1/auth/session` (60 requests) and `/api/v1/links` were never limited; the Actual login router limited after 10. The numbers are not load-tested against the real apps; adjust them if the access log shows legitimate 429s.
- **Client-supplied identity headers:** every router lists `public-strip-client-headers` before its secure-headers middleware. It deletes (an empty `customRequestHeaders` value removes the header) the client-IP headers `CF-Connecting-IP`, `CF-Connecting-IPv6`, `True-Client-IP`, `X-Client-IP`, `X-Cluster-Client-IP` and `Forwarded`, and the proxy-authentication identity headers `Remote-User`, `Remote-Email`, `Remote-Name`, `Remote-Groups`, `X-Forwarded-User`, `X-Forwarded-Email`, `X-Webauth-User`, `X-Webauth-Email` and `X-Webauth-Fullname`. This path never sets any of them, so nothing legitimate is lost, and a backend with a trusted-proxy or header-authentication feature cannot be fed a forged value. `X-Forwarded-For`, `X-Real-Ip` and `X-Forwarded-Proto/Host/Port/Server` need no stripping: with no `forwardedHeaders.trustedIPs` configured, Traefik replaces them with values derived from the TCP peer (and drops `X-Forwarded-Prefix` and `X-Forwarded-Uri`), so `X-Real-IP` is deliberately not in the list (deleting it would remove the genuine value Traefik sets). Checked against `traefik:v3.7.17` with spoofed values for every header named here.
- **Timeouts:** read and write 86400s (24h), idle 180s. The read and write values are total per-request budgets, not inactivity timers; 24h covers about 100 GB at 10 Mbit/s in a single request. Slow-client limits come from the planned per-source controls below, not from these values. Resumable/chunked clients (Gokapi chunks, OpenCloud/TUS) remain the robust way to move very large files, because a dropped single-request upload restarts from zero. There is no request-body size limit anywhere (no `buffering` middleware). Checked locally through this proxy with stand-in backends: a 600 MiB `Content-Length` POST and a 300 MiB chunked PUT arrive byte for byte, WebDAV methods (`PROPFIND`, `PROPPATCH`, `MKCOL`, `COPY`, `MOVE`, `LOCK`, `UNLOCK`, `REPORT`), TUS `PATCH`/`HEAD` with their headers and `Authorization` arrive unchanged, an SSE stream is delivered event by event (not buffered), and a WebSocket upgrade returns 101.
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
| `public-mealie` (created here, `internal: true`, explicit subnet, gateway and ip_range) | Mealie's backend network. Default subnet `172.16.83.0/28`. |
| `public-homebox` (same) | Homebox's backend network. Default subnet `172.16.84.0/28`. |
| `public-kavita` (same) | Kavita's backend network. Default subnet `172.16.85.0/28`. |
| `public-opencloud` (same) | OpenCloud's backend network. Default subnet `172.16.86.0/28`. |
| `public-hi-events` (same) | Hi.Events' backend network. Default subnet `172.16.87.0/28`. |
| `public-easy-appointments` (same) | Easy!Appointments' backend network (its nginx only). Default subnet `172.16.88.0/28`; the stack's own `easy-appointments-backend` network is `172.16.88.16/28`. |
| `public-trek` (same) | TREK's backend network. Default subnet `172.16.89.0/28`. |
| `public-paperless` (same) | Paperless-ngx's backend network (its web container only). Default subnet `172.16.90.0/28`; the stack's own backend network for the database and helpers is `172.16.90.16/28`. |
| `public-linkwarden` (same) | Linkwarden's backend network. Default subnet `172.16.91.0/28`; the stack's own database network is `172.16.91.16/28`. |
| `public-budget` (same) | Actual server's backend network. Default subnet `172.16.93.0/28`. |
| `public-bytestash` (same) | ByteStash's backend network. Default subnet `172.16.92.0/28`. |

`172.16.94.0/28` (formerly `public-budget-api`) and `172.16.95.0/28` (formerly `public-budget-tap`) are released; ActualAPI, actualtap and actual-ical are private-only (owner decisions 2026-11-03). `172.16.96.0/28` (actual-ical) stays reserved and unused.

Each backend's own stack declares its network as `external: true`. A `/28` holds only the proxy and its one backend. The proxy appears to the backend as an address inside that subnet, which is what the backend's trusted-proxy setting has to cover. On every application network the proxy has a fixed address, so a backend whose trusted-proxy field takes only host addresses (Jellyfin's Known Proxies) can name it; the others can use the `/28` itself:

| Network | Subnet | Gateway (Docker) | Proxy address | Backend address |
|---|---|---|---|---|
| `public-jellyfin` | `172.16.78.0/28` | `172.16.78.1` | `172.16.78.2` | `.8` to `.14` (`ip_range` `172.16.78.8/29`) |
| `public-navidrome` | `172.16.79.0/28` | `172.16.79.1` | `172.16.79.2` | `.8` to `.14` (`ip_range` `172.16.79.8/29`) |
| `public-gokapi` | `172.16.80.0/28` | `172.16.80.1` | `172.16.80.2` | `.8` to `.14` (`ip_range` `172.16.80.8/29`) |
| `public-gitea` | `172.16.81.0/28` | `172.16.81.1` | `172.16.81.2` | `.8` to `.14` (`ip_range` `172.16.81.8/29`) |
| `public-privatebin` | `172.16.82.0/28` | `172.16.82.1` | `172.16.82.2` | `.8` to `.14` (`ip_range` `172.16.82.8/29`) |
| `public-mealie` | `172.16.83.0/28` | `172.16.83.1` | `172.16.83.2` | `.8` to `.14` (`ip_range` `172.16.83.8/29`) |
| `public-homebox` | `172.16.84.0/28` | `172.16.84.1` | `172.16.84.2` | `.8` to `.14` (`172.16.84.8/29`) |
| `public-kavita` | `172.16.85.0/28` | `172.16.85.1` | `172.16.85.2` | `.8` to `.14` (`172.16.85.8/29`) |
| `public-opencloud` | `172.16.86.0/28` | `172.16.86.1` | `172.16.86.2` | `.8` to `.14` (`172.16.86.8/29`) |
| `public-hi-events` | `172.16.87.0/28` | `172.16.87.1` | `172.16.87.2` | `.8` to `.14` (`172.16.87.8/29`) |
| `public-easy-appointments` | `172.16.88.0/28` | `172.16.88.1` | `172.16.88.2` | `.8` to `.14` (`172.16.88.8/29`) |
| `public-trek` | `172.16.89.0/28` | `172.16.89.1` | `172.16.89.2` | `.8` to `.14` (`172.16.89.8/29`) |
| `public-paperless` | `172.16.90.0/28` | `172.16.90.1` | `172.16.90.2` | `.8` to `.14` (`172.16.90.8/29`) |
| `public-linkwarden` | `172.16.91.0/28` | `172.16.91.1` | `172.16.91.2` | `.8` to `.14` (`172.16.91.8/29`) |
| `public-budget` | `172.16.93.0/28` | `172.16.93.1` | `172.16.93.2` | `.8` to `.14` (`172.16.93.8/29`) |
| `public-bytestash` | `172.16.92.0/28` | `172.16.92.1` | `172.16.92.2` | `.8` to `.14` (`172.16.92.8/29`) |

`public-apps` and `public-pocket-id` keep Docker-assigned proxy addresses.

**Why every backend network with a fixed proxy address has an `ip_range`.** Docker hands the lowest free address to whichever container attaches first, and a fixed address (`ipv4_address`) only reserves it at the moment the proxy attaches. On a network without an `ip_range` the first backend to attach therefore gets `.2`, the proxy's address, whenever it attaches before the proxy: after a host reboot (container start order is not defined), or when a backend is recreated while `traefik-public-net` is down or being recreated (a push to main redeploys every stack). The proxy's attach then fails with `Address already in use`, `traefik-public-net` does not start, and neither does the proxy: the whole public edge, Immich and Pocket-ID included, stays down until the backend holding `.2` is stopped or recreated. Reproduced locally (Docker 29.9.1): a backend started first on a network without `ip_range` took `.2` and the proxy's holder failed with exactly that error; on the Batch 2 networks the seven backends were started first (they took `.8`) and the holder still attached `.2` on all of them. The `ip_range` is the upper half of each `/28` and the proxy's `.2` lies outside it; Docker accepts a fixed address outside the `ip_range`. Each network also sets its `gateway` explicitly (`.1`): without it Docker takes the first address of the `ip_range` as the gateway.

**Batch 1 was migrated on 2026-11-04.** `public-jellyfin`, `public-navidrome`, `public-gokapi`, `public-gitea` and `public-privatebin` were created without an `ip_range` and now have the same `gateway` and `ip_range` as the later batches. Docker cannot change a live network's IPAM in place: a changed definition makes Compose stop the proxy's holder container, try to remove the network and fail with `has active endpoints` while the backends are attached, which leaves the proxy stopped (reproduced locally). The migration therefore ran as a maintenance window: stop `traefik-public`, stop the five backend containers, remove the five networks, push the new definitions, redeploy `traefik-public`, then redeploy the five backend stacks so they attach to the new networks. Do the same if any of these networks ever needs a different subnet or range. Recovery if the race ever happens anyway: stop or recreate the backend that took `.2` (`docker network inspect public-<app>` shows who holds it), then redeploy or restart `traefik-public-net` and `traefik-public`. `public-apps` and `public-pocket-id` are not affected (no fixed proxy address there).

Deliberately not on `traefik-proxy` (the shared network of the private and tailnet-admin Traefik routers): public traffic reaches the apps only through the per-app `public-<app>` networks.

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

All are required except `TZ` and the optional `PUBLIC_*_SUBNET`, `PUBLIC_*_GATEWAY`, `PUBLIC_*_IP_RANGE` and `PUBLIC_*_PROXY_IP` variables: an unset or empty value fails the deploy instead of generating a broken rule such as ``Host(`foto.`)``.

| Variable | Purpose |
|---|---|
| `TZ` | Timezone. |
| `DOMAIN` | Base domain; routers match `<subdomain>.${DOMAIN}`. |
| `VOLUME_CONFIG` | Base path for `traefik-public/acme.json` and the generated `dynamic/` directory. |
| `ACME_EMAIL` | Let's Encrypt contact address. |
| `CF_DNS_API_TOKEN_PUBLIC` | Dedicated Cloudflare token `traefik-public-dns01` (Zone.DNS:Edit + Zone.Zone:Read, single zone). Never the core Traefik's token. |
| `TRAEFIK_PUBLIC_IP` | Free static LAN IP for the macvlan interface; the UniFi forward targets it. |
| `IMMICH_SUBDOMAIN` | Hostname segment of the Immich router; same value as the immich stack. |
| `POCKET_ID_SUBDOMAIN` | Hostname segment of the Pocket-ID router; same value as the pocket-id stack, and the host of Pocket-ID's `APP_URL`. |
| `JELLYFIN_SUBDOMAIN` | Hostname segment of the Jellyfin router; same value as the jellyfin stack. |
| `NAVIDROME_SUBDOMAIN` | Hostname segment of the Navidrome router; same value as the navidrome stack. |
| `GOKAPI_SUBDOMAIN` | Hostname segment of the Gokapi router; same value as the gokapi stack. |
| `GITEA_SUBDOMAIN` | Hostname segment of the Gitea router; same value as the gitea stack, and the host of Gitea's `ROOT_URL`. |
| `PRIVATEBIN_SUBDOMAIN` | Hostname segment of the PrivateBin router; same value as the privatebin stack. |
| `MEALIE_SUBDOMAIN` | Hostname segment of the Mealie router; same value as the mealie stack (`ricette` on this instance). |
| `HOMEBOX_SUBDOMAIN` | Hostname segment of the Homebox router; same value as the homebox stack. |
| `KAVITA_SUBDOMAIN` | Hostname segment of the Kavita router; same value as the kavita stack. |
| `OPENCLOUD_SUBDOMAIN` | Hostname segment of the OpenCloud router; same value as the opencloud stack, and the host of its `OC_URL`. |
| `HI_EVENTS_SUBDOMAIN` | Hostname segment of the Hi.Events router; same value as the hi-events stack (`eventi` on this instance). |
| `EASY_APPOINTMENTS_SUBDOMAIN` | Hostname segment of the Easy!Appointments router; same value as the easy-appointments stack (`appuntamenti` on this instance). Its nginx answers only this exact host. |
| `TREK_SUBDOMAIN` | Hostname segment of the TREK router; same value as the trek stack. |
| `PAPERLESS_SUBDOMAIN` | Hostname segment of the Paperless-ngx router; same value as the paperlessngx stack, and the host of its `PAPERLESS_URL` (`paperlessngx` on this instance). |
| `LINKWARDEN_SUBDOMAIN` | Hostname segment of the Linkwarden router; same value as the linkwarden stack, and the host of its `NEXTAUTH_URL`. |
| `ACTUAL_BUDGET_SUBDOMAIN` | Hostname segment of the Actual server router; same value as the actual-budget server stack (`budget` on this instance). |
| `BYTESTASH_SUBDOMAIN` | Hostname segment of the two ByteStash routers; same value as the bytestash stack (`bytestash` on this instance). |
| `PUBLIC_POCKET_ID_SUBNET` | Optional. Subnet of the `public-pocket-id` network (default `172.16.77.0/28`). Outside Docker's default address pools, the LAN/VLANs and the tailnet. |
| `PUBLIC_JELLYFIN_SUBNET`, `PUBLIC_NAVIDROME_SUBNET`, `PUBLIC_GOKAPI_SUBNET`, `PUBLIC_GITEA_SUBNET`, `PUBLIC_PRIVATEBIN_SUBNET`, `PUBLIC_MEALIE_SUBNET`, `PUBLIC_HOMEBOX_SUBNET`, `PUBLIC_KAVITA_SUBNET`, `PUBLIC_OPENCLOUD_SUBNET`, `PUBLIC_HI_EVENTS_SUBNET`, `PUBLIC_EASY_APPOINTMENTS_SUBNET`, `PUBLIC_TREK_SUBNET`, `PUBLIC_PAPERLESS_SUBNET`, `PUBLIC_LINKWARDEN_SUBNET`, `PUBLIC_BUDGET_SUBNET`, `PUBLIC_BYTESTASH_SUBNET` | Optional. Subnets of the matching backend networks (defaults `172.16.78.0/28` to `172.16.91.0/28`, then `172.16.93.0/28` and `172.16.95.0/28` (`172.16.94.0/28` is unused), then `172.16.92.0/28` for ByteStash, in the order of the names). Same placement rules as above; each must be unique among all Docker networks on the host. A subnet can only be changed while no container is attached to the network. |
| `PUBLIC_MEALIE_GATEWAY`, `PUBLIC_HOMEBOX_GATEWAY`, `PUBLIC_KAVITA_GATEWAY`, `PUBLIC_OPENCLOUD_GATEWAY`, `PUBLIC_HI_EVENTS_GATEWAY`, `PUBLIC_EASY_APPOINTMENTS_GATEWAY`, `PUBLIC_TREK_GATEWAY`, `PUBLIC_PAPERLESS_GATEWAY`, `PUBLIC_LINKWARDEN_GATEWAY`, `PUBLIC_BUDGET_GATEWAY`, `PUBLIC_BYTESTASH_GATEWAY` | Optional. Gateway of the Batch 2 and 3 backend networks: the first address of the matching subnet (defaults `172.16.83.1` to `172.16.95.1`). |
| `PUBLIC_MEALIE_IP_RANGE`, `PUBLIC_HOMEBOX_IP_RANGE`, `PUBLIC_KAVITA_IP_RANGE`, `PUBLIC_OPENCLOUD_IP_RANGE`, `PUBLIC_HI_EVENTS_IP_RANGE`, `PUBLIC_EASY_APPOINTMENTS_IP_RANGE`, `PUBLIC_TREK_IP_RANGE`, `PUBLIC_PAPERLESS_IP_RANGE`, `PUBLIC_LINKWARDEN_IP_RANGE`, `PUBLIC_BUDGET_IP_RANGE`, `PUBLIC_BYTESTASH_IP_RANGE` | Optional. The part of the matching subnet Docker hands backend addresses out of: its upper half (defaults `172.16.83.8/29` to `172.16.95.8/29`). Must lie inside the subnet and must not contain the proxy address or the gateway. |
| `PUBLIC_JELLYFIN_PROXY_IP`, `PUBLIC_NAVIDROME_PROXY_IP`, `PUBLIC_GOKAPI_PROXY_IP`, `PUBLIC_GITEA_PROXY_IP`, `PUBLIC_PRIVATEBIN_PROXY_IP`, `PUBLIC_MEALIE_PROXY_IP`, `PUBLIC_HOMEBOX_PROXY_IP`, `PUBLIC_KAVITA_PROXY_IP`, `PUBLIC_OPENCLOUD_PROXY_IP`, `PUBLIC_HI_EVENTS_PROXY_IP`, `PUBLIC_EASY_APPOINTMENTS_PROXY_IP`, `PUBLIC_TREK_PROXY_IP`, `PUBLIC_PAPERLESS_PROXY_IP`, `PUBLIC_LINKWARDEN_PROXY_IP`, `PUBLIC_BUDGET_PROXY_IP`, `PUBLIC_BYTESTASH_PROXY_IP` | Optional. The proxy's fixed address on the matching backend network (defaults `172.16.78.2` to `172.16.95.2`, including `172.16.92.2` for ByteStash, in the order of the subnet variables). Must lie inside the matching `PUBLIC_*_SUBNET` and must not be its first address (the Docker gateway); on the Batch 2 and 3 networks it must also lie outside the `PUBLIC_*_IP_RANGE`. Change all of a network's variables together or the proxy container fails to start. |

## Deploy order

1. Create the dedicated Cloudflare token and set the variables on a new Portainer stack `traefik-public` (this directory's compose file).
2. Deploy `traefik-public` **first**. It creates the `public-apps` network and requests the certificates (DNS-01 needs neither the port forward nor public DNS records). Wait for the container to be healthy and for the certificates to appear in the logs / `acme.json`.
3. Only afterwards deploy the updated `immich` stack: it declares `public-apps` as external and fails to start if that network does not exist yet. Do not push the immich edit before step 2 is done.
4. Test with `curl --resolve <test-host>:443:<TRAEFIK_PUBLIC_IP> https://<test-host>/api/server/ping` from a LAN device other than the NAS (the LAN resolvers wildcard-override `*.${DOMAIN}` to the private forwarder, so plain names do not reach this stack from inside the LAN).
5. In UniFi, forward WAN TCP 443 to `${TRAEFIK_PUBLIC_IP}:443`. Create the public DNS records as **DNS only** (not proxied), IPv4 only unless an IPv6 path is set up.

## Adding Pocket-ID (second backend)

Pocket-ID keeps its passkey login and its existing private and tailnet paths; this only adds the public router and a dedicated backend network.

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

## Adding the second batch (Mealie, Homebox, Kavita, OpenCloud, Hi.Events, Easy!Appointments, TREK)

Same mechanics as the first batch: seven routers sharing the header-strip middleware, seven dedicated `internal: true` networks with a fixed proxy address. Differences: the networks carry a `gateway` and an `ip_range` (see [Networks](#networks)), OpenCloud and TREK use the app-framing header profile, and the Mealie and Easy!Appointments routers exclude paths (see [What it does](#what-it-does)). Each application keeps its private and tailnet routers; its stack declares `public-<app>` as `external: true`.

1. Add the seven `*_SUBDOMAIN` variables to the `traefik-public` stack's environment **before** the commit reaches it. They are required, so a deploy without them fails at interpolation and leaves the running containers untouched. Each value must equal the one in that application's own stack. All other new variables are optional.
2. Deploy `traefik-public` **first**. It creates the seven networks and requests seven more certificates (DNS-01), which count toward the weekly Let's Encrypt quota; the public hostnames then total 14 (the `public-test` router that was counted here has since been removed). `traefik-public-net` and `traefik-public` are recreated, so the public Immich, Pocket-ID and first-batch paths have a short gap.
3. Only afterwards deploy the application stacks, one at a time (each declares its network as external and fails before touching the running container if the network is missing). Easy!Appointments also needs its new application directory first (its README has the steps), and Hi.Events should have a database backup first because its migrations run automatically at every start.
4. No application in this batch needs the proxy's fixed address: they trust the `/28` or a hop count (TREK `TRUST_PROXY=1`, Mealie `HOST_IP`, Hi.Events `APP_TRUSTED_PROXIES`, Easy!Appointments `PROXY_IPS`).
5. After each application is up, `docker exec traefik-public nc -z -w2 <container> <port>` confirms the proxy reaches it (`mealie` 9000, `homebox` 7745, `kavita` 5000, `opencloud` 9200, `all-in-one` 80, `trek` 3000, `easy-appointments-nginx` 80).
6. Test with `curl --resolve <host>:443:<TRAEFIK_PUBLIC_IP> https://<host>/...` from a LAN device other than the NAS: Mealie `/` answers and `/docs`, `/redoc`, `/openapi.json` answer 404; Easy!Appointments `/index.php/booking` answers and `/index.php/api/v1/appointments` answers 404 (and `/?/api/v1/appointments` too, once the vhost refuses query-string routes); OpenCloud and TREK responses carry `X-Frame-Options: SAMEORIGIN` and the app's own CSP; TREK's `/ws` upgrades; an OpenCloud `PROPFIND` with an app token returns 207.
7. Create the DNS-only public records last.

## Adding the third batch (Paperless-ngx, Linkwarden, Actual server)

Same mechanics as the second batch: three applications, three `internal: true` networks with `gateway`, `ip_range` and a fixed proxy `.2` (ByteStash, `172.16.92.0/28`, follows the same pattern, see below). ActualAPI, actualtap and actual-ical are deliberately NOT public (owner decisions 2026-11-03: everything exposing personal data or bound to the owner's budget stays on the private and tailnet paths; only the Actual server is internet-facing), so `172.16.94.0/28`, `172.16.95.0/28` and `172.16.96.0/28` stay unused. Paperless-ngx and Linkwarden use the app-framing header profile, Paperless-ngx excludes paths (see [What it does](#what-it-does)), and the Actual server routers use the default profile.

1. Add the three `*_SUBDOMAIN` variables (`PAPERLESS_SUBDOMAIN=paperlessngx`, `LINKWARDEN_SUBDOMAIN=linkwarden`, `ACTUAL_BUDGET_SUBDOMAIN=budget`) to the `traefik-public` stack's environment **before** the commit reaches it. They are required, so a deploy without them fails at interpolation and leaves the running containers untouched. Each value must equal the one in that application's own stack.
2. Deploy `traefik-public` **first**. It creates the three networks (four with ByteStash) and requests three more certificates (four with ByteStash, DNS-01); the public hostnames then total 18 including ByteStash (the `public-test` router has since been removed). `traefik-public-net` and `traefik-public` are recreated, so every public path has a short gap.
3. Only afterwards deploy the application stacks (each declares its `public-<app>` network as `external: true`). Container names the proxy resolves: `paperlessngx` (8000), `linkwarden` (3000), `ActualBudget` (5006).
4. `docker exec traefik-public nc -z -w2 <container> <port>` confirms the proxy reaches each backend.
5. Test with `curl --resolve <host>:443:<TRAEFIK_PUBLIC_IP> https://<host>/...` from a LAN device other than the NAS: Paperless `/api/schema/` and `/api/remote_version/` answer 404 and the document preview and `/ws/status/` work; Linkwarden's archived page and PDF views render; the Actual web UI loads with its own COOP/COEP headers and `/openid/config` answers 404 while `/openid/callback` is routed.
6. Create the DNS-only public records last.

### ByteStash: public snippets only

Owner decision: snippets marked public are readable from the internet; login, registration, the editor and the authenticated API stay on the private and tailnet paths. Two routers share the `bytestash` service and each matches `GET`/`HEAD` plus an explicit allowlist (read from ByteStash 1.6.1 and checked with an anonymous browser, see the rollout notes; ByteStash now follows `:latest`, so re-check the allowlist after an upgrade):

- `bytestash` (pages and static files): `/public/snippets`, `/snippets/<number>`, `/assets/...`, `/monacoeditorwork/...`, `/manifest.json`, `/favicon.ico`, `/logo192.png`, `/logo512.png` and the three `*-mark-white.svg` icons.
- `bytestash-api` (read-only data, with rate limit): `/api/public/snippets`, `/api/public/snippets/metadata`, `/api/public/snippets/<number>` and `/api/public/snippets/<number>/<number>/raw`.

Everything else answers Traefik's plain 404: `/`, `/login`, `/register`, all of `/api/auth/*` (the public pages work without it; "Sign in" links on the listing page lead to a 404 here), `/api/snippets*`, share links (`/s/*`, `/api/share/*`, `/api/embed/*`), `/mcp` and any write method. The rate limit is the `public-bytestash-api-ratelimit` middleware (`average: 10`, `period: 1s`, `burst: 30`, per client address, applied after the header middlewares so a 429 still carries HSTS). The numbers are a starting point, not load-tested: a page view makes about three API calls, so one visitor stays well under them; static files are not limited because a page load fetches many chunks. Consequences to know: `GET /api/public/snippets` lists every public snippet of every user (and the owner's username) in one request, so only mark snippets public that may be indexed; share links of non-public snippets are readable without login by anyone with the link, which is why they are not exposed (to allow them later add `PathRegexp(`^/s/[0-9a-f]{32}$`)` and `PathRegexp(`^/api/share/[0-9a-f]{32}$`)`, keep `/api/embed/` closed); API-key clients (editor extensions, MCP) no longer work from the internet.

## Rollback

1. Remove the UniFi WAN 443 forward.
2. Delete the affected public DNS record(s) (the Cloudflare Tunnel they used to point at no longer exists, so there is no previous target to flip back to). The names keep working on the LAN and the tailnet, where the wildcard resolvers answer them.
3. Optionally stop the `traefik-public` stack. Stopping keeps the `public-*` backend networks, so every backend keeps starting.

To delete the stack entirely, first revert the `public-*` network entries in each backend's own stack (`../immich`, `../pocket-id`, `../jellyfin`, `../navidrome`, `../gokapi`, `../gitea`, `../privatebin`, `../mealie`, `../homebox`, `../kavita`, `../opencloud`, `../hi-events`, `../easy-appointments`, `../trek`, `../paperlessngx`, `../linkwarden`, `../actual-budget/*`, `../bytestash`) and redeploy them; otherwise the networks cannot be removed while attached and those stacks cannot start without them. To withdraw a single backend, delete its public DNS record, remove the network entries from its stack and redeploy it, then remove its router, service and network from this stack.

## Operating rules

- **Never add `TRAEFIK_PUBLIC_IP` to `MACVLAN_ATTACHED_IPS` in `../macvlan-host-shim/`.** That list creates host-side routes to the listed macvlan IPs and would remove the host/macvlan isolation this stack relies on, giving a compromised proxy a path to the NAS host.
- **Keep the egress guard's allowances narrow.** Any new need to reach a private address from the proxy goes through the backend networks (an `internal: true` network per backend), never by loosening the guard on the macvlan interface.
- **One dedicated backend network per backend.** `public-apps` is Immich's, `public-pocket-id` is Pocket-ID's and `public-<app>` belongs to the application of that name. For each additional public service, create its own `internal: true` network in this stack with an explicit subnet outside Docker's default address pools (those pools are nearly exhausted, and an explicit subnet cannot collide with an auto-allocated one), an explicit `gateway` (the first address) and an `ip_range` in the upper half of the `/28` (so a backend can never take the proxy's fixed `.2` first), declare it external in that service's stack and add it to the `traefik-public-net` service's networks with `ipv4_address` set to `.2`. Never put several backends on one shared network.
- **Adding a public service:** add a router (and a service block if the backend differs) to the heredoc in `traefik-public-init`'s command, attach the backend as above, and create the DNS-only record. The router's `middlewares` list must be `public-strip-client-headers` followed by `public-secure-headers` (or `public-secure-headers-app-framing` for an application that frames its own origin and sends its own frame policy); a router without the first one passes forged client-IP and identity headers through to the backend. To hide a path, add `&& !Path(...)` / `&& !PathPrefix(...)` terms to the router rule (whole segments, so `/api` does not catch `/api_settings`) and re-test the dot-segment, encoded and query-string variants against the real application. Each new hostname requests its own certificate.

## Planned hardening

Before widening exposure beyond the first service:

- Per-source connection cap (CrowdSec or an nftables `ct count` rule) on the gateway (the country allow-list already exists: UniFi Region Blocking, Incoming, Allow CH and IT); rate limiting and forward-auth once real client IPs are confirmed in the access log, since they can break Immich bulk uploads and the mobile apps.
- Deferred, not applied: a small HAProxy hop between `traefik-public` and the Actual server on `public-budget` that accepts `POST /account/login` only with a strict OIDC-start JSON body and rejects explicit password logins (`loginMethod: password`, duplicate keys, urlencoded bodies), which is the only way to keep the shared server password from being usable on the public path while OIDC works. Tested config and results: `tools/actual-login-body-filter.haproxy.cfg` and the 2026-11-03 19:50 and 19:58 entries in the rollout notes (`findings/actual-budget.md`). The rate limit above is the interim control.
- Rate limits exist per source address on logins, the Actual login endpoint and ByteStash (see [What it does](#what-it-does)); a global or per-country control and forward-auth are still planned.
- Watch the UniFi gateway's conntrack table under load.
- Alert on certificate expiry (renewal failures are otherwise silent until a certificate lapses).
- Optional later upgrade: attach the container to a DMZ network on the NAS's second port. The [egress guard](#egress-guard) already contains the proxy without it; a DMZ would additionally route that traffic through the gateway, where a zone rule can see and filter it, and make the guard a second layer instead of the only one.

Before real services move over, narrow the DNS-01 credential. The Cloudflare token can edit every record in the zone. Option: delegate `_acme-challenge.<host>` by CNAME to a dedicated acme-dns zone so this host holds no Cloudflare token at all. TLS-ALPN-01 and HTTP-01 are not alternatives while a country allow-list on the gateway blocks Let's Encrypt's validators.
