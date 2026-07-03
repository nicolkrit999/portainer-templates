---
name: adding-compose-services
description: Use this skill when the user wants to bring a brand-new service into this Portainer homelab repo. Trigger phrases include 'add <service> to my homelab', 'set up <service> behind the tunnel', 'create a compose for <service>', 'deploy <service>', 'I want to self-host <service>'. It researches the service, has docker-compose-architect create the new `<service>/docker-compose.yml` per repo rules, runs compose-security-auditor and compose-consistency-linter in parallel, loops fixes back through docker-compose-architect, and hands off the Cloudflare Tunnel target plus the full list of `${VAR}`s to set in Portainer. It does NOT cover auditing or linting services that already exist across the repo (use auditing-compose-repo for that) and it does NOT cover editing an already-deployed service's compose file (dispatch docker-compose-architect directly for that).
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

3. **REVIEW** - dispatch `compose-security-auditor` and
   `compose-consistency-linter` in parallel on the new file only. Both are
   read-only and never edit.

4. **FIX** - send any findings from either reviewer back to
   `docker-compose-architect` as an exact list (file, finding, required fix).
   Reviewers never edit files themselves. Re-run only the reviewer(s) that had
   findings, scoped to the new service.

5. Repeat steps 3→4 up to 3 cycles total. If findings remain after cycle 3,
   stop looping and report the residual findings to the user instead of
   continuing to iterate.

6. **HANDOFF** - close by stating:
   - the Cloudflare Tunnel connector target, `http://<container_name>:<internal_port>`,
     if the compose touches `cloudflare_web_network` (docker-compose-architect
     states this after any such change - surface it here);
   - the full list of `${VAR}`s to configure in Portainer for this stack.

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
