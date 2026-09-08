# tailscale-admin_traefik-tailnet-forwarder

Gives admin-gated services a clean, no-port `hostname:443` URL over Tailscale, with the real client IP preserved end-to-end so Traefik's tailnet-admin IP-allowlist actually works. Three containers, one Portainer stack.

## What it is

- **`tailscale-admin`** - a second, independent Tailscale identity (not the household's primary node in `../tailscale/`), using ordinary (non-host) Docker networking so it gets its own genuinely isolated network namespace.
- **`traefik-tailnet-forwarder`** - an HAProxy TCP-passthrough sidecar that joins `tailscale-admin`'s network namespace (`network_mode: container:tailscale-admin`) and binds `tailscale-admin`'s tailnet IP on ports 443/80, forwarding into Traefik's `tailnet-admin` entrypoint with the PROXY protocol (`send-proxy-v2`).
- **`haproxy-config-init`** - a one-shot init container that writes `haproxy.cfg` to disk the first time it's missing (HAProxy config doesn't support `${VAR}` interpolation, so this substitutes the real values once at first deploy).
- **`tailscale-admin-watcher`** - a self-heal sidecar; see "The residual-risk watcher" below.

## Why this exists (the problem it solves)

Docker's userland-proxy (`docker-proxy`) rewrites a Tailscale-sourced connection's source IP to a Docker bridge gateway address before Traefik ever sees it, on every one of Traefik's published ports. That breaks the `tailnet-admin-only` IP-allowlist middleware (`.claude/rules/networking.md`), which needs the *real* client IP to work at all.

The fix: route tailnet-admin traffic through this dedicated forwarder instead of a published port. The real client IP never touches `docker-proxy`'s NAT - it's preserved via the PROXY protocol, and Traefik's `tailnet-admin` entrypoint (`../traefik/docker-compose.yml`) trusts PROXY headers only from this forwarder's own known static IP.

Tailscale's `tailscale0` interface is a TUN device, not a real L2 NIC, so it can't be macvlan'd the way `../traefik-private-forwarder/`'s LAN-facing sibling is. Instead, `traefik-tailnet-forwarder` gets a namespace to bind into by sharing one with a second, dedicated Tailscale identity (`tailscale-admin`) - see `.claude/rules/core-infra-topology.md` for the full mechanism and how this fits with the other 5 core infra stacks.

## History: two incidents that shaped this file

1. **2026-08-22, `network_mode: host` reverted.** The forwarder originally used `network_mode: host` to reach the Tailscale interface directly. That put it in the same namespace as the host - which is also where Traefik's own `docker-proxy` wildcard-binds `0.0.0.0:443` for the family entrypoint - so the two binds collided. Fixed by giving it its own isolated namespace via `tailscale-admin` instead.
2. **2026-09-08, merged from two stacks into one (see the compose file's own top-of-file comment for the full incident writeup).** `tailscale-admin` and `traefik-tailnet-forwarder` were two independent Portainer git stacks. `traefik-tailnet-forwarder`'s `network_mode: container:tailscale-admin` is a hard runtime coupling - Docker pins `tailscale-admin`'s raw container ID at creation time. Two independent 5-minute auto-poll timers could (and did) recreate `tailscale-admin` without also recreating the forwarder, leaving it bound inside a stale, orphaned network namespace: `haproxy` looked "listening" locally, but the *live* `tailscaled` (now in a fresh namespace) had nothing listening on port 443 in *its* namespace, so real tailnet connections got an instant "Connection refused" - while everything looked healthy. This broke tailnet-admin access to ~50 hostnames for hours before being diagnosed and fixed live, then structurally fixed by merging into this one file/stack.

## The residual-risk watcher

Merging into one stack + setting this stack's Portainer `AutoUpdate.ForceUpdate` to `true` closes the *exact* trigger from the 2026-09-08 incident (a change touching both services in one commit), but **not** a narrower one: Compose only recreates a service whose own config changed, and there's no vanilla-Compose mechanism to cascade-recreate a `network_mode: container:X` dependent when X is recreated for an unrelated reason (e.g. rotating `TS_AUTHKEY_ADMIN` alone). Verified against Portainer's own docs and Docker Compose's documented behavior - see `.claude/rules/core-infra-topology.md`'s "This pair's residual risk" section for the full writeup.

`tailscale-admin-watcher` closes this gap structurally instead of relying on remembering a rule: it watches `docker events` for `tailscale-admin` `start` events, waits `${WATCHER_RESTART_WAIT_TIME}` seconds (lets the identity establish its tailnet connection), then runs `docker compose up -d --force-recreate traefik-tailnet-forwarder` against a read-only mount of this stack's own compose file.

Two off-the-shelf watcher images were evaluated and rejected before building this ourselves:
- `buxxdev/containernetwork-autofix` - hard-requires Unraid plugin host paths that don't exist on this NAS.
- `treyturner/whalewatcher` - no verifiable public source repo, a supply-chain concern for something needing `docker.sock` access.

Built instead as a custom `command:` on the official `docker:27-cli` image - no Dockerfile, same pattern this file already uses for `haproxy-config-init`.

**Security-reviewed before deploy** (`compose-security-auditor` caught two real issues, both fixed in the compose file, not just noted):
- The force-recreate call had no access to this stack's real env vars on its own - it would have deployed `traefik-tailnet-forwarder` with every `${VAR}` blank on every single recreate (this repo's own previously-documented `StackGitRedeploy` env-wipe failure mode, self-inflicted by the fix itself). Fixed: the watcher's own `environment:` block carries a full copy of every var this stack needs, dumped to a real file and passed via `--env-file` at recreate time.
- `$line` and `$WATCHER_RESTART_WAIT_TIME` inside the command string were unescaped, so Compose's own variable-interpolation (which matches bare `$VAR`, not just `${VAR}`) silently ate them as undefined at deploy time instead of letting the container's shell resolve them at runtime. Fixed with `$$` escaping.

