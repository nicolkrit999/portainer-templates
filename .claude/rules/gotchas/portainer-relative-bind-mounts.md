# Gotcha: relative bind mounts (`./file`) in Portainer git stacks become empty directories

Portainer deploys a git stack by running `docker compose` **inside the
Portainer container**, against the checkout at
`/data/compose/<stack-id>/<stack-dir>/`. On this NAS Portainer's `/data` is the
host directory `/volume2/docker/portainer` (confirmed 2026-11-03 via container
inspect). A relative bind source such as `./conf.php:/srv/cfg/conf.php` is
resolved by the compose CLI to the absolute path `/data/compose/<id>/privatebin/conf.php`
and handed to the **NAS Docker daemon**, which looks for that path on the NAS
itself. It does not exist there, so the daemon auto-creates an EMPTY DIRECTORY at
the source and bind-mounts it. The deploy succeeds, the container starts, and the
app silently runs without its config (or with a directory where its file should be).

**Symptom (2026-11-03):** PrivateBin returned HTTP 500 because `/srv/cfg/conf.php`
was an empty directory. Nothing in the deploy output hinted at it. Fixed in commit
`3aa1303` (stack 237).

**What is affected (compose behaviour, from the cause above; only the `./` bind
mount case was observed failing here):**
- Relative short/long-syntax bind mounts, file or directory. A relative directory
  mount is not "safe": it yields an empty directory instead of the repo's files, so
  the app starts empty. Only acceptable if the intent is fresh writable state, and
  even then an absolute `${DOCKER_CONFIG_DIR}/<svc>/...` path is the repo convention.
- `configs:` / `secrets:` with `file:` in non-Swarm compose are implemented as bind
  mounts of the resolved path, so a relative `file:` hits the same problem. Not used
  with relative sources anywhere in this repo today.

**What is NOT affected (resolved client-side, inside the Portainer container where
the checkout does exist):** `build:` / `build.context` (the CLI uploads the context
to the daemon), `env_file:`, `extends:`, `include:`, inline `configs: content:`.
`icorsi-notes` and `icorsi-sync` use `build: .` / `build: ./auth` and are fine.

## The working pattern

Mount from the checkout's real HOST path, using the stack's own ID:

```yaml
volumes:
  - "${DOCKER_CONFIG_DIR}/portainer/compose/${PORTAINER_STACK_ID:?set PORTAINER_STACK_ID}/<stack-dir>/<file>:/path/in/container:ro"
```

- Live examples: `privatebin/docker-compose.yml` (`conf.php`) and
  `tailscale-admin_traefik-tailnet-forwarder/docker-compose.yml` (watcher's
  `docker-compose.yml`, written with `${VOLUME_CONFIG}` as the root). Both root
  variables are `/volume2/docker` on this NAS; use whichever the stack already has.
  The root MUST be the directory that contains Portainer's `portainer/` data dir.
- `<stack-dir>` is the repo directory name of the compose file (for
  `actual-budget/*` stacks it is the sub-directory name).
- Add `PORTAINER_STACK_ID` to the stack's env in Portainer AND to `.env.example`
  (with a comment saying it is the numeric ID from Portainer, not a constant).
- Keep the `:?` guard. Without it an unset ID expands to `.../compose//<dir>/<file>`,
  which is a missing path, so Docker silently creates the empty directory again.
- The ID changes if the stack is ever deleted and recreated; re-check it then.
- Coupling: this relies on Portainer's internal checkout layout (unversioned).
  If a container fails to start with "no such file" on this path, check that first.
- Single-file bind mounts pin the file's inode. A git update that replaces the file
  (new inode) without recreating the container may leave the container on the old
  content. NOT verified on this NAS; mount the parent directory read-only if a
  config edit ever fails to take effect after a redeploy.

Alternatives that avoid the coupling when the file is small: bake it into an image,
use inline `configs: ... content:`, or have an init container write it into
`${DOCKER_CONFIG_DIR}/<svc>/` (`tailscale-adguard` writes `dnsdist.yml` this way).

## How to apply

- Before adding or reviewing any compose file, run this; the expected result is no
  output (exit 1). Any hit is a bug unless it is a `build:` context:

  ```bash
  rg -n -e '^\s*-\s*["'"'"']?\.{1,2}(/|:)' -e 'source:\s*["'"'"']?\.{1,2}(/|["'"'"']?$)' \
        -e '^\s*(env_file|file):\s*["'"'"']?\.' --glob 'docker-compose.yml' --glob '!.claude/**' .
  ```
- A service that "needs the repo's file" has three options: the pattern above, an
  image/inline `configs`, or a hand-placed host file under `${DOCKER_CONFIG_DIR}/<svc>/`.
- To check a live stack: `docker_proxy` `GET /containers/<name>/json` projecting only
  `Mounts[].{Type,Source,Destination}` (never `Config.Env`); a source starting
  `/data/compose/` means the bug is live. For a suspicious file mount, exec
  `ls -ld <dest>` in the container (first character `d` means the auto-created directory).

## Scan result, 2026-11-03

97 compose files scanned (94 stack dirs plus the 3 `actual-budget/*` sub-stacks; 75
are deployed in Portainer on environment 3).

- Relative bind mounts (short or long), `configs`/`secrets` `file:`, `env_file:`,
  `extends:`, `include:`, and `driver_opts.device`: **none** in the repo. PrivateBin
  was the only one and is already fixed.
- Relative `build:` contexts (safe, listed for completeness): `icorsi-notes` (302)
  `build: .`; `icorsi-sync` (265) `build: .` and `build: ./auth`. Images built and
  containers up and healthy.
- Live NAS: no container has any bind source under `/data/compose/`. Exactly two
  containers mount from the Portainer checkout path, both correctly: `privatebin`
  (stack 237, `conf.php`, 12985 bytes regular file) and `tailscale-admin-watcher`
  (stack 350, `docker-compose.yml`, regular file).
- Same-symptom sweep on absolute single-file mounts (host file missing makes Docker
  create a directory too): 13 file mounts across 12 running containers (traefik,
  traefik-public, traefik-tailnet-forwarder, homehub, tailscale-adguard-dns-relay x2,
  atticd, prometheus, easy-appointments nginx / php-fpm / swagger-ui, plus the two
  above) were checked with `ls -ld`; all are regular files, none is an auto-created
  directory. `Traefik-init` (exited one-shot, `acme.json`) was not checked.
- Not this bug, but the same family: `prometheus/prometheus.yml` and
  `grafana/provisioning/` exist in the repo but the containers read host copies under
  `${VOLUME_CONFIG}/...`, so repo edits do not reach them until the host copy is updated
  by hand. The live `prometheus.yml` is 208 bytes, same size as the repo file (content
  not compared).
- False positives ignored: `PAPERLESS_EMPTY_TRASH_DIR: ../trash` (paperlessngx) and
  `./scripts/self-host-predeploy.js` (affine `command`) are container-internal paths;
  `../adguard/INCIDENT-...` in `tailscale-adguard` is inside a comment in a heredoc.

**Result: no stack is currently running without its config because of this bug.**

Discovered 2026-11-03 (PrivateBin HTTP 500); repo-wide scan the same day.
