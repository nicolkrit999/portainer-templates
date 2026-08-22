---
name: adding-compose-services
description: Use this skill when the user wants to bring a brand-new service into this Portainer homelab repo. Trigger phrases include 'add <service> to my homelab', 'set up <service> behind the tunnel', 'create a compose for <service>', 'deploy <service>', 'I want to self-host <service>'. It researches the service, has docker-compose-architect create the new `<service>/docker-compose.yml` per repo rules - Cloudflare Tunnel AND Traefik ALWAYS added together (private tier by default, other tiers only if the user asks, no confirmation needed either way), HSTS on every router - adds the matching DNS overrides in `dnsmasq` AND `dnsmasq-tailnet` (required for every service, not optional), assigns the service to a SAN-bundle certificate group (existing group if it fits, otherwise asks the user - never silently invented), runs compose-security-auditor and compose-consistency-linter in parallel, loops fixes back through docker-compose-architect, and hands off the Cloudflare Tunnel target plus the full list of `${VAR}`s to set in Portainer. It does NOT cover auditing or linting services that already exist across the repo (use auditing-compose-repo for that) and it does NOT cover editing an already-deployed service's compose file (dispatch docker-compose-architect directly for that).
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
   **creates `<service>/.env.example` listing every `${VAR}` the compose file
   uses with a real placeholder/default value (never blank, secrets get an
   obviously-fake placeholder)** whenever the compose references any `${VAR}`
   at all (virtually always, given TZ/hostname conventions - genuinely skip
   this only for the rare service with zero vars) - a real file, not just a
   chat summary of vars - and lists every `${VAR}` that must be set in Portainer.

   **Cloudflare and Traefik are always added together, never just one** -
   the only exception is a service that needs neither at all (e.g. `attic`,
   a LAN-only tool with no remote-access need), which is rare and should be
   obvious from the objective, not assumed by default. **Traefik access
   defaults to the `private` tier only, and that private-tier router can
   never be omitted once Traefik is present at all** - if the prompt
   doesn't say otherwise, it's private, full stop, no confirmation needed.
   Only ask the user about `family`/`guest`/`friends` if the objective you
   were given doesn't already specify - and when one of those tiers is
   added, it's additive on top of the private router, never a replacement
   for it. Full networking/Traefik convention detail lives in
   `.claude/rules/networking.md` ("Traefik reverse-proxy network").

   **Every router needs `hsts-headers@docker` in its `middlewares` list**
   (append to any existing middleware value, don't replace it) - omit only
   for a genuinely good, explicit reason, and flag/explain it if you do.

   > ⚠️ One thing worth double-checking in the reviewed file: the router's
   > `tls.certresolver` must be set explicitly, every time - a router with
   > its own `tls: "true"` silently overrides the entrypoint's default
   > certresolver, with no error logged, and falls back to Traefik's
   > self-signed cert forever. Confirmed production bug, 2026-08-21.

   If the service uses `network_mode: host`, the backend target must be
   `traefik.http.services.<name>.loadbalancer.server.url: "http://host.docker.internal:<port>"`
   - **never `${NAS_IP}`**. Confirmed 2026-08-22 by exec'ing into the
   `traefik` container directly: its bridge networks cannot route to the
   NAS's own LAN IP at all (connection times out), only to
   `host.docker.internal` (Docker's host-gateway alias - requires
   `extra_hosts: ["host.docker.internal:host-gateway"]` on the `traefik`
   service itself, already present).

3. **DNS** - dispatch `docker-compose-architect` again to add the new
   service's hostname to **both** `dnsmasq/docker-compose.yml` (LAN) and
   `dnsmasq-tailnet/docker-compose.yml` (Tailscale), unless the new
   service is itself part of the admin-gated tailnet-only set (rare -
   check `.claude/rules/core-infra-topology.md` if unsure which applies).
   Standard LAN line: `--address=/<service-subdomain>.${DNS_WILDCARD_DOMAIN}/${DNS_PRIVATE_IP}`,
   inserted alphabetically among the existing per-hostname override lines.
   **Every new service needs the LAN entry, unconditionally** - not just
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
   `dnsmasq-tailnet` usually needs no per-service change at all (it answers
   the whole domain with one wildcard IP already) - only add a specific
   override there if this service is being added to the admin-gated
   tailnet-only set, which is a distinct, separate effort, not part of
   ordinary new-service onboarding.

   This is routine, expected maintenance of these files (see
   `.claude/rules/core-infra-topology.md`'s note on the difference between
   this kind of edit and a structural change) - do it without asking.

4. **SAN GROUP** - dispatch `docker-compose-architect` again to add the
   new service to a SAN-bundle certificate group, per
   `.claude/rules/san-cert-groups.md` (read it fully - explains the 6
   existing groups, the anchor-router mechanism, and why skipping this
   risks Let's Encrypt's rate limit: 50 new certs per registered domain
   per 168 hours, easily exhausted at one-cert-per-router). If an existing
   group's theme genuinely fits, add the hostname to that group's anchor
   router's `tls.domains[0].sans` (plus a matching env var on the
   anchor's own `.env.example`, value taken from THIS service's own real
   hostname - never invented). The new service's own router(s) get bare
   `tls: "true"`, no `certresolver`, no `tls.domains` of their own - same
   as every other non-anchor router in that group. **If no group fits
   well, or you're not sure, stop and ask the user** - propose the
   closest-fitting existing group, or a new group with reasoning, don't
   guess. **Once deployed, write the new member into the table in
   `.claude/rules/san-cert-groups.md`** - this is a required last step,
   not optional cleanup.

   ⚠️ **This is the new service's OWN `.env.example` value you're adding
   to the anchor's file - always verify it against the new service's own
   compose file and (if it's already deployed elsewhere/live) its actual
   configured Portainer env, never just assume the directory name or copy
   a value from memory.** Confirmed real bug: an anchor's `.env.example`
   ended up with a sibling's STALE default value (`holyclaude`) while that
   sibling's actual live, deployed hostname was different (`claude`) -
   `.env.example` defaults can drift from what's really configured and
   must not be trusted blindly, only from a fresh read of the source of
   truth (the sibling's own compose file's `Host()` rule, or its live
   Portainer env if you can check it).

5. **REVIEW** - dispatch `compose-security-auditor` and
   `compose-consistency-linter` in parallel on the new file only. Both are
   read-only and never edit.

6. **FIX** - send any findings from either reviewer back to
   `docker-compose-architect` as an exact list (file, finding, required fix).
   Reviewers never edit files themselves. Re-run only the reviewer(s) that had
   findings, scoped to the new service.

7. Repeat steps 5→6 up to 3 cycles total. If findings remain after cycle 3,
   stop looping and report the residual findings to the user instead of
   continuing to iterate.

8. **HANDOFF** - close by stating:
   - the Cloudflare Tunnel connector target, `http://<container_name>:<internal_port>`,
     if the compose touches `cloudflare_web_network` (docker-compose-architect
     states this after any such change - surface it here);
   - the full list of `${VAR}`s to configure in Portainer for this stack,
     including the new per-service `${<SERVICE>_SUBDOMAIN}` var and its
     chosen value (default: the service's directory name, unless a legacy
     Cloudflare hostname already exists for it - confirm with the user), and
     the new `${..._SUBDOMAIN}` var added to the SAN group anchor's own
     `.env.example` from step 4, which must be set on the **anchor's**
     Portainer stack, not the new service's;
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
   - a reminder that **`dnsmasq` (and `dnsmasq-tailnet`, if touched) needs
     to be redeployed** (recreated, not just restarted - it runs
     `restart: always` but a compose-file edit only applies on recreate)
     before the new service's hostname will actually resolve correctly;
   - a reminder that the **SAN group anchor's stack also needs redeploying**
     to pick up its updated `tls.domains[0].sans` and new env var - and per
     `.claude/rules/portainer-instance.md`, always re-fetch and re-supply
     that stack's full `Env` on that redeploy, never omit it.

## Exit condition

Both reviewers report clean, or the user has explicitly accepted residual
findings after 3 fix cycles - AND the handoff (tunnel target + `${VAR}` list)
has been delivered to the user - AND the service has a SAN group (step 4,
with `.claude/rules/san-cert-groups.md` updated) and its DNS entries (step
3) in place. Do not consider the task done without all of this, even if
the compose file itself is clean.

## Out of scope

- Auditing or linting services that already exist in the repo, or a repo-wide
  sweep - that is `auditing-compose-repo`.
- Editing an existing, already-deployed service's compose file with no new
  service being added - dispatch `docker-compose-architect` directly, no
  research/review loop needed unless the user asks for one.
