---
name: immich-backend-isolation
description: immich backend network isolation (2026-11-03, uncommitted at write time) - what changed, the cross-network DNS precedence finding, live facts about the stack and the NAS Docker address pools
metadata:
  type: project
---

> **2026-11-03: superseded in part. `cloudflare-web` was deleted, so the cross-network DNS precedence hazard between `cloudflare-web` and `immich-backend` no longer applies and the `gw_priority` mitigation is moot; `immich-server` now sits on `traefik-proxy`, `public-apps` (for `traefik-public`) and `immich-backend`. The backend isolation design and the redeploy-order notes remain accurate.**

## immich/docker-compose.yml: backend isolation (written 2026-11-03, coordinator reviews/pushes)

Added `immich_backend_network` (`immich-backend`, internal, created by the stack) for server+ML+redis+db,
and `immich_ml_egress_network` (`immich-ml-egress`, non-internal) for ML only. db/redis/ML left
`cloudflare-web`; server keeps cloudflare-web, traefik-proxy, public-apps and gets
`security_opt: ["no-new-privileges:true"]` (no cap_drop: untested with /dev/dri + group_add).
Env/names unchanged: DB_HOSTNAME=database, REDIS_HOSTNAME=immich_redis, ML URL is the service name.

### Finding: DNS precedence for a container on several networks
A container attached to BOTH cloudflare-web and immich-backend resolves a name to the cloudflare-web
holder first. A foreign container with `--network-alias database` on cloudflare-web hijacked the
server's `database` lookup in 8/8 tries (docker 29.9.1 local test). Live check 2026-11-03: no such alias
exists today (only immich_postgres has service `database`; `db`/`redis` service names exist in other stacks,
immich uses the unique container name `immich_redis`). Tested mitigation, NOT applied:
`gw_priority: 100` on the server's immich_backend_network entry -> backend wins, default route and egress
stay on cloudflare-web. Needs NAS validation (engine 29.6.2 supports gw_priority).
**How to apply:** if a future stack adds a service named `database` to cloudflare-web, or the coordinator asks
how to harden name resolution, offer gw_priority (or DB_HOSTNAME=immich_postgres, which is hijackable only
via alias, not container name).

### Redeploy behaviour (simulated with stand-ins, volumes stripped)
`docker compose up -d` created both networks first, then recreated ALL four containers (new IDs). Order:
db/redis/ML stopped+recreated first while the server still ran, then the server; start order ML, redis,
postgres, server. depends_on is short form (started, not healthy). Networks are created before any
container is touched, so a network-creation failure leaves the running stack untouched.

### Live facts (read-only Portainer queries, env 3)
- Immich stack id 227 tracks refs/heads/main, AutoUpdate every 5m, ForceUpdate=false, ForcePullImage=false,
  has a webhook (do not call it by accident).
- Docker 29.6.2, DefaultAddressPools null (defaults): 192.168.x/20 blocks used up to 192.168.176.0/20
  (public-apps); only 4 free /20 blocks left (192.168.192/208/224/240) -> this change uses 2.
- Live server/ML still run tags `:release` / `:release-openvino`; both image labels say v3.3.5, so the
  IMMICH_VERSION=v3.3.5 pin (saved on the stack at 12:07Z, after the last server recreation at 11:24Z) is the
  same code but a different tag string -> the next deploy pulls the v3.3.5 tags.
- Uptime Kuma is on cloudflare-web: its monitors (app DB, not in repo) could target immich backend names.
