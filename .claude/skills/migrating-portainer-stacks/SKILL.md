---
name: migrating-portainer-stacks
description: Use this skill whenever a stack currently runs only inside Portainer (not in this repo) and the user wants it under git management - 'migrate <stack> to git', 'extract this stack from Portainer', 'bring <service> under git management', 'import the running stack', 'convert my Portainer stack to a template', 'it's only in Portainer'. It reads the live stack through the Portainer MCP, saves every real secret to a private .env BEFORE templating (once the old stack is deleted, uncaptured secrets are gone), has docker-compose-architect write the parameterized compose and .env.example, runs the security and consistency reviewers, and hands off the env diff and reach-test. NOT for brand-new services (adding-compose-services) or repo-wide audits (auditing-compose-repo).
---

# Migrating Portainer stacks

Brings a stack that exists only live in Portainer into this repo as a parameterized template without losing a secret. You run the loop in the main chat; agents cannot call each other.

The output must follow `.claude/rules/` (the architect applies it): everything parameterized, the two routers with bare TLS, `traefik-proxy` plus a registered backend /28, no relative bind mounts, and an `.env.example` listing only referenced variables. Any Cloudflare Tunnel, `cloudflare-web`, tier or SAN-group configuration in the live stack is dropped, not carried over.

## Portainer access

Follow `.claude/rules/portainer-instance.md` (environment ID `3`, `StackList` with `select`, `StackInspect` for env, `StackFileInspect` for the compose, `docker_proxy` for containers). Env values are not redacted on this server: never print them and never select `Config.Env` from a container inspect. Do not use `StackUpdate` on a git-tracked stack (it detaches it from git), and never call `StackGitRedeploy` without re-supplying the full `Env`.

## Loop

1. **Extract.** `StackList` to find the stack (names are not unique, use the id), `StackInspect` and `StackFileInspect` for env and compose, `docker_proxy` `GET /containers/json` for the running image, volumes, ports and networks. A bind source under `/data/compose/...` is the relative-mount trap in `.claude/rules/gotchas/portainer-relative-bind-mounts.md`.

2. **Capture secrets first.** Write the real values to `/home/krit/momentary/portainer-env/<service>/.env` (create the directory if missing; private, never committed) before templating, because the old stack may be deleted afterwards and uncaptured secrets are then permanently lost. Check the file is non-empty and every secret is real, not a placeholder.

3. **Template.** Dispatch `docker-compose-architect` with the extracted config. It writes `<service>/docker-compose.yml` and `<service>/.env.example` (placeholders such as `your-password-here` for every `${VAR}` it introduced, nothing unreferenced).

4. **Review.** Dispatch `compose-security-auditor` and `compose-consistency-linter` in parallel on the new file. Tell the auditor the focus: no real value may leak into the compose or `.env.example`. Send findings to the architect and repeat template and review up to 3 cycles.

5. **Handoff.** Report the compose path, the two env file paths (private real values, repo `.env.example`), the variables to keep or remove in the live stack env (only those the new compose references), and the check `/home/krit/momentary/proxy-research/tools/reach-test.sh <hostfile> tailnet|lan`. Re-pointing the old Portainer stack to git, or deleting it, is the user's step and needs the full `Env` re-supplied.

## Done when

Both reviewers are clean, the secrets are confirmed in the private `.env`, and `.env.example` holds placeholders only (no real secret, no blank required value).
