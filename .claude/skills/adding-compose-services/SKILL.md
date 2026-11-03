---
name: adding-compose-services
description: Use this skill when the user wants to bring a brand-new service into this Portainer homelab repo. Trigger phrases include 'add <service> to my homelab', 'create a compose for <service>', 'deploy <service>', 'I want to self-host <service>', 'make <service> public'. It researches the service with service-researcher, has docker-compose-architect create the new `<service>/docker-compose.yml` per repo rules (a private router and a tailnet router with bare TLS, `traefik-proxy` plus a per-stack backend network with an explicit /28 from the subnet registry, minimal env, no relative bind mounts), optionally exposes it to strangers ONLY through a router and network in `traefik-public`, runs compose-security-auditor and compose-consistency-linter in parallel, loops fixes back through docker-compose-architect, and closes with the Portainer variable list, the redeploy rule and a reach-test verification. It does NOT cover auditing existing services (use auditing-compose-repo), does NOT cover extracting a stack that already runs in Portainer (use migrating-portainer-stacks) and does NOT cover editing an already-deployed service's compose file (dispatch docker-compose-architect directly).
---

# Adding a Compose Service

Orchestrated in the main chat. You (the orchestrator) dispatch each agent below in
order and loop the review step - agents cannot call each other.

## The model in one paragraph

There is no Cloudflare Tunnel, no family/guest/friends tier, no SAN certificate group
and no per-service DNS entry any more. A new service needs: a `<svc>-private` router
(entrypoint `${TRAEFIK_ENTRYPOINT_3}`) and a `<svc>-tailnet` router
(`${TRAEFIK_ENTRYPOINT_7}`), both with bare `tls: "true"` (the single wildcard
certificate comes from the `traefik-dashboard` router), `traefik-proxy` attached, and,
for multi-container stacks, one `<stack>-backend` network with an explicit /28. Both
dnsmasq instances are wildcard-only, so the name resolves on LAN and tailnet by itself.
Only if strangers must reach it: an additive router, service and `public-<app>` network
in `traefik-public`. Details: `.claude/rules/networking.md`,
`.claude/rules/core-infra-topology.md`, `traefik-public/README.md`.

## Agent loop

1. **RESEARCH** - dispatch `service-researcher` with the service name AND the
   objective (private only, or also public? what does it depend on - a database,
   another stack already in the repo? does it need egress, a non-HTTP port?).
   Pass the *why*, not a bare service name. It returns a compact spec (image, env
   vars, volumes, ports, healthcheck, and for a public app the proxy/unauthenticated-path
   notes) and writes no files.

2. **DECIDE** (you, with the user - ask only what the objective does not answer):
   - Public access? Default **no** (private + tailnet only, no question needed). If
     yes, the app additionally goes through `traefik-public` (step 4).
   - Volume paths: the architect proposes `${VOLUME_CONFIG}/<svc>/...` and
     `${VOLUME_DATA}/<svc>/...`; confirm them with the user.
   - Multi-container stack? Then a /28 is needed. Check the "Next free" line of
     `/home/krit/momentary/proxy-research/findings/subnets.md` and have it recorded
     there BEFORE the compose is written (append-only registry; the architect does the
     append). A public app needs a second /28 for its `public-<app>` network.

3. **BUILD** - dispatch `docker-compose-architect` with the spec and the decisions. It
   creates `<service>/docker-compose.yml` following `.claude/rules/`:
   - two routers (`<svc>-private`, `<svc>-tailnet`), same `Host()` on
     `${<SERVICE>_SUBDOMAIN}.${DOMAIN}`, same explicit `service:`, `hsts-headers@docker`
     first in every `middlewares`, `tailnet-admin-only@docker` on the tailnet one, bare
     `tls: "true"` - **no** `tls.certresolver`, **no** `tls.domains`;
   - `traefik_proxy_network` (`traefik-proxy`, external) on the routed container and
     `traefik.docker.network: "traefik-proxy"`; databases and helpers on the
     `<stack>-backend` network (`internal: true` unless a member needs egress or publishes
     a port; gateway `.1`, `ip_range` `.8/29`, subnet/gateway/ip_range overridable via
     `${<STACK>_BACKEND_*}`);
   - parameterized volumes, `${ADMIN_USER}`/`${PUID}`/`${PGID}`, `TZ: "${TZ}"`, all
     `environment:` values quoted, `container_name`, `restart`, healthchecks;
   - **no relative bind mounts** (config files: env vars, inline config, or a hand-placed
     host path; see `.claude/rules/gotchas/portainer-relative-bind-mounts.md`);
   - **`<service>/.env.example` listing exactly the `${VAR}`s the compose references**
     (real placeholder/default, secrets obviously fake, nothing unreferenced).
   If the service uses `network_mode: host`, the Traefik backend target is
   `loadbalancer.server.url: "http://host.docker.internal:<port>"`, never `${NAS_IP}`.
   A host port is only published on explicit request (it bypasses Traefik); check
   `.claude/rules/service-directory.md` for collisions first.

