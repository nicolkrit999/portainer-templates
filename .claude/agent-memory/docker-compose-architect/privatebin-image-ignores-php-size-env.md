---
name: privatebin-image-ignores-php-size-env
description: privatebin/nginx-fpm-alpine does not read PHP_POST_MAX_SIZE / PHP_UPLOAD_MAX_FILESIZE; hard caps are 15M; purge-on-create works without cron
metadata:
  type: reference
---

The `privatebin/nginx-fpm-alpine` image (verified at image-repo tag `2.1.0-alpine3.24`, 2026-11-03) never reads `PHP_POST_MAX_SIZE` or `PHP_UPLOAD_MAX_FILESIZE`: `etc/php/conf.d/00-docker.ini` hardcodes `upload_max_filesize=15M` / `post_max_size=15M`, `etc/nginx/nginx.conf` has `client_max_body_size 15M`, php-fpm runs `clear_env = On`. The old `10G` env values in `privatebin/docker-compose.yml` were dead and are removed. The real size control is `sizelimit` in `privatebin/conf.php` (currently 1 MiB, `fileupload = false`); a lower hard cap needs a mounted php/nginx ini file.

Only `TZ` and `PHP_TZ` are documented timezone env vars, and the README warns that changing the PHP timezone shifts existing paste expiry. Do not add `TZ: "${TZ}"` reflexively to privatebin (the compose has none).

**Why:** the repo convention says add `${TZ}` to every service and "lower the limits" sounds like an env job; both are wrong for this image.

**How to apply:** to change PrivateBin size limits or timezone, edit `conf.php` (`sizelimit`) or mount ini files, not env vars. Purge of expired pastes runs on paste creation (`[purge] limit`/`batchsize`, verified locally 2026-11-03), so no cron/Ofelia/docker.sock sidecar is needed. Tag trap: Docker Hub tag `2.1.0` corresponds to image-repo git tag `2.1.0-alpine3.24`, not `2.1.0`.

See [[privatebin_service]] for the rest of the stack's lessons.
