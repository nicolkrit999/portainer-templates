---
name: adding-compose-services
description: Use this skill when the user wants to bring a brand-new service into this Portainer homelab repo. Trigger phrases include 'add <service> to my homelab', 'set up <service> behind the tunnel', 'create a compose for <service>', 'deploy <service>', 'I want to self-host <service>'. It researches the service, has docker-compose-architect create the new `<service>/docker-compose.yml` per repo rules - Cloudflare Tunnel AND a private-tier Traefik router by default, plus family/guest/friends tiers if the user asks for them - adds the matching `dnsmasq` private-tier DNS override (required for every service, not optional, so the private-tier URL actually resolves to Traefik), runs compose-security-auditor and compose-consistency-linter in parallel, loops fixes back through docker-compose-architect, and hands off the Cloudflare Tunnel target plus the full list of `${VAR}`s to set in Portainer. It does NOT cover auditing or linting services that already exist across the repo (use auditing-compose-repo for that) and it does NOT cover editing an already-deployed service's compose file (dispatch docker-compose-architect directly for that).
---

# Adding a Compose Service

Orchestrated in the main chat. You (the orchestrator) dispatch each agent below in
order and loop the review step - agents cannot call each other.

## Agent loop

1. **RESEARCH** - dispatch `service-researcher` with the service name AND the
   objective (does it need external/Cloudflare access? what does it depend on -
   a database, another service already in the repo, etc.?). Pass the *why*, not
   a bare service name. It returns a compact spec (image, env vars, volumes,
   ports, healthcheck) and writes no files.

2. **BUILD** - dispatch `docker-compose-architect` with that spec. It creates
   `<service>/docker-compose.yml` following `.claude/rules/` (parameterized
   `${VOLUME_CONFIG}`/`${VOLUME_DATA}` volumes, `${ADMIN_USER}`/`${PUID}`/`${PGID}`
   quoted, `<svc>.${DOMAIN}` hostname, `TZ: "${TZ}"`), proposes the
   `${VOLUME_CONFIG}`/`${VOLUME_DATA}` subpaths and confirms them with the user,
   and lists every `${VAR}` that must be set in Portainer.

   It attaches both `cloudflare_web_network` and the Traefik network by
   default, with a `private`-tier-only router - this is automatic, not
   something to ask about. The one thing you must ask the user and relay
   into this dispatch explicitly: **does this service also need `family`,
   `guest`, and/or `friends` tier access?** docker-compose-architect can't
   infer that from the service name alone - pass it through as part of the
   objective. Full networking/Traefik convention detail lives in
   `.claude/rules/networking.md` ("Traefik reverse-proxy network").

   > ⚠️ One thing worth double-checking in the reviewed file: the router's
   > `tls.certresolver` must be set explicitly, every time - a router with
   > its own `tls: "true"` silently overrides the entrypoint's default
   > certresolver, with no error logged, and falls back to Traefik's
   > self-signed cert forever. Confirmed production bug, 2026-08-21.

   Every router also needs `traefik.http.routers.<name>.middlewares` to
   include `hsts-headers@docker` (the shared HSTS middleware defined once
   on the `traefik` service itself, rolled out repo-wide 2026-08-22) - if
   the router already needs another middleware (e.g. basicauth), append
   `,hsts-headers@docker` to the existing comma-separated value rather than
   replacing it.

   If the service uses `network_mode: host`, the backend target must be
   `traefik.http.services.<name>.loadbalancer.server.url: "http://host.docker.internal:<port>"`
   - **never `${NAS_IP}`**. Confirmed 2026-08-22 by exec'ing into the
   `traefik` container directly: its bridge networks cannot route to the
   NAS's own LAN IP at all (connection times out), only to
   `host.docker.internal` (Docker's host-gateway alias - requires
   `extra_hosts: ["host.docker.internal:host-gateway"]` on the `traefik`
   service itself, already present).

