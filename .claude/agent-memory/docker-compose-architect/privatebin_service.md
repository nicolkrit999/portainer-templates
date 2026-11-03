---
name: privatebin-service
description: privatebin HTTP 500 root cause (relative bind mount under Portainer), the /run tmpfs fix, image-tag facts (latest = nightly), first-load config behaviour - 2026-11-03
metadata:
  type: project
---

## privatebin/docker-compose.yml fix (2026-11-03, uncommitted at write time)

**Root cause of the 500:** Portainer runs `docker compose` INSIDE its own container (its /data = host
/volume2/docker/portainer), so a relative `./conf.php` resolved to the container path `/data/compose/237/privatebin/conf.php`,
which the daemon treats as a HOST path on the NAS root FS. It does not exist there, so Docker auto-created an empty root-owned
DIRECTORY on 8 Sep (nothing to do with git; the checkout itself has conf.php as a regular file - verified via
`GET /containers/portainer/archive?path=...`). The relative mount NEVER delivered the config. Newer PrivateBin (2.1.0 nightly
on PHP 8.5) turned the resulting `parse_ini_file(dir)` into a TypeError -> 500; older images tolerated it.
**Renaming the file would NOT have helped** (a missing source path always becomes a directory, whatever the name).

**Fix:** mount the checkout by its real host path, repo precedent in tailscale-admin_traefik-tailnet-forwarder:
`"${DOCKER_CONFIG_DIR}/portainer/compose/${PORTAINER_STACK_ID:?set PORTAINER_STACK_ID}/privatebin/conf.php:/srv/cfg/conf.php:ro"`
(DOCKER_CONFIG_DIR=/volume2/docker on this NAS; stack id 237). The user must add PORTAINER_STACK_ID=237 to the stack env first.
privatebin was the only compose in the repo using a `./` bind mount (grep 2026-11-03); never use `./` file mounts with Portainer here.

**/run:** the image's rc.local does `cp -r /etc/s6/services /run` which MERGES into an existing /run/services, so a persistent
/run keeps removed services (php-fpm84) alive after an image upgrade. Now `tmpfs: ["/run:exec,uid=${PUID},gid=${PGID},mode=0755,size=16m"]`.
**Docker tmpfs defaults to noexec** - without `exec` s6 fails with "unable to spawn ./run: Permission denied" (tested). /tmp and
/var/lib/nginx/tmp stay on the bind mount (nginx client_body buffering of 10G POSTs needs disk).

**Image tags (Docker Hub, 2026-11-03):** `latest` == `nightly` (same digest, built daily); `stable` == `2.1.0` (21 Oct). The live
container ran today's NIGHTLY (image id sha256:45af93...) while its label said 2.1.0. Exact tags exist: 2.1.0, 2.1.0-alpine3.24,
2.1.0-alpine3.24-php8.5.12; no floating 2 / 2.1 tags seen. 2.1.0 index digest sha256:0f80fb240c3c3073c53a82893da7c7d62f03f4e05403855b720e4371541ba412.
Stable 2.1.0 tested working with the same user/mounts/tmpfs and reads pastes made by the nightly image. Recommended pinning to 2.1.0.

**First-load config effects** (conf.php was probably never applied since 8 Sep): fileupload=true (default off), sizelimit 10 GB
(default 10 MB), template + language selection menus, traffic header CF-Connecting-IP (spoofable when the request did not come
through Cloudflare; on the private/tailnet paths the header is absent so the limiter keys on the proxy address = one shared bucket).
Pre-existing gap: TZ is used by the ofelia service but is neither in .env.example nor the live stack env.

**Local test recipe:** real compose with `up -d privatebin` (skips ofelia), stand-in external networks, DOCKER_CONFIG_DIR pointing
at a scratch tree that mimics `<dir>/portainer/compose/<id>/privatebin/conf.php`, data/tmp dirs chowned 1000:10 via a root helper
container; API paste = POST / with X-Requested-With: JSONHttpRequest, v2 adata [[iv<=24ch, salt<=14ch, >10000, 256, 128, "aes", "gcm", "none"], "plaintext", 0, 0],
meta.expire, random (incompressible) base64 ct; mind the 10 s per-IP posting limit between creates.
