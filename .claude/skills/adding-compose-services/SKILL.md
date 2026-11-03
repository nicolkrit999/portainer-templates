---
name: adding-compose-services
description: Use this skill whenever the user wants a brand-new service in this Portainer homelab repo - 'add <service> to my homelab', 'create a compose for <service>', 'deploy <service>', 'I want to self-host <service>', 'make <service> public' - even if they only name the app. It runs the full loop - research with service-researcher, build with docker-compose-architect (two Traefik routers, per-stack backend network with a registered /28, minimal env, no relative bind mounts), optionally expose it through traefik-public only, parallel review by compose-security-auditor and compose-consistency-linter, fixes, then the Portainer variable list, redeploy rule and reach-test. NOT for auditing existing services (auditing-compose-repo), extracting a stack that already runs in Portainer (migrating-portainer-stacks) or editing an already-deployed compose (dispatch docker-compose-architect directly).
---

# Adding a compose service

You (the orchestrator, in the main chat) dispatch the agents below in order and loop the review. Agents cannot call each other. Pass each one the objective and the reason, not just a service name, so its output already fits the exposure and dependencies you have in mind.

The conventions are not repeated here, so they cannot drift: they live in `.claude/rules/` (`networking.md` for routers, networks and the public path; `conventions.md`; `secrets.md`; `volumes.md`; `gotchas/portainer-relative-bind-mounts.md`) and the architect applies them. Public exposure mechanics are in `traefik-public/README.md`.

## Loop

1. **Research.** Dispatch `service-researcher` with the service name and the objective: private only or also public, what it depends on (a database, another stack), whether it needs egress or a non-HTTP port. It returns a compact spec and writes nothing.

2. **Decide with the user**, asking only what the objective leaves open:
   - Public access? Default is no (LAN and tailnet only, which needs no question). Yes means step 4 as well.
   - Volume paths: the architect proposes `${VOLUME_CONFIG}/<svc>/...` and `${VOLUME_DATA}/<svc>/...`; the user confirms them.
   - More than one container? Then a /28 is needed (and a second one for a public app's `public-<app>` network). It must be recorded in `/home/krit/momentary/proxy-research/findings/subnets.md` BEFORE the compose is written, otherwise two stacks can claim the same block.

3. **Build.** Dispatch `docker-compose-architect` with the spec and decisions. It writes `<service>/docker-compose.yml` and `<service>/.env.example` (exactly the variables the compose references). Remind it of the two traps that look fine in review but fail live: a `network_mode: host` backend needs `loadbalancer.server.url: "http://host.docker.internal:<port>"` (never `${NAS_IP}`), and a published host port bypasses Traefik, so only on explicit request after checking `service-directory.md`.

4. **Public exposure (only if requested).** Dispatch the architect again with `traefik-public/README.md` and the research notes. The change lives in `traefik-public/docker-compose.yml` and its `.env.example`, plus the app's `external: true` attachment and trusted-proxy setting. Never a router on the core Traefik, never a new WAN port. The user does the one manual step (a DNS-only CNAME to `wg.${DOMAIN}`). `traefik-public` must be deployed before the app, because it creates the network.

5. **Review.** Dispatch `compose-security-auditor` and `compose-consistency-linter` in parallel on the new file (and on `traefik-public/docker-compose.yml` if step 4 ran). Both are read-only.

6. **Fix.** Send findings to the architect as an exact list (file, finding, fix). Re-run only the reviewer(s) that had findings, scoped to the new service. Repeat review and fix up to 3 cycles in total; after that report the residue to the user instead of iterating further.

7. **Handoff.** The user deploys. State:
   - every `${VAR}` to set in the new Portainer stack: the `${<SERVICE>_SUBDOMAIN}` value (default is the directory name), secrets, `<STACK>_BACKEND_*` only if overriding, and the shared vars the compose references (`DOMAIN`, `TRAEFIK_ENTRYPOINT_3`, `TRAEFIK_ENTRYPOINT_7`, `TZ`, volume roots, `PUID`/`PGID`). Nothing the compose does not reference. For a public app, also the variables to add to the `traefik-public` stack;
   - the redeploy rule: `StackInspect` first, then `StackGitRedeploy` with the full current `Env` passed back, every time (`.claude/rules/portainer-instance.md`); never print secret values;
   - the check, once the stack is up: `/home/krit/momentary/proxy-research/tools/reach-test.sh <hostfile> tailnet` and `... lan`, with the new subdomain in the hostfile. `OK` on both is the pass criterion; the script header explains `NOROUTE`, `CERT`, `5xx` and `DOWN`. For a public app also test from outside the LAN: `curl --resolve <host>:443:<WAN-IP>` through an exit node in an allowed region, and read the `traefik-public` access log;
   - that `.claude/rules/service-directory.md` needs a row for the new hostname, and that the subnet registry now holds the allocation(s).

## Done when

Both reviewers are clean (or the user accepted the residue after 3 cycles), `.env.example` matches the compose in both directions, any /28 is in the registry, and the handoff has been delivered. A clean compose file alone is not done: the user still has to set variables and redeploy correctly.
