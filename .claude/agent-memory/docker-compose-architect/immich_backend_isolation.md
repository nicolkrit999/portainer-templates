---
name: immich-backend-isolation
description: immich network layout (internal backend + ML egress net), the multi-network DNS precedence finding, redeploy order, Docker address pool limits
metadata:
  type: project
---

`immich/docker-compose.yml`, backend isolation written 2026-11-03:

- `immich_backend_network` (`immich-backend`, `internal: true`, created by the stack) holds server + ML + redis + db; `immich_ml_egress_network` (`immich-ml-egress`, not internal) is for ML only, which downloads models. `immich-server` additionally joins `traefik-proxy` and `public-apps` (backend network of `traefik-public`) and has `no-new-privileges` (no `cap_drop`: untested with `/dev/dri` + `group_add`). Env/names unchanged: `DB_HOSTNAME=database`, `REDIS_HOSTNAME=immich_redis`, ML URL is the service name.
- Both new networks use Docker's default address pools (192.168.192.0/20 and 192.168.208.0/20 per the subnet registry), not an explicit /28: the pools were nearly exhausted on 2026-11-03 (only 4 free /20 blocks after this change). Check `docker network ls` / the registry before adding another default-pool network.

**DNS precedence on a multi-network container (tested 2026-11-03, docker 29.9.1, when `cloudflare-web` still existed):** a container attached to two networks resolved a name to the holder on the other (shared) network first; a foreign container with `--network-alias database` hijacked the server's `database` lookup 8/8 times. The same hazard exists for `traefik-proxy`, which every stack shares: UNVERIFIED there, but compose gives every service a service-name alias on each network it joins, so another stack's service named `database`/`db`/`redis` on `traefik-proxy` could shadow it. Tested mitigation, not applied: `gw_priority: 100` on the server's `immich_backend_network` entry (backend wins, default route and egress stay put); or `DB_HOSTNAME=immich_postgres` (hijackable only via alias, not container name).
**How to apply:** when a stack with generic backend service names joins a shared network, use unique container names/hostnames or offer `gw_priority`.

**Redeploy behaviour (simulated with stand-ins):** `docker compose up -d` creates both new networks first, then recreates all four containers: db/redis/ML first while the server still runs, then the server. `depends_on` is short form (started, not healthy). A network-creation failure leaves the running stack untouched.

**Image tag:** `IMMICH_VERSION` defaults to `release` in the compose; a Portainer stack variable can pin it. Check the stack's live env before assuming which tag runs.
