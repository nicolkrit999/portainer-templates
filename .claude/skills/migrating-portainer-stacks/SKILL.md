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
`TZ: "${TZ}"`. See `.claude/rules/` for the full conventions.

## MCP constraint (mandatory)

Per `.claude/rules/portainer-instance.md`: use ONLY
`mcp__portainer__listLocalStacks` and `mcp__portainer__dockerProxy`
(`environmentId: 3`). Never call `listStacks`, `getStackFile`, or
`listEnvironments` - they always return 503 on this instance.

## Loop (orchestrator runs this in the main chat; agents cannot call each other)

1. **EXTRACT** (main chat) - `mcp__portainer__listLocalStacks` to find the
   target stack; `mcp__portainer__dockerProxy` with `GET /containers/json`
   (environmentId 3) to capture the running config: image+tag, env values,
   volumes, ports, networks.
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
   (momentary real values + repo `.env.example`), the Cloudflare connector
   target if the service is networked, and a reminder that the old Portainer
   stack can now be re-pointed or deleted.

## Exit condition

Both reviewers report clean, secrets are confirmed captured in the momentary
`.env`, and `.env.example` contains placeholder values only (no real
secrets, no empty required values).

## Out of scope

- Brand-new services never deployed anywhere: use `adding-compose-services`.
- Repo-wide consistency audits across already-migrated stacks: use
  `auditing-compose-repo`.
