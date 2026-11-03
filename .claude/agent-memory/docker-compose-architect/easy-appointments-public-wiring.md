---
name: easy-appointments-public-wiring
description: Non-obvious facts from the 2026-11-03 Batch 2 easy-appointments edit - dev-setup layout, release-zip gaps, PROXY_IPS, php2shell, fixed-.2 IPAM hazard, local test recipe
metadata:
  type: project
---

Edit made 2026-11-03 (uncommitted, nothing deployed); full evidence in `/home/krit/momentary/proxy-research/findings/easy-appointments.md`, runbook in `easy-appointments/README.md`.

- **The live stack was the upstream DEV docker-compose** (git checkout of `main` = 1.5.2+1 commit bind-mounted as the app, nginx `root` = repo root with no deny rules, xdebug `mode=debug`, MySQL/Baikal data inside the same tree). The app version is whatever sits on the volume, not in any image. Rebuilt as: new clean app dir `${DOCKER_CONFIG_DIR}/easyappointments-app` (release zip), php-fpm mounts it `:ro` + `storage/` rw, nginx mounts only `assets/` and serves only `/assets/*` + `/index.php` (everything else rewrites to the app), 444 for unknown Host.
- **The 1.6.1 release zip has no root `config.php` and no `openapi.yml`** (a bind mount of a missing file silently creates a directory); swagger-ui therefore bakes the spec in via `ADD <raw github url>` in its own Dockerfile.
- **1.6.1 reads `PROXY_IPS`** (CodeIgniter `proxy_ips`). Without it all visitors share one rate-limit bucket (100 req/120 s) and 5 failed logins (429) lock everyone out. Peers must be listed as nginx sees Traefik (public /28 + `traefik-proxy` /16). The Host-header reset bug (GHSA-c5rh) is fixed in 1.6.1 via `trusted_site_url()`; BASE_URL did NOT protect <=1.6.0.
- **PHP2Shell (CVE-2026-109618/109619, 2026-10-21)**: unauthenticated RCE, fixed in PHP 8.5.12/8.4.27/8.3.36/8.2.35; php:8.1 (Baikal image) has no patched image. Cloudflare's WAF had rules for it, so dropping the tunnel removes a layer. Every PHP container in the repo needs checking before a direct public path.
- **Fixed proxy address `.2` on a /28 is a boot-order hazard**: Docker gives the lowest free address, so an app container that joins `public-*` first takes `.2` and the holder's fixed-IP attach fails ("Address already in use", reproduced locally). Recommend `ipam.config.ip_range` in the upper half of each public-* network.
- **Local test recipe that worked**: stub external networks (`docker network create --internal --subnet ...`), unzip the release into a scratch tree, `docker compose -p x --env-file ... up -d --build`, install with `docker exec -u www-data php-fpm php index.php console install`, probe from a `curlimages/curl` container on the public network. The dev laptop's default log driver is journald, so `logging.options.max-file` needs a `driver: json-file` override file for local runs only. With `cap_drop: ALL`, root in php-fpm cannot read the 750 www-data storage dir; exec as `-u www-data`.
- MySQL 8.0.46 -> 8.4.13 in-place start rehearsed on a throwaway data dir (works in seconds); not done on the real one. `mysqladmin ping -h 127.0.0.1 --silent` needs no credentials (exit 0 on access denied), which removes the password from the healthcheck config.
