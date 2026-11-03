---
name: tailscale-admin-traefik-tailnet-forwarder-service
description: tailnet-admin gateway stack (tailscale-admin + HAProxy forwarder + config-init + watcher) - build lessons only; topology and the residual-risk story live in core-infra-topology.md and the stack README
metadata:
  type: project
---

`tailscale-admin_traefik-tailnet-forwarder/` is the tailnet path: `dnsmasq-tailnet` answers every `*.${DOMAIN}` name with the gateway's tailnet IP (`${TAILSCALE_IP}`, currently `100.83.124.109`), HAProxy forwards to Traefik entrypoint 7 with the PROXY protocol. What it is, why it exists, the merge incident and the watcher rationale are written once in `.claude/rules/core-infra-topology.md` and the stack's `README.md`; do not restate them here. Lessons that matter when editing the compose:

**Services:** `tailscale-admin` (second Tailscale identity, `restart: always`, `cpu_shares: 4096`), `haproxy-config-init` (alpine one-shot), `traefik-tailnet-forwarder` (`haproxy:alpine`, `network_mode: "container:tailscale-admin"`, `restart: always`), `tailscale-admin-watcher` (`docker:27-cli`, `restart: unless-stopped`, no healthcheck, not in any `depends_on`).

**Tailscale sidecar pattern (non-host):** `cap_add: [NET_ADMIN, SYS_MODULE]` and `devices: ["/dev/net/tun:/dev/net/tun"]` only (no extra `volumes:` entry for the TUN device; the host-mode primary node in `tailscale/` is the one that bind-mounts it, do not copy that across). It advertises no routes. Only network: `traefik-proxy` with static `${TAILSCALE_ADMIN_INTERNAL_IP}`; no router labels.

**Binding :443 without root or caps:** `sysctls: net.ipv4.ip_unprivileged_port_start: "0"` on `tailscale-admin` is namespace-scoped and lets the non-root HAProxy that shares the namespace bind 443. `cap_add: NET_BIND_SERVICE` did not survive `haproxy:alpine`'s su-exec user drop (confirmed live) and `user: "0:0"` failed security review.

**HAProxy config:** HAProxy cannot interpolate `${VAR}`, so `haproxy-config-init` rewrites `${VOLUME_CONFIG}/traefik-tailnet-forwarder/haproxy.cfg` on every deploy with real values; HAProxy re-reads it only when its container restarts, so a config-only change needs that container restarted. The :443 backend uses `send-proxy-v2` to `${TRAEFIK_INTERNAL_IP}:${TRAEFIK_PORT_7}`; the :80 pair is plain passthrough. The healthcheck is `haproxy -c -f ...` (syntax only, the alpine image has no reliable nc/curl).

**Traefik side (in `traefik/`):** entrypoint 7 (`tailnet-admin`, 8446, not host-published) with `proxyProtocol.trustedIPs=${TAILSCALE_ADMIN_INTERNAL_IP}/32`; Traefik itself has a static `${TRAEFIK_INTERNAL_IP}` on `traefik-proxy` (explicit `ipam` subnet needed for that). On routers the middleware order stays `hsts-headers@docker` first, then `tailnet-admin-only@docker` (reordering hit this repo twice).

**IP trap:** `TAILSCALE_IP` is `tailscale-admin`'s own tailnet address (`100.83.124.109`), NOT the NAS primary node's (`100.101.189.91`, used for `gitea-ssh` on the tailnet). An older `.env.example` carried the NAS value, left over from the reverted `network_mode: host` design.

**Watcher:** `docker events --filter event=start --filter container=tailscale-admin` feeds a loop that sleeps `${WATCHER_RESTART_WAIT_TIME}` (15) and runs `docker compose -p tailscale-admin_traefik-tailnet-forwarder up -d --force-recreate traefik-tailnet-forwarder` against a read-only mount of this stack's own compose file at `${VOLUME_CONFIG}/portainer/compose/${PORTAINER_STACK_ID}/tailscale-admin_traefik-tailnet-forwarder/docker-compose.yml` (`PORTAINER_STACK_ID` is 350 now; re-check if the stack is ever recreated). Two traps found by the security audit: (1) the mounted file has no `.env` beside it, so EVERY `${VAR}` of the stack must also be set in the watcher's own `environment:` (the command dumps it to `--env-file`), otherwise each recreate deploys blanks. **When you add a variable to this stack, add it to the watcher's `environment:` too.** (2) Shell variables inside the `command:` string need `$$`, because Compose eats bare `$VAR`. `docker.sock` is read-write on purpose (it issues `up`).
