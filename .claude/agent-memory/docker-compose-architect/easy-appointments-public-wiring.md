---
name: easy-appointments-public-wiring
description: Non-obvious facts about the Easy!Appointments stack - release-zip gaps, PROXY_IPS, PHP2Shell, CodeIgniter query-route bypass, local test recipe
metadata:
  type: project
---

Stack layout, data paths and runbook: `easy-appointments/README.md`; evidence: `/home/krit/momentary/proxy-research/findings/easy-appointments.md`.

- **History (2026-11-03):** the stack used to run the upstream DEV compose (git checkout bind-mounted as the app, xdebug on). It now runs the 1.6.1 release zip in `${DOCKER_CONFIG_DIR}/easyappointments-app`: php-fpm mounts it `:ro` plus `storage/` rw, nginx serves only `/assets/*` and `/index.php` (everything else rewrites to the app) and answers 444 for unknown Host. MySQL is `mysql:8.4.13` at `${DOCKER_CONFIG_DIR}/easyappointments-mysql` (bind with `create_host_path: false`, upgraded in place from 8.0.46 on 2026-11-04).
- **The 1.6.1 release zip has no root `config.php` and no `openapi.yml`.** A bind mount of a missing file silently creates a directory, so swagger-ui bakes the spec in with `ADD <raw github url>` in its Dockerfile.
- **`PROXY_IPS`** (CodeIgniter `proxy_ips`) must list the peers as nginx sees them: the `public-easy-appointments` /28 and the `traefik-proxy` /16 (compose default does). Without it all visitors share one rate-limit bucket (100 req/120 s) and 5 failed logins (429) lock everyone out. The Host-header reset bug (GHSA-c5rh) is fixed in 1.6.1 via `trusted_site_url()`; BASE_URL did NOT protect <= 1.6.0.
- **Query-string routing:** CodeIgniter also routes from a query starting with `/` (`/?/api/v1/...`), which a Traefik path rule cannot see; the nginx vhost refuses `$args ~ "^/"`. `index.php/api_settings` is a staff admin page: block `/api` by whole segments in `traefik-public`, not by prefix.
- **PHP2Shell (CVE-2026-109618/109619, 2026-10-21):** unauthenticated RCE, fixed in PHP 8.5.12 / 8.4.27 / 8.3.36 / 8.2.35. The php-fpm image is built on 8.4.27. Any PHP container exposed through `traefik-public` needs this checked; nothing in front filters it any more.
- **Healthcheck:** `mysqladmin ping -h 127.0.0.1 --silent` needs no credentials (exit 0 even on access denied), so no password sits in the healthcheck config.
- **Local test recipe** (generic parts: `reference_public-proxy-batch-lessons.md`): unzip the release into a scratch tree, `docker compose -p x --env-file ... up -d --build`, install with `docker exec -u www-data php-fpm php index.php console install` (with `cap_drop: ALL`, root cannot read the 750 www-data storage dir), probe from a `curlimages/curl` container on the public network.
- The fixed-proxy-`.2` boot-order hazard and the `ip_range` fix are in [[public-proxy-batch-lessons]] (the `public-easy-appointments` network already has `ip_range`).

**Why:** release-zip and CodeIgniter quirks are invisible in the compose file.
**How to apply:** read this before upgrading Easy!Appointments or touching its nginx/php-fpm/proxy rules.
