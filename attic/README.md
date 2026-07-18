# attic

A self-hosted [Nix binary cache](https://github.com/zhaofengli/attic) server. Postgres-backed
(not SQLite - see below).

---

## The one thing you'll edit: `config/server.toml`

`atticd` reads its configuration from a file bind-mounted read-only into the container
(`${DOCKER_CONFIG_DIR}/attic/config/server.toml`). Docker Compose only substitutes `${VAR}`
values inside `docker-compose.yml` itself - it never templates the contents of a mounted
file - so this file can't be parameterized the way `.env` is. It also can't be baked into a
custom image, since this repo has no build step.

That means `config/server.toml.example` in this repo is a **template, not a ready-to-run
file**. Before first deploy:

1. Copy it to `${DOCKER_CONFIG_DIR}/attic/config/server.toml` on your host (the exact path
   your `DOCKER_CONFIG_DIR` resolves to - see your `.env`).
2. Edit the placeholder(s) below for your setup.
3. Redeploy the stack.

Any future edit to this file has to go through the same copy + redeploy cycle - it's not
watched or live-reloaded.

### What to decide

- **`api-endpoint`** (required) - the URL your Nix clients will actually use to reach this
  cache when pushing/pulling. It has to match how you're exposing the service:
  - Reachable directly on your LAN → `http://<nas-hostname-or-ip>:8081/` (`8081` is this
    compose's published port; change it if you changed the port mapping).
  - Behind a reverse proxy or tunnel → the public URL that proxy answers on instead.
  - Must end with a trailing slash, or clients will get bad URLs back in cache-config
    responses.
- **`allowed-hosts`** (optional hardening) - which `Host` headers `atticd` will accept.
  `[]` (the default here, matching attic's own upstream default) accepts any `Host` header.
  For production, attic's own docs recommend locking this down to the hostname(s) from
  `api-endpoint`, e.g. `["your-nas-hostname"]`.

### What you don't need to touch

- `[database]` - the connection URL is supplied via the `ATTIC_SERVER_DATABASE_URL` env var
  in `docker-compose.yml` (built from `${ATTIC_DB_PASSWORD}`), specifically so the Postgres
  password never has to live in this file. Leave the `url =` line commented out.
- `[jwt]` - the signing secret is supplied via `ATTIC_SERVER_TOKEN_RS256_SECRET_BASE64`, same
  reasoning. Nothing to set here.
- `[storage]`, `[chunking]`, `[compression]`, `[garbage-collection]` - in-container paths and
  tuning defaults that work as shipped. If you do change `[chunking]` later, note attic's own
  warning: it invalidates dedup for existing NARs until the cache warms back up.

---

## Why Postgres, not SQLite

`atticd` hardcodes `pragma journal_mode=WAL` and a large `mmap_size` for every SQLite
connection, with no config option to disable it. On some host filesystems this makes SQLite's
WAL shared-memory file intermittently fail to `mmap()`, surfacing as
`SQLITE_IOERR_SHMMAP` (`disk I/O error`, SQLite result code 6410) and 500s on push/pull.
Postgres sidesteps this class of failure entirely, and it's what attic's own
`config-template.toml` recommends for production use anyway.