3. **DNS** - dispatch `docker-compose-architect` again, this time to add a
   line to `dnsmasq/docker-compose.yml` for the new service's hostname:
   `--address=/<service-subdomain>.${DNS_WILDCARD_DOMAIN}/${DNS_PRIVATE_IP}`,
   inserted alphabetically among the existing per-hostname override lines.
   **Every new service needs this entry, unconditionally** - not just
   services without family/guest/friends access. Since every service now
   gets a private-tier Traefik router by default (step 2), its clean private
   URL only actually resolves to Traefik's private forwarder if dnsmasq has
   this override; without it, the hostname falls through to the general
   wildcard (the NAS's own IP, not Traefik) and the private router is
   unreachable by hostname even though it exists. Confirmed as the root
   cause of repeated "not secure"/no-route bugs across many services,
   2026-08-22 - dnsmasq is confirmed permanent infrastructure here, not a
   stopgap, so this step is not optional. Skip it only if the user
   explicitly says this specific service must stay unreachable outside
   Cloudflare/family/guest/friends tiers (rare - confirm before skipping).

4. **REVIEW** - dispatch `compose-security-auditor` and
   `compose-consistency-linter` in parallel on the new file only. Both are
   read-only and never edit.

5. **FIX** - send any findings from either reviewer back to
   `docker-compose-architect` as an exact list (file, finding, required fix).
   Reviewers never edit files themselves. Re-run only the reviewer(s) that had
   findings, scoped to the new service.

6. Repeat steps 4→5 up to 3 cycles total. If findings remain after cycle 3,
   stop looping and report the residual findings to the user instead of
   continuing to iterate.

7. **HANDOFF** - close by stating:
   - the Cloudflare Tunnel connector target, `http://<container_name>:<internal_port>`,
     if the compose touches `cloudflare_web_network` (docker-compose-architect
     states this after any such change - surface it here);
   - the full list of `${VAR}`s to configure in Portainer for this stack,
     including the new per-service `${<SERVICE>_SUBDOMAIN}` var and its
     chosen value (default: the service's directory name, unless a legacy
     Cloudflare hostname already exists for it - confirm with the user);
   - a reminder that `TRAEFIK_ENTRYPOINT_*`/`TRAEFIK_PORT_*` are shared,
     repo-wide vars already set once on the `traefik` stack itself - **not**
     something to add per-service - shown here for reference only:

     | Var | Tier | Port |
     |---|---|---|
     | `TRAEFIK_ENTRYPOINT_1` / `TRAEFIK_PORT_1` | family | 443 |
     | `TRAEFIK_ENTRYPOINT_2` / `TRAEFIK_PORT_2` | guest | 8443 |
     | `TRAEFIK_ENTRYPOINT_3` / `TRAEFIK_PORT_3` | private (`asDefault`, default for new services) | 8444 |
     | `TRAEFIK_ENTRYPOINT_4` / `TRAEFIK_PORT_4` | friends | 8445 |
     | `TRAEFIK_ENTRYPOINT_5` / `TRAEFIK_PORT_5` | internal, `cloudflared`-facing only | 9080 |
     | `TRAEFIK_ENTRYPOINT_6` / `TRAEFIK_PORT_6` | internal, ping/dashboard-API only | 8080 |
   - a reminder that **`dnsmasq` needs to be redeployed** (recreated, not
     just restarted - it runs `restart: always` but a compose-file edit only
     applies on recreate) before the new service's private-tier hostname will
     actually resolve to Traefik.

## Exit condition

Both reviewers report clean, or the user has explicitly accepted residual
findings after 3 fix cycles - AND the handoff (tunnel target + `${VAR}` list)
has been delivered to the user. Do not consider the task done without the
handoff even if the compose file itself is clean.

## Out of scope

- Auditing or linting services that already exist in the repo, or a repo-wide
  sweep - that is `auditing-compose-repo`.
- Editing an existing, already-deployed service's compose file with no new
  service being added - dispatch `docker-compose-architect` directly, no
  research/review loop needed unless the user asks for one.
