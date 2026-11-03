---
name: batch2-opencloud-trek-hi-events-public-wiring
description: Non-obvious app-side facts for OpenCloud, TREK and Hi.Events behind traefik-public - who sets headers, root entrypoint, auto-migrations, basic auth vs app tokens
metadata:
  type: project
---

History: written 2026-11-03 during public Batch 2; per-service evidence lives in `/home/krit/momentary/proxy-research/findings/`. Proxy side (header profiles, networks, routers) is in `traefik-public/README.md`.

- **OpenCloud** (tag default `8.0.1` in the compose; bumping is a separate decision): the app's own proxy sends CSP (`frame-ancestors 'self'`), `X-Frame-Options: SAMEORIGIN` and referrer policy, so it uses `public-secure-headers-app-framing` in `traefik-public` (no `frameDeny`). `PROXY_ENABLE_BASIC_AUTH` is upstream "tests/dev only" and stays `false`; WebDAV clients that cannot do OIDC use per-user app tokens (`auth-app`, on by default) as the Basic password. The repo's `csp.yaml` is MERGED into the upstream default. The init container fixes ownership with `find ! -user/-group -exec chown -h` (not `chown -R` over ~212k entries) under `cap_drop: ALL` + CHOWN + DAC_OVERRIDE (DAC_OVERRIDE is needed: dirs are 700/755 owned by the app uid).
- **TREK** (`mauriceboe/trek`, pinned tag in the compose): the entrypoint chowns data then `gosu node`, so it MUST start as root (`user: "0:0"` with CHOWN/SETUID/SETGID/KILL); `read_only`, tmpfs and `no-new-privileges` were tested with the real image. Registration has no env switch (admin UI `password_registration`, default On, or `OIDC_ONLY`). Required path variables use `${VAR:?msg}`: an unset plain `${VAR}` silently binds an empty path and the app would boot on a fresh empty DB. TREK loads map tiles cross-origin, hence `strict-origin-when-cross-origin` in the app-framing profile. Behind the proxy it needs `TRUST_PROXY: "1"`.
- **Hi.Events** (see [[hi-events-service]] for the stack layout): `/startup.sh` runs `php artisan migrate --force` on EVERY start, so any tag bump auto-migrates; back up first. The Alpine image's www-data is uid 82. `APP_TRUSTED_PROXIES` is an explicit CIDR list (the `traefik-proxy` /16 plus the `public-hi-events` /28), never `*`. It ships an embeddable iframe widget, which a global `frameDeny` would break (the public router currently uses the default profile: UNVERIFIED whether the widget is used publicly). Security-critical "closed" flags (`APP_DISABLE_REGISTRATION`) are hardcoded in the compose, not read from a variable, because a stale Portainer value once overrode them.

**Why:** these are the facts a future upgrade session would otherwise have to rediscover.
**How to apply:** before bumping any of the three images, re-read the findings entries and take a backup; before editing proxy-side headers, use the per-app header table in `findings/cross-cutting.md` and `traefik-public/README.md`.
