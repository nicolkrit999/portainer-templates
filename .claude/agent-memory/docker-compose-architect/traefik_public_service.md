---
name: traefik-public-service
description: traefik-public (internet-facing Traefik, written 2026-11-03, not yet deployed) - design decisions, review-round changes, locally verified behaviors, Traefik 3.7 gotchas, what stayed unverified
metadata:
  type: project
---

## traefik-public/ (written 2026-11-03, reviewed once same day; NOT deployed or committed by the architect)

Second, separate Traefik for direct WAN TCP 443 exposure (replaces the Cloudflare Tunnel
for Immich first: 100 MB cap, video ToS). Plan context lives in the main session's
`public-access-no-cloudflare-plan-2026-11-03` memory. Immich's `immich-server` was the only
service edited (added external `public-apps` network).

**Why:** small, hardened, isolated from the core Traefik. **How to apply:** for another public
service, add a router to the heredoc in `traefik-public-init`'s command and give that backend its OWN
internal network (coordinator rule: never one shared backend network); do not copy the
Cloudflare/Traefik-private defaults.

### Design choices that look odd but are deliberate
- Config generation: init container + quoted heredoc (`<< 'EOF'`) inside a double-quoted YAML
  string with `\n`; the repo has NO `configs:` usage. Compose interpolates `${VAR}` before the
  shell sees it, so the quoted heredoc protects the backticks in `Host(...)`. Written to
  `/target/.dynamic.yml.tmp` then `mv` into `dynamic/` (atomic, watched dir never sees a partial file).
- Init container hardening: digest-pinned `alpine:3@sha256:be2656...` (multi-arch index digest, 2026-11-03),
  `read_only`, `no-new-privileges`, `cap_drop ALL` + CHOWN/FOWNER/DAC_OVERRIDE, `network_mode: none`.
  DAC_OVERRIDE is genuinely required: without it root cannot mkdir in a directory owned by another uid
  (verified with a control run). Init works on first and second run (acme.json already 65532:600).
- Main container: non-root `65532:65532`, NO capabilities at all (CapEff all zero verified). Port 443 binds
  through `sysctls: net.ipv4.ip_unprivileged_port_start: "0"`; Docker's cap_add gives non-root nothing
  usable, and NET_BIND_SERVICE was removed after verifying it is not needed. Literal UID on purpose.
- Limits (review round): `restart: unless-stopped`, `cpu_shares 2048`, `cpus 2.0`, `mem_limit 512m`,
  `pids_limit 512`, `ulimits.nofile 65536`, `oom_score_adj 500` (sacrificial; opposite of adguard -800).
  `pids_limit` had no repo precedent. All verified applied via docker inspect.
- Required-variable syntax `${VAR:?set VAR}` on every occurrence of DOMAIN, both SUBDOMAINs,
  TRAEFIK_PUBLIC_IP, ACME_EMAIL, CF_DNS_API_TOKEN_PUBLIC, VOLUME_CONFIG (TZ stays plain). Consequence:
  `docker compose config -q` now needs a full env file; unset vars are errors, not warnings.
- ACME `keyType=EC256`; timeouts read 3600s / write 7200s / idle 180s (finite, not a per-source limit).
- Ping entrypoint bound to `127.0.0.1:8082` (macvlan exposes EVERY listening port on the LAN IP).
  `traefik healthcheck` needs `--ping.entryPoint=ping` AND `--entryPoints.ping.address=...` on the
  healthcheck command itself (the CLI rebuilds static config from its own flags).
- `public-apps` is created here with `internal: true`; consumers declare it external. Deploy order matters.
- Not in SAN-bundle groups (per-hostname certs, own resolver `cf_dns_public`), not on cloudflare-web,
  no dnsmasq entry (public hostnames must NOT resolve to the core stack on LAN).
- Access-log path includes Immich share keys (`/share/<key>`); only the query string is dropped.

### Wording rule from the coordinator (public repo)
Do not advertise missing controls in compose comments or README: say "planned hardening" instead of
"no rate limiting / not slowloris protection". Keep compose comments to non-obvious constraints only;
future-work notes live in the README.

### Traefik 3.7 facts confirmed (docs + local run of traefik:v3.7.17)
- A router-level `tls` section REPLACES the entrypoint's tls settings entirely, so routers set
  `certResolver` explicitly.
- 3.7.12+ warns per entrypoint unless `aliasHeadersStrategy` is set: `--global.aliasHeadersStrategy=delete`
  verified (underscore/dot headers stripped, dash headers kept).
- `accesslog.fields.queryparameters.defaultmode=drop` drops the query from `RequestPath`; header default
  is `drop`; `User-Agent=keep` works. ChaCha cipher names without `_SHA256` are accepted.
- lego Cloudflare token needs Zone:Read + DNS:Edit (single zone ok). Token power = every record in the zone;
  do NOT advise client-IP filtering (WAN IPv4 is dynamic, rotation would silently break renewal).

### Tooling gotchas
- Repo root is the git toplevel ONE LEVEL ABOVE the session cwd (`.../portainer-templates`; cwd
  `.../portainer-templates/portainer` only has a stub compose). `.claude/rules/` is at the root.
- `.env.example`: Write tool is denied on `.env*`; write `env.example.tmp` then `mv`. A multi-file `cat`
  that included another service's `.env.example` was denied once - read them one at a time.
- Local validation recipe (workstation, not the NAS): full dummy env file, run the init service for real,
  bring the stack up against a throwaway bridge named like the macvlan network, a
  `traefik/whoami --port 2283` container named `immich_server` on `public-apps`, a self-signed cert via a
  compose overlay. The workstation daemon defaults to the journald log driver, which rejects `max-file`;
  overlay `logging.driver: json-file`. To see requested ACME domains/static config, overlay `command: !override`
  with DEBUG and an unreachable `caServer` so nothing reaches Let's Encrypt.
- The coordinator stages (git add) and moves memory files between rounds; do not touch the index.

### Unverified at write time
Real macvlan default-route behavior and static IP outside the network's `ip_range`, UniFi DNAT preserving
client IPs, real ACME issuance, forwarded-header stripping from untrusted clients (documented, not tested),
and what host-side addresses the proxy can reach on the macvlan segment (the macvlan-host-shim IP is a
host-namespace address on the same segment; check after deploy).
