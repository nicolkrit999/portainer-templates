---
name: migrating-portainer-stacks
description: Use this skill when bringing a stack that is currently only running in Portainer under git management in this repo, extracting its live configuration, and templating it per repo conventions. Triggers include 'migrate <stack> to git', 'extract this stack from Portainer', 'bring <service> under git management', 'import the running stack', 'convert my Portainer stack to a template'. Does NOT cover brand-new services that have never been deployed (use adding-compose-services) and does NOT cover repo-wide audits of already-migrated stacks (use auditing-compose-repo).
---

# Migrating Portainer stacks

Brings a stack that only exists live in Portainer into this repo as a fully
parameterized compose template, while capturing every secret before it can
be lost.

## Repo conventions the output must follow

Everything parameterized: `${VOLUME_CONFIG}` / `${VOLUME_DATA}`,
`${ADMIN_USER}` / `${PUID}` / `${PGID}` (quoted), `<svc>.${DOMAIN}`,
`TZ: "${TZ}"`. The routing follows the current model: a `<svc>-private` and a
`<svc>-tailnet` router with bare `tls: "true"`, `traefik-proxy` attached, a
`<stack>-backend` network with an explicit /28 (subnet registry) for databases and
helpers, no relative bind mounts, and an `.env.example` that lists only the
variables the compose references. Any Cloudflare Tunnel / `cloudflare-web` / tier /
SAN-group configuration found in the live stack is dropped, not carried over. See
`.claude/rules/` for the full conventions.

## MCP usage (mandatory)

Per `.claude/rules/portainer-instance.md`: environment ID is `3`. List stacks with
`mcp__portainer__StackList` (project with `select`), read a stack's live env with
`mcp__portainer__StackInspect` (`select: Env`) and its compose file with
`mcp__portainer__StackFileInspect`, inspect containers through
`mcp__portainer__docker_proxy`. Never select `Config.Env` from a container inspect and
never print secret values in chat. Do NOT use `StackUpdate` on a git-tracked stack (it
detaches it from git) and never `StackGitRedeploy` without re-supplying the full `Env`.

## Loop (orchestrator runs this in the main chat; agents cannot call each other)

1. **EXTRACT** (main chat) - `mcp__portainer__StackList` to find the target stack
   (names are not unique; use the id), `StackInspect`/`StackFileInspect` for its env
   and compose, and `mcp__portainer__docker_proxy` with `GET /containers/json`
   (environmentId 3) to capture the running config: image+tag, volumes, ports,
   networks. For a relative-path bind source in the live file (`/data/compose/...`),
   see `.claude/rules/gotchas/portainer-relative-bind-mounts.md`.
2. **CAPTURE SECRETS FIRST** (main chat, before templating) - write all real
   values to `/home/krit/momentary/portainer-env/<service>/.env`. This must
   happen before step 3 because once the original stack is deleted,
   uncaptured secrets are permanently lost. Verify the file is non-empty and
   every secret has a real value, not a placeholder.
3. **TEMPLATE** - dispatch `docker-compose-architect` (sonnet) with the
   extracted config. It writes `<service>/docker-compose.yml` fully
   parameterized per repo rules, plus `.env.example` with placeholder values
   (e.g. `your-password-here`) matching every `${VAR}` it introduced.
4. **REVIEW** - dispatch `compose-security-auditor` (opus, read-only) and
   `compose-consistency-linter` (haiku, read-only) on the new file in
   parallel. The auditor's focus here is specifically that no real value
   leaked into the committed compose or `.env.example`. Send findings back
   to `docker-compose-architect` to fix; repeat step 3→4 up to 3 cycles.
5. **HANDOFF** - report: the compose file path, the two `.env` file paths
   (momentary real values + repo `.env.example`), the variables to keep in or remove
   from the live stack env (only variables the new compose references), the
   `reach-test.sh` command for the hostname (`/home/krit/momentary/proxy-research/tools/reach-test.sh`,
   `tailnet` and `lan`), and a reminder that the old Portainer stack can now be
   re-pointed or deleted (re-pointing a stack to git needs the full `Env` re-supplied).

## Exit condition

Both reviewers report clean, secrets are confirmed captured in the momentary
`.env`, and `.env.example` contains placeholder values only (no real
secrets, no empty required values).

## Out of scope

- Brand-new services never deployed anywhere: use `adding-compose-services`.
- Repo-wide consistency audits across already-migrated stacks: use
  `auditing-compose-repo`.