Verified live, 2026-09-08: a fresh deploy of this stack restarted `tailscale-admin`, and the watcher automatically detected it and correctly force-recreated `traefik-tailnet-forwarder` in response - captured in its own logs, with a subsequent end-to-end connectivity check confirming the recreated forwarder had the real (not blank) config.

## Environment variables

| Variable | Purpose |
|---|---|
| `TS_AUTHKEY_ADMIN` | Secret - reusable Tailscale pre-auth key for this identity, generated via the Tailscale admin console. |
| `TS_HOSTNAME_ADMIN` | This node's name in the Tailscale admin console (`traefik-admin-gateway`). |
| `TAILSCALE_ADMIN_INTERNAL_IP` | Static Docker-bridge IP on `traefik-proxy` - Traefik's `proxyProtocol.trustedIPs` trusts PROXY headers only from this address. |
| `TAILSCALE_IP` | `tailscale-admin`'s own **tailnet** IP (100.x.x.x) - only known after deploy + approval in the Tailscale admin console. Not the same thing as the Docker-internal IP above. |
| `TRAEFIK_INTERNAL_IP` | Traefik's own static IP on `traefik-proxy` (set in `../traefik/docker-compose.yml`). |
| `TRAEFIK_PORT_7` | Traefik's internal-only `tailnet-admin` entrypoint port. |
| `WATCHER_RESTART_WAIT_TIME` | Seconds the watcher waits after a `tailscale-admin` restart before force-recreating the forwarder (default `15`). |
| `PORTAINER_STACK_ID` | This exact stack's Portainer-assigned numeric ID - **not a fixed constant**, must be re-verified if this stack is ever deleted and recreated. Current live value: `350`. |
| `VOLUME_CONFIG` | Shared fast-storage base path. |

## Deployment gotchas

- **`haproxy.cfg` is write-once.** `haproxy-config-init` only writes it if missing - it will NOT self-correct if `TAILSCALE_IP` (or anything else baked into it) changes later. Delete `${VOLUME_CONFIG}/traefik-tailnet-forwarder/haproxy.cfg` manually before the next redeploy if any of its baked-in values need to change.
- **This stack's Portainer `AutoUpdate.ForceUpdate` must stay `true`.** It's not expressible in this compose file - it's a Portainer stack setting, set directly via the Portainer API/UI.
- **`PORTAINER_STACK_ID` must be re-verified** if this stack is ever deleted and recreated (a new stack gets a new ID) - the watcher's compose-file mount depends on it.
- **`tailscale-admin` needs manual approval** in the Tailscale admin console the first time it's deployed (a new device), same as any new tailnet node.

## Detecting and fixing staleness manually (if the watcher is ever down)

Compare `tailscale-admin`'s `State.StartedAt` against `traefik-tailnet-forwarder`'s - if `tailscale-admin` is newer, the forwarder is stale. Confirm by checking the forwarder's `HostConfig.NetworkMode` (a raw `container:<id>` string) against `tailscale-admin`'s *current* container ID - a mismatch means it's happening right now. Fix: just recreate `traefik-tailnet-forwarder` (`docker compose up -d --force-recreate traefik-tailnet-forwarder`) - its `network_mode` reference re-resolves fresh against whatever `tailscale-admin` container is currently running.
