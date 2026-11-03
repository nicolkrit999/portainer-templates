---
name: privatebin-service
description: PrivateBin lessons - /run tmpfs needs exec, image tags (latest = nightly, pinned 2.1.0), conf.php behaviour; the relative-mount 500 lives in the gotcha file
metadata:
  type: project
---

`privatebin/docker-compose.yml`: pinned `privatebin/nginx-fpm-alpine:2.1.0`, `user: ${PUID}:${PGID}`, routers `privatebin` + `privatebin-tailnet` on `traefik-proxy`, plus the external `public-privatebin` network (it is one of the `traefik-public` backends; deploy `traefik-public` first).

**The 2026-11-03 HTTP 500** (relative `./conf.php` mount became an empty directory under Portainer) is documented once in `.claude/rules/gotchas/portainer-relative-bind-mounts.md`. The compose mounts `conf.php` from the checkout's real host path with `${PORTAINER_STACK_ID:?...}` (stack 237); `PORTAINER_STACK_ID` must be in the stack env. Renaming the file never helps (a missing source always becomes a directory). Newer PrivateBin turned `parse_ini_file(dir)` into a TypeError, which is why it surfaced only after an image update.

**`/run` must start empty:** the image's `rc.local` does `cp -r /etc/s6/services /run`, which MERGES into an existing `/run/services`, so a persistent `/run` kept a removed service (php-fpm84) alive after an image upgrade. Hence `tmpfs: ["/run:exec,uid=${PUID},gid=${PGID},mode=0755,size=16m"]`. Docker tmpfs defaults to `noexec`; without `exec` s6 fails with "unable to spawn ./run: Permission denied" (tested). `/tmp` and `/var/lib/nginx/tmp` stay on the bind mount (large POST buffering needs disk).

**Image tags (Docker Hub, checked 2026-11-03):** `latest` == `nightly` (same digest, built daily); `stable` == `2.1.0`. The live container had been running a nightly while its label said 2.1.0, so pin the exact tag (`2.1.0`; no floating `2`/`2.1` tags seen). Stable 2.1.0 reads pastes made by the nightly image.

**`conf.php` is applied now:** `fileupload = false`, `sizelimit = 1048576`, traffic `header = "X_FORWARDED_FOR"`. On the public path `traefik-public` sets `X-Forwarded-For` to the real peer, so the limiter keys per client; on LAN/tailnet paths it keys on the proxy side. See [[privatebin-image-ignores-php-size-env]] for why limits are not env vars.

**Local test recipe:** real compose with `up -d privatebin`, stand-in external networks, `DOCKER_CONFIG_DIR` pointing at a scratch tree that mimics `<dir>/portainer/compose/<id>/privatebin/conf.php`, data/tmp dirs chowned to the container uid. API paste = `POST /` with `X-Requested-With: JSONHttpRequest`, v2 `adata`, `meta.expire`, random base64 ciphertext; mind the per-IP posting limit between creates.