4. **PUBLIC EXPOSURE (only if requested)** - dispatch `docker-compose-architect` again
   with `traefik-public/README.md` and the research notes. It adds, in
   `traefik-public/docker-compose.yml` and its `.env.example`: the router/service for
   `${<APP>_SUBDOMAIN}.${DOMAIN}`, the `public-<app>` network (explicit /28, proxy at
   `.2`, backend `ip_range` `.8/29`, `internal: true`), any path exclusions and
   rate limits the app needs, and the right header profile; and in the app's compose
   the `external: true` attachment plus the trusted-proxy setting for that /28.
   Never a router on the core Traefik, never a new WAN port. The user then performs the
   one manual step: a DNS-only (grey cloud) CNAME for the hostname to the WAN DDNS name
   (`wg.${DOMAIN}` on this instance). Deploy order: `traefik-public` (to create the
   network) before the app.

5. **REVIEW** - dispatch `compose-security-auditor` and `compose-consistency-linter`
   in parallel on the new file (and on `traefik-public/docker-compose.yml` if step 4 ran).
   Both are read-only and never edit.

6. **FIX** - send any findings from either reviewer back to `docker-compose-architect`
   as an exact list (file, finding, required fix). Re-run only the reviewer(s) that had
   findings, scoped to the new service.

7. Repeat steps 5→6 up to 3 cycles total. If findings remain after cycle 3, stop looping
   and report the residual findings to the user instead of continuing to iterate.

8. **HANDOFF** - the user deploys; close by stating:
   - the full list of `${VAR}`s to set in the new Portainer stack: the new
     `${<SERVICE>_SUBDOMAIN}` with its value (default: the directory name), secrets,
     `<STACK>_BACKEND_*` only if overriding, and the shared repo-wide vars the compose
     references (`DOMAIN`, `TRAEFIK_ENTRYPOINT_3`, `TRAEFIK_ENTRYPOINT_7`, `TZ`, volume
     roots, `PUID`/`PGID`). The stack env must hold only variables the compose
     references. For `traefik-public`, name the new variables to add to ITS stack env;
   - the redeploy rule: any `StackGitRedeploy` (and the `traefik-public` redeploy) needs
     `StackInspect` first and the full current `Env` passed back, every time
     (`.claude/rules/portainer-instance.md`); never print secret values;
   - the verification, and run it once the stack is up:
     `/home/krit/momentary/proxy-research/tools/reach-test.sh <hostfile> tailnet` and
     `... lan` with the new subdomain in the hostfile (one per line). `OK` on both is the
     pass criterion; `NOROUTE` = a router is missing on that path, `CERT` = the router
     carries its own certificate labels or the wildcard is not issued, `5xx`/`DOWN` = the
     backend or its network is wrong. For a public app also test through the forward from
     outside the LAN, e.g. `curl --resolve <host>:443:<WAN-IP>` via an exit node in an
     allowed region, and check the access log of `traefik-public`;
   - a reminder to sanity-check that `TAILNET_ADMIN_IPS` (on the `traefik` stack) still
     covers the owner devices that need the tailnet path;
   - that `.claude/rules/service-directory.md` should list the new service (hostname,
     deployed, direct port if any) and that the subnet registry now contains the
     allocation(s).

## Exit condition

Both reviewers report clean, or the user has explicitly accepted residual findings after
3 fix cycles - AND `.env.example` matches the compose in both directions - AND any /28
allocation is recorded in the subnet registry - AND the handoff (variables, redeploy rule,
reach-test commands, and for a public app the CNAME step) has been delivered. The task
is not done on a clean compose file alone.

## Out of scope

- Auditing or linting services that already exist in the repo, or a repo-wide sweep -
  that is `auditing-compose-repo`.
- Bringing a stack that only exists live in Portainer under git - that is
  `migrating-portainer-stacks`.
- Editing an existing, already-deployed service's compose file with no new service being
  added - dispatch `docker-compose-architect` directly, no research/review loop needed
  unless the user asks for one.
